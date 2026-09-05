"""Background scheduler for WhatsApp customer support tasks.

Runs periodic jobs:
1. Poll Daraz for new orders → trigger order confirmation via WhatsApp
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv
from sqlmodel import Session, select

from neurocom_backend.database.connection import engine
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.database.models.marketplace import Marketplace, MarketplaceConnection
from neurocom_backend.models.daraz_model import OrdersWithItemsResponse
from neurocom_backend.database.models.whatsapp_support import (
    MerchantSupportConfig,
    WhatsAppConversation,
    ConfirmationStatus,
    ConversationStatus,
    MessageRole,
    WhatsAppMessage,
)
from neurocom_backend.services.whatsapp_agent_service import (
    initiate_order_confirmation,
)
from neurocom_backend.utils.security import decrypt_value

_: bool = load_dotenv()
logger = logging.getLogger(__name__)

ORDER_POLL_INTERVAL = int(os.getenv("WHATSAPP_ORDER_POLL_INTERVAL", "600"))  # 10 minutes

_processed_order_ids: set[str] = set()


async def poll_daraz_orders():
    """Poll Daraz for new orders and trigger WhatsApp confirmation.

    Runs every ORDER_POLL_INTERVAL seconds. For each merchant with WhatsApp
    enabled and auto-confirm on, checks for new orders since the last poll.
    """

    logger.info("Starting Daraz order poll for WhatsApp confirmations...")

    with Session(engine) as db:
        # Find all merchants with WhatsApp auto-confirm enabled
        configs = db.exec(
            select(MerchantSupportConfig).where(
                MerchantSupportConfig.is_whatsapp_enabled == True,
                MerchantSupportConfig.auto_confirm_orders == True,
            )
        ).all()

        for config in configs:
            try:
                await _process_merchant_orders(db, config)
            except Exception:
                logger.exception("Failed to process orders for merchant %s", config.merchant_id)

    logger.info("Daraz order poll completed")


async def _process_merchant_orders(db: Session, config: MerchantSupportConfig):
    """Process new Daraz orders for a single merchant."""
    from neurocom_backend.services.daraz_service import get_orders_with_items

    merchant_id = config.merchant_id

    marketplace = db.exec(
        select(Marketplace).where(Marketplace.name == "Daraz")
    ).first()
    if not marketplace:
        logger.debug("No Daraz marketplace found for merchant %s", merchant_id)
        return

    connection = db.exec(
        select(MarketplaceConnection).where(
            MarketplaceConnection.merchant_id == merchant_id,
            MarketplaceConnection.marketplace_id == marketplace.id,
        )
    ).first()
    if not connection or not connection.encrypted_access_token:
        logger.debug("No Daraz connection for merchant %s", merchant_id)
        return

    try:
        access_token = decrypt_value(connection.encrypted_access_token)
    except Exception:
        logger.exception("Failed to decrypt Daraz token for merchant %s", merchant_id)
        return

    # Fetch recent orders (last 24 hours)
    pk_tz = timezone(timedelta(hours=5))
    utc8_tz = timezone(timedelta(hours=8))
    since = (datetime.now(pk_tz).astimezone(utc8_tz) - timedelta(minutes=35)).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    try:
        print("orders since start_date: ", since)
        orders_data = get_orders_with_items(access_token, start_date=since)
        orders = orders_data.get("orders", [])
    except Exception:
        logger.exception("Failed to fetch Daraz orders for merchant %s", merchant_id)
        return

    new_order_count = 0
    print("orders found: ", orders)
    for order in orders:
        order_id = str(order.get("order_id", ""))
        if not order_id or order_id in _processed_order_ids:
            continue

        existing = db.exec(
            select(WhatsAppConversation).where(
                WhatsAppConversation.merchant_id == merchant_id,
                WhatsAppConversation.daraz_order_id == order_id,
            )
        ).first()
        if existing:
            _processed_order_ids.add(order_id)
            continue

        customer_phone = _extract_customer_phone(order)
        if not customer_phone:
            logger.debug("No customer phone for Daraz order %s", order_id)
            continue

        customer_name = order.get("customer_first_name", "Customer")

        # Trigger confirmation
        try:
            initiate_order_confirmation(
                db=db,
                merchant_id=merchant_id,
                daraz_order_id=order_id,
                customer_phone=customer_phone,
                customer_name=customer_name,
                order_details=order,
            )
            _processed_order_ids.add(order_id)
            new_order_count += 1
            logger.info("Triggered confirmation for order %s (customer: %s)", order_id, customer_phone)
        except Exception:
            logger.exception("Failed to trigger confirmation for order %s", order_id)

    if new_order_count:
        logger.info("Merchant %s: triggered %d new order confirmations", merchant_id, new_order_count)


def _extract_customer_phone(order: dict) -> Optional[str]:
    for addr_key in ("address_billing", "address_shipping"):
        addr = order.get(addr_key, {})
        if isinstance(addr, dict):
            phone = addr.get("phone") or addr.get("phone2")
            if phone:
                print("Found customer phone: ", phone)
                return _normalize_phone(phone)

    phone = order.get("customer_phone") or order.get("phone")
    if phone:
        return _normalize_phone(phone)

    return None


def _normalize_phone(phone: str) -> str:
    """Normalize phone number to E.164 format (no + prefix, no spaces)."""
    cleaned = "".join(c for c in str(phone) if c.isdigit())
    if cleaned.startswith("0"):
        cleaned = "92" + cleaned[1:]
    if len(cleaned) < 10:
        return ""
    return cleaned

async def _scheduler_loop():
    """Main scheduler loop that runs all periodic tasks."""
    logger.info("WhatsApp scheduler started (poll=%ds)",
                ORDER_POLL_INTERVAL)

    while True:
        try:
            await poll_daraz_orders()

        except Exception:
            logger.exception("Scheduler loop error")

        await asyncio.sleep(ORDER_POLL_INTERVAL)


def start_scheduler():
    """Background scheduler for cron jobs."""
    loop = asyncio.get_event_loop()
    task = loop.create_task(_scheduler_loop())
    logger.info("WhatsApp scheduler task created")
    return task
