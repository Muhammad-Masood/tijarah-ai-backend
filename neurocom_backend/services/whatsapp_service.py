"""WhatsApp Business Cloud API service.

Handles all communication with Meta's WhatsApp Cloud API:
- Sending template messages (order confirmations)
- Sending/receiving text messages
- Interactive button messages
- Webhook verification and event processing
"""

import json
import logging
from typing import Any, Optional

import requests
from dotenv import load_dotenv
import os

from neurocom_backend.utils.settings import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PN_ID,
    WHATSAPP_API_VERSION,
    WHATSAPP_VERIFY_TOKEN,
)

_: bool = load_dotenv()
logger = logging.getLogger(__name__)

# WhatsApp Cloud API base URL
_BASE_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


# ── Low-level HTTP helpers ───────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _send_url() -> str:
    return f"{_BASE_URL}/{WHATSAPP_PN_ID}/messages"


def _post(payload: dict) -> dict:
    """POST to the messages endpoint and return the parsed JSON body."""
    url = _send_url()
    logger.debug("WhatsApp POST %s payload=%s", url, json.dumps(payload, default=str))
    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Webhook verification ─────────────────────────────────────────────────────

def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    """Verify the WhatsApp webhook subscription challenge.

    Meta sends a GET request with hub.mode, hub.verify_token, hub.challenge.
    We must echo back the challenge if the token matches.
    """
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        return challenge
    logger.warning("WhatsApp webhook verification failed: mode=%s token=%s", mode, token)
    return None


# ── Sending messages ─────────────────────────────────────────────────────────

def send_text_message(to: str, text: str) -> dict:
    """Send a plain text message to a phone number.

    Args:
        to: Recipient phone number in E.164 format (e.g. "923001234567")
        text: Message body text

    Returns:
        API response with message_id
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": "false", "body": text},
    }
    result = _post(payload)
    logger.info("Sent text message to %s: msg_id=%s", to, result.get("messages", [{}])[0].get("id"))
    return result


def send_template_message(
    to: str,
    template_name: str,
    language_code: str = "en",
    components: Optional[list[dict]] = None,
) -> dict:
    """Send a template message (used for order confirmation initiation).

    Template messages can be sent outside the 24-hour session window.
    They must be pre-approved by Meta.

    Args:
        to: Recipient phone number in E.164 format
        template_name: Pre-approved template name
        language_code: Language code (e.g. "en", "en_US", "ur")
        components: Template components (header, body, buttons) with parameters

    Returns:
        API response
    """
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    result = _post(payload)
    logger.info("Sent template '%s' to %s: msg_id=%s", template_name, to,
                result.get("messages", [{}])[0].get("id"))
    return result


def send_order_confirmation_template(
    to: str,
    customer_name: str,
    order_id: str,
    total_amount: str,
    merchant_name: str,
) -> dict:
    """Send the order confirmation template with interactive buttons.

    Uses a pre-approved template with:
    - Body parameters: customer_name, order_id, total_amount, merchant_name
    - Quick reply buttons: "Confirm Order" / "Cancel Order"

    NOTE: You must create this template in your WhatsApp Business Manager first.
    Template name: "order_confirmation"
    """
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": customer_name},
                {"type": "text", "text": order_id},
                {"type": "text", "text": total_amount},
                {"type": "text", "text": merchant_name},
            ],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": 0,
            "parameters": [{"type": "payload", "payload": f"CONFIRM_ORDER_{order_id}"}],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": 1,
            "parameters": [{"type": "payload", "payload": f"CANCEL_ORDER_{order_id}"}],
        },
    ]

    return send_template_message(to, "order_confirmation", "en", components)


def send_interactive_buttons(
    to: str,
    body_text: str,
    buttons: list[dict[str, str]],
    header_text: Optional[str] = None,
) -> dict:
    """Send an interactive message with up to 3 quick-reply buttons.

    Args:
        to: Recipient phone number
        body_text: Message body
        buttons: List of {"id": "unique_id", "title": "Button Text"} (max 3)
        header_text: Optional header text
    """
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }
    if header_text:
        payload["interactive"]["header"] = {"type": "text", "text": header_text}

    result = _post(payload)
    logger.info("Sent interactive buttons to %s", to)
    return result


# ── Webhook event parsing ────────────────────────────────────────────────────

def parse_webhook_event(payload: dict) -> list[dict]:
    """Parse incoming WhatsApp webhook payload and extract messages.

    Returns a list of extracted message dicts with keys:
    - from_: sender phone number
    - message_id: WhatsApp message ID
    - timestamp: message timestamp
    - type: "text", "button", "interactive", etc.
    - text: message text (for text type)
    - button_payload: payload string (for button replies)
    """
    extracted = []

    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                # Handle message status updates (delivered, read)
                for status in value.get("statuses", []):
                    extracted.append({
                        "type": "status",
                        "message_id": status.get("id"),
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "from_": status.get("recipient_id"),
                    })
                # Handle incoming messages
                for msg in value.get("messages", []):
                    parsed = _parse_message(msg)
                    if parsed:
                        extracted.append(parsed)
    except Exception:
        logger.exception("Failed to parse WhatsApp webhook payload")

    return extracted


def _parse_message(msg: dict) -> Optional[dict]:
    """Parse a single message object from the webhook."""
    msg_type = msg.get("type", "")
    from_ = msg.get("from", "")
    message_id = msg.get("id", "")
    timestamp = msg.get("timestamp", "")

    base = {
        "from_": from_,
        "message_id": message_id,
        "timestamp": timestamp,
        "type": msg_type,
    }

    if msg_type == "text":
        base["text"] = msg.get("text", {}).get("body", "")
        return base

    if msg_type == "button":
        # Quick reply button tap
        button = msg.get("button", {})
        base["text"] = button.get("text", "")
        base["button_payload"] = button.get("payload", "")
        return base

    if msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type", "")
        if interactive_type == "button_reply":
            reply = interactive.get("button_reply", {})
            base["text"] = reply.get("title", "")
            base["button_payload"] = reply.get("id", "")
            return base
        if interactive_type == "list_reply":
            reply = interactive.get("list_reply", {})
            base["text"] = reply.get("title", "")
            base["button_payload"] = reply.get("id", "")
            return base

    # Unsupported message types (image, audio, video, location, etc.)
    base["text"] = f"[{msg_type} message]"
    return base


# ── Contact name lookup ──────────────────────────────────────────────────────

def get_contact_name(phone_number: str) -> Optional[str]:
    """Attempt to retrieve the contact's WhatsApp profile name."""
    try:
        url = f"{_BASE_URL}/{WHATSAPP_PN_ID}"
        resp = requests.get(url, headers=_headers(), params={
            "fields": "verified_name",
        }, timeout=10)
        resp.raise_for_status()
        return resp.json().get("verified_name")
    except Exception:
        logger.debug("Could not fetch contact name for %s", phone_number)
        return None
