"""WhatsApp Customer Support Router.

Endpoints:
- Webhook verification (GET) and message receiver (POST) — public, no auth
- Merchant config management — authenticated
- Conversation history & summary — authenticated
- Manual order confirmation trigger — authenticated
"""

import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.database.models.whatsapp_support import (
    ConfirmationStatus,
    ConversationStatus,
    GenerateSummaryRequest,
    MerchantSupportConfig,
    MerchantSupportConfigRead,
    MerchantSupportConfigUpdate,
    TriggerConfirmationRequest,
    WhatsAppConversation,
    WhatsAppConversationRead,
    WhatsAppMessage,
    WhatsAppMessageRead,
)
from neurocom_backend.dependencies import get_current_user
from neurocom_backend.services.whatsapp_agent_service import (
    generate_conversation_summary,
    initiate_order_confirmation,
    process_incoming_message,
)
from neurocom_backend.services.whatsapp_service import (
    parse_webhook_event,
    verify_webhook,
)
from neurocom_backend.utils.settings import WHATSAPP_VERIFY_TOKEN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp/support", tags=["WhatsApp Customer Support"])


# ── Webhook endpoints (public — no auth) ─────────────────────────────────────

@router.get("/webhook")
async def whatsapp_webhook_verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    """WhatsApp webhook verification endpoint.

    Meta sends a GET request to verify the webhook URL.
    We must echo back the challenge string if the token matches.
    """
    result = verify_webhook(mode or "", token or "", challenge or "")
    if result is not None:
        return int(result) if result.isdigit() else result
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook")
async def whatsapp_webhook_event(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_session)],
):
    """Receive incoming WhatsApp messages and status updates.

    Processes the webhook payload and dispatches message handling
    as a background task to respond quickly to Meta.
    """
    try:
        payload = await request.json()
        print("payload received from webhook: ", payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")

    events = parse_webhook_event(payload)
    if not events:
        return {"status": "ok", "events_processed": 0}

    for event in events:
        if event["type"] == "status":
            logger.debug("Message status: %s for %s", event.get("status"), event.get("message_id"))
            continue

        # Process incoming customer message
        customer_phone = event.get("from_", "")
        message_text = event.get("text", "")
        button_payload = event.get("button_payload")

        if not customer_phone or not message_text:
            continue

        # Find the merchant this phone number belongs to via active conversations
        # We look across all merchants — in production, you'd scope this better
        conversations = db.exec(
            select(WhatsAppConversation).where(
                WhatsAppConversation.customer_phone == customer_phone,
                WhatsAppConversation.status == ConversationStatus.ACTIVE,
            )
        ).all()

        for conv in conversations:
            background_tasks.add_task(
                _process_message_bg,
                conv.merchant_id,
                customer_phone,
                message_text,
                button_payload,
                conv.daraz_order_id,
            )

    return {"status": "ok", "events_processed": len(events)}


async def _process_message_bg(
    merchant_id: UUID,
    customer_phone: str,
    message_text: str,
    button_payload: Optional[str],
    daraz_order_id: Optional[str],
):
    """Background task wrapper for processing incoming messages."""
    from neurocom_backend.database.connection import engine
    with Session(engine) as bg_session:
        process_incoming_message(
            db=bg_session,
            merchant_id=merchant_id,
            customer_phone=customer_phone,
            message_text=message_text,
            button_payload=button_payload,
            daraz_order_id=daraz_order_id,
        )


# ── Merchant config endpoints (authenticated) ────────────────────────────────

@router.get("/config", response_model=MerchantSupportConfigRead)
async def get_support_config(
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    """Get the merchant's WhatsApp support configuration."""
    config = db.exec(
        select(MerchantSupportConfig).where(
            MerchantSupportConfig.merchant_id == merchant.id
        )
    ).first()
    if not config:
        # Auto-create with defaults
        config = MerchantSupportConfig(merchant_id=merchant.id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.put("/config", response_model=MerchantSupportConfigRead)
async def update_support_config(
    update: MerchantSupportConfigUpdate,
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    """Update the merchant's WhatsApp support configuration."""
    config = db.exec(
        select(MerchantSupportConfig).where(
            MerchantSupportConfig.merchant_id == merchant.id
        )
    ).first()
    if not config:
        config = MerchantSupportConfig(merchant_id=merchant.id)
        db.add(config)
        db.commit()
        db.refresh(config)

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    from datetime import datetime, timezone
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    return config


# ── Order confirmation trigger (authenticated) ───────────────────────────────

@router.post("/confirm-order", response_model=WhatsAppConversationRead)
async def trigger_order_confirmation(
    req: TriggerConfirmationRequest,
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    """Manually trigger order confirmation for a Daraz order.

    Sends a WhatsApp template message to the customer with Confirm/Cancel buttons.
    """
    conversation = initiate_order_confirmation(
        db=db,
        merchant_id=merchant.id,
        daraz_order_id=req.daraz_order_id,
        customer_phone=req.customer_phone,
        customer_name=req.customer_name,
        order_details=req.order_details,
    )
    return conversation


# ── Conversation endpoints (authenticated) ───────────────────────────────────

@router.get("/conversations", response_model=list[WhatsAppConversationRead])
async def list_conversations(
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    status: Optional[ConversationStatus] = None,
    confirmation_status: Optional[ConfirmationStatus] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List conversations for the authenticated merchant."""
    query = select(WhatsAppConversation).where(
        WhatsAppConversation.merchant_id == merchant.id
    )
    if status:
        query = query.where(WhatsAppConversation.status == status)
    if confirmation_status:
        query = query.where(WhatsAppConversation.confirmation_status == confirmation_status)

    query = query.order_by(WhatsAppConversation.last_message_at.desc()).offset(offset).limit(limit)
    conversations = db.exec(query).all()
    return conversations


@router.get("/conversations/{conversation_id}", response_model=WhatsAppConversationRead)
async def get_conversation(
    conversation_id: UUID,
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    """Get a specific conversation with all messages."""
    conversation = db.exec(
        select(WhatsAppConversation).where(
            WhatsAppConversation.id == conversation_id,
            WhatsAppConversation.merchant_id == merchant.id,
        )
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.post("/conversations/summary")
async def get_conversation_summary(
    req: GenerateSummaryRequest,
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    """Generate an AI summary of a customer conversation.

    Returns summary, action items, and customer sentiment.
    """
    summary = generate_conversation_summary(
        db=db,
        conversation_id=req.conversation_id,
        merchant_id=merchant.id,
    )
    if "error" in summary:
        raise HTTPException(status_code=404, detail=summary["error"])
    return summary


@router.get("/stats")
async def get_confirmation_stats(
    merchant: Annotated[Merchant, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
):
    """Get order confirmation statistics for the merchant dashboard."""
    conversations = db.exec(
        select(WhatsAppConversation).where(
            WhatsAppConversation.merchant_id == merchant.id
        )
    ).all()

    stats = {
        "total_conversations": len(conversations),
        "confirmed": sum(1 for c in conversations if c.confirmation_status == ConfirmationStatus.CONFIRMED),
        "cancelled": sum(1 for c in conversations if c.confirmation_status == ConfirmationStatus.CANCELLED),
        "pending": sum(1 for c in conversations if c.confirmation_status == ConfirmationStatus.SENT),
        "no_response": sum(1 for c in conversations if c.confirmation_status == ConfirmationStatus.NO_RESPONSE),
        "escalated": sum(1 for c in conversations if c.confirmation_status == ConfirmationStatus.ESCALATED),
        "modified": sum(1 for c in conversations if c.confirmation_status == ConfirmationStatus.MODIFIED),
    }

    total_with_resolution = stats["confirmed"] + stats["cancelled"]
    if total_with_resolution > 0:
        stats["confirmation_rate"] = round(stats["confirmed"] / total_with_resolution * 100, 1)
    else:
        stats["confirmation_rate"] = 0.0

    return stats
