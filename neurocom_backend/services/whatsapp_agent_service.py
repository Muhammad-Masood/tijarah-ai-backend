"""WhatsApp Customer Support Agent Service.

AI-powered customer support for Daraz orders via WhatsApp:
- Order confirmation flow (confirm / cancel / modify)
- Context-aware Q&A using order details + merchant instructions
- Conversation summary generation for merchants
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from openai import OpenAI
from sqlmodel import Session, select
from dotenv import load_dotenv
import os

from neurocom_backend.database.models.whatsapp_support import (
    WhatsAppConversation,
    WhatsAppMessage,
    MerchantSupportConfig,
    ConfirmationStatus,
    ConversationStatus,
    MessageRole,
)
from neurocom_backend.models.daraz_model import OrdersWithItemsResponse
from neurocom_backend.services.whatsapp_service import (
    send_text_message,
    send_order_confirmation_template,
    send_interactive_buttons,
)

_: bool = load_dotenv()
logger = logging.getLogger(__name__)

# Use the existing OpenAI-compatible client (OpenRouter)
_agent_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPEN_ROUTER_AI_API_KEY") or os.getenv("OPENAI_API_KEY"),
)

_MODEL = os.getenv("WHATSAPP_AGENT_MODEL", "openai/gpt-4o-mini")


# ── System prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are a helpful customer support assistant for a merchant's {marketplace} store called "{merchant_name}".

You are communicating with a customer via WhatsApp. Be friendly, concise, and professional.

## Current Order Context
- Order ID: {order_id}
- Customer Name: {customer_name}
- Order Total: {order_total}
- Order Status: {order_status}
- Order Items: {order_items}

## Your Primary Task
The customer placed an order and needs to confirm it. Guide them to:
1. Confirm the order
2. Cancel the order
3. Request modifications (color, size, quantity, etc.)

## Merchant Instructions
{merchant_instructions}

## Response Guidelines
- Keep messages SHORT (WhatsApp messages should be concise, max 2-3 sentences)
- Use simple language — the customer may not be tech-savvy
- If the customer asks something outside your scope, say you'll connect them with the merchant
- Never share sensitive information (payment details, other customers' info)
- If the customer confirms → respond with confirmation and say the order will be processed
- If the customer cancels → acknowledge and say the cancellation is noted
- If the customer wants modifications → note the changes and confirm what was changed
- For any other questions, answer based on the order context and merchant instructions

## Response Format
Always respond with a JSON object:
{{
    "reply": "your message to the customer",
    "action": "none" | "confirm" | "cancel" | "modify" | "escalate",
    "action_details": null | {{"field": "value"}}
}}

- action "confirm": customer confirmed the order
- action "cancel": customer wants to cancel
- action "modify": customer wants changes (include details in action_details)
- action "escalate": customer needs human merchant assistance
- action "none": general Q&A, no status change
"""


# ── Core agent logic ─────────────────────────────────────────────────────────

def _build_system_prompt(
    merchant_name: str,
    order_id: str,
    customer_name: str,
    order_total: str,
    order_status: str,
    order_items: str,
    merchant_instructions: str,
    marketplace: str = "Daraz",
) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        marketplace=marketplace,
        merchant_name=merchant_name,
        order_id=order_id,
        customer_name=customer_name,
        order_total=order_total,
        order_status=order_status,
        order_items=order_items,
        merchant_instructions=merchant_instructions or "No specific instructions. Use your best judgment.",
    )


def _call_agent(messages: list[dict]) -> dict:
    """Call the AI agent and parse the JSON response."""
    try:
        response = _agent_client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except json.JSONDecodeError:
        logger.exception("Agent returned non-JSON response")
        return {"reply": content or "Let me check on that for you.", "action": "none", "action_details": None}
    except Exception:
        logger.exception("Agent call failed")
        return {"reply": "I'm having trouble right now. Let me connect you with our team shortly.", "action": "escalate", "action_details": None}


def _build_conversation_messages(conversation: WhatsAppConversation, db: Session) -> list[dict]:
    """Build the message history for the agent from DB."""
    db_messages = db.exec(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.conversation_id == conversation.id)
        .order_by(WhatsAppMessage.created_at)
    ).all()

    history = []
    for msg in db_messages:
        role = "user" if msg.role == MessageRole.USER else "assistant"
        history.append({"role": role, "content": msg.content})
    return history


# ── Public API ───────────────────────────────────────────────────────────────

def initiate_order_confirmation(
    db: Session,
    merchant_id: UUID,
    daraz_order_id: str,
    customer_phone: str,
    customer_name: Optional[str] = None,
    order_details: Optional[dict] = None,
) -> WhatsAppConversation:
    """Start the order confirmation flow for a Daraz order.

    Creates a conversation record and sends the WhatsApp template message.
    """
    # Check if conversation already exists for this order
    existing = db.exec(
        select(WhatsAppConversation).where(
            WhatsAppConversation.merchant_id == merchant_id,
            WhatsAppConversation.daraz_order_id == daraz_order_id,
        )
    ).first()
    if existing:
        logger.info("Conversation already exists for order %s", daraz_order_id)
        return existing

    # Get merchant config for merchant name
    merchant_config = db.exec(
        select(MerchantSupportConfig).where(MerchantSupportConfig.merchant_id == merchant_id)
    ).first()

    # Extract order info
    order_total = str(order_details.get("price", "N/A")) if order_details else "N/A"
    order_items = ""
    if order_details and "items" in order_details:
        items_list = []
        for item in order_details["items"]:
            name = item.get("name", item.get("product_name", "Item"))
            qty = item.get("items_count", item.get("quantity", 1))
            items_list.append(f"{name} x{qty}")
        order_items = ", ".join(items_list)

    # Create conversation
    conversation = WhatsAppConversation(
        merchant_id=merchant_id,
        daraz_order_id=daraz_order_id,
        customer_phone=customer_phone,
        customer_name=customer_name,
        status=ConversationStatus.ACTIVE,
        confirmation_status=ConfirmationStatus.SENT,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    # Send the WhatsApp template message
    try:
        merchant_name = "Our Store"
        if merchant_config and merchant_config.whatsapp_phone_number:
            merchant_name = merchant_config.whatsapp_phone_number

        send_order_confirmation_template(
            to=customer_phone,
            customer_name=customer_name or "Customer",
            order_id=daraz_order_id,
            total_amount=order_total,
            merchant_name=merchant_name,
        )

        # Record the outbound message
        outbound_msg = WhatsAppMessage(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=f"Order confirmation template sent for order {daraz_order_id}",
            metadata_json=json.dumps({"type": "template", "template_name": "order_confirmation"}),
        )
        db.add(outbound_msg)
        conversation.last_message_at = datetime.now(timezone.utc)
        db.commit()

    except Exception:
        logger.exception("Failed to send order confirmation template for order %s", daraz_order_id)
        conversation.confirmation_status = ConfirmationStatus.PENDING
        db.commit()

    return conversation


def process_incoming_message(
    db: Session,
    merchant_id: UUID,
    customer_phone: str,
    message_text: str,
    button_payload: Optional[str] = None,
    daraz_order_id: Optional[str] = None,
) -> Optional[WhatsAppConversation]:
    """Process an incoming WhatsApp message from a customer.

    Finds the active conversation, runs it through the AI agent,
    updates confirmation status, and sends the reply.
    """
    # Find active conversation for this customer
    conversation = _find_active_conversation(db, merchant_id, customer_phone, daraz_order_id)
    if not conversation:
        logger.info("No active conversation found for %s (order=%s)", customer_phone, daraz_order_id)
        return None

    # Handle button payload directly (fast path for confirm/cancel)
    if button_payload:
        action = _handle_button_payload(button_payload)
        if action:
            _apply_action(db, conversation, action, {"source": "button"})
            return conversation

    # Record the incoming customer message
    incoming_msg = WhatsAppMessage(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=message_text,
    )
    db.add(incoming_msg)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.commit()

    # Build agent context
    merchant_config = db.exec(
        select(MerchantSupportConfig).where(MerchantSupportConfig.merchant_id == merchant_id)
    ).first()

    # Get merchant name from the Merchant table
    from neurocom_backend.database.models.merchant import Merchant
    merchant = db.get(Merchant, merchant_id)
    merchant_name = merchant.business_name if merchant else "Our Store"

    # Build order context (simplified — in production, fetch from Daraz API)
    order_items = "See order details"
    order_total = "See order details"

    system_prompt = _build_system_prompt(
        merchant_name=merchant_name,
        order_id=conversation.daraz_order_id or "N/A",
        customer_name=conversation.customer_name or "Customer",
        order_total=order_total,
        order_status=conversation.confirmation_status.value,
        order_items=order_items,
        merchant_instructions=merchant_config.custom_instructions if merchant_config else "",
    )

    # Build message history
    history = _build_conversation_messages(conversation, db)
    messages = [{"role": "system", "content": system_prompt}] + history

    # Call the AI agent
    agent_response = _call_agent(messages)

    # Record the agent's reply in DB
    reply_text = agent_response.get("reply", "I'll get back to you shortly.")
    action = agent_response.get("action", "none")
    action_details = agent_response.get("action_details")

    outbound_msg = WhatsAppMessage(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=reply_text,
        metadata_json=json.dumps({"action": action, "action_details": action_details}),
    )
    db.add(outbound_msg)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.commit()

    # Apply any status-changing action
    if action != "none":
        _apply_action(db, conversation, action, action_details)

    # Send the reply via WhatsApp
    try:
        send_text_message(customer_phone, reply_text)
    except Exception:
        logger.exception("Failed to send WhatsApp reply to %s", customer_phone)

    return conversation


def _find_active_conversation(
    db: Session,
    merchant_id: UUID,
    customer_phone: str,
    daraz_order_id: Optional[str] = None,
) -> Optional[WhatsAppConversation]:
    """Find the most recent active conversation for a customer."""
    query = select(WhatsAppConversation).where(
        WhatsAppConversation.merchant_id == merchant_id,
        WhatsAppConversation.customer_phone == customer_phone,
        WhatsAppConversation.status == ConversationStatus.ACTIVE,
    )
    if daraz_order_id:
        query = query.where(WhatsAppConversation.daraz_order_id == daraz_order_id)

    query = query.order_by(WhatsAppConversation.last_message_at.desc())
    return db.exec(query).first()


def _handle_button_payload(payload: str) -> Optional[str]:
    """Parse button payload and return action string."""
    payload_upper = payload.upper()
    if "CONFIRM_ORDER" in payload_upper:
        return "confirm"
    if "CANCEL_ORDER" in payload_upper:
        return "cancel"
    if "MODIFY_ORDER" in payload_upper:
        return "modify"
    return None


def _apply_action(
    db: Session,
    conversation: WhatsAppConversation,
    action: str,
    details: Any = None,
) -> None:
    """Update conversation status based on agent action."""
    action_map = {
        "confirm": ConfirmationStatus.CONFIRMED,
        "cancel": ConfirmationStatus.CANCELLED,
        "modify": ConfirmationStatus.MODIFIED,
        "escalate": ConfirmationStatus.ESCALATED,
    }
    new_status = action_map.get(action)
    if new_status:
        conversation.confirmation_status = new_status
        if new_status in (ConfirmationStatus.CONFIRMED, ConfirmationStatus.CANCELLED):
            conversation.confirmed_at = datetime.now(timezone.utc)
            conversation.status = ConversationStatus.CLOSED
        elif new_status == ConfirmationStatus.ESCALATED:
            conversation.status = ConversationStatus.ESCALATED

    # Record the action as a system message
    system_msg = WhatsAppMessage(
        conversation_id=conversation.id,
        role=MessageRole.SYSTEM,
        content=f"Status changed to: {action}",
        metadata_json=json.dumps({"action": action, "details": details}),
    )
    db.add(system_msg)
    db.commit()


def generate_conversation_summary(
    db: Session,
    conversation_id: UUID,
    merchant_id: UUID,
) -> dict:
    """Generate an AI summary of a customer conversation for the merchant.

    Returns:
        {"summary": "...", "action_items": ["...", ...], "customer_sentiment": "positive|neutral|negative"}
    """
    conversation = db.get(WhatsAppConversation, conversation_id)
    if not conversation or conversation.merchant_id != merchant_id:
        return {"error": "Conversation not found"}

    # Build message history
    history = _build_conversation_messages(conversation, db)
    if not history:
        return {"summary": "No messages in this conversation yet.", "action_items": [], "customer_sentiment": "neutral"}

    # Format conversation for the summarizer
    conversation_text = "\n".join(
        f"{'Customer' if m['role'] == 'user' else 'Agent'}: {m['content']}"
        for m in history
    )

    summary_messages = [
        {
            "role": "system",
            "content": (
                "You are a merchant assistant. Summarize the following WhatsApp conversation "
                "between a customer and a support agent about a Daraz order.\n\n"
                "Provide:\n"
                "1. A brief summary (2-3 sentences)\n"
                "2. Any action items the merchant needs to handle\n"
                "3. Customer sentiment (positive, neutral, or negative)\n\n"
                "Respond as JSON: {\"summary\": \"...\", \"action_items\": [\"...\"], \"customer_sentiment\": \"...\"}"
            ),
        },
        {"role": "user", "content": conversation_text},
    ]

    try:
        response = _agent_client.chat.completions.create(
            model=_MODEL,
            messages=summary_messages,
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        logger.exception("Failed to generate conversation summary")
        return {
            "summary": "Unable to generate summary at this time.",
            "action_items": [],
            "customer_sentiment": "neutral",
        }
