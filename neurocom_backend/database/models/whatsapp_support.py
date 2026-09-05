from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional, List
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ────────────────────────────────────────────────────────────────────

class ConfirmationStatus(PyEnum):
    """Lifecycle of a single order-confirmation WhatsApp thread."""
    PENDING = "pending"              # message not yet sent
    SENT = "sent"                    # template message sent, awaiting reply
    CONFIRMED = "confirmed"          # customer replied "confirm"
    CANCELLED = "cancelled"          # customer replied "cancel"
    MODIFIED = "modified"            # customer wants changes (color, size…)
    NO_RESPONSE = "no_response"      # reminder sent, still no reply
    ESCALATED = "escalated"          # handed to merchant / human agent


class MessageRole(PyEnum):
    ASSISTANT = "assistant"          # outbound from our agent
    USER = "user"                    # inbound from customer
    SYSTEM = "system"                # internal note / status change


class ConversationStatus(PyEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    ESCALATED = "escalated"


# ── DB Models ────────────────────────────────────────────────────────────────

class MerchantSupportConfig(SQLModel, table=True):
    """Per-merchant WhatsApp support configuration and instructions."""
    __tablename__ = "merchant_support_config"

    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    merchant_id: UUID = Field(foreign_key="merchant.id", nullable=False, unique=True, index=True)

    # WhatsApp Business profile
    whatsapp_phone_number: Optional[str] = Field(default=None, max_length=20)
    is_whatsapp_enabled: bool = Field(default=False)

    # Auto-confirmation settings
    auto_confirm_orders: bool = Field(default=True)
    confirmation_timeout_hours: int = Field(default=24)

    # Merchant-defined instructions for the AI agent
    # e.g. "We only have black and white in stock", "Exchanges within 7 days"
    custom_instructions: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Greeting message template (used when customer first messages)
    greeting_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WhatsAppConversation(SQLModel, table=True):
    """One conversation thread per (merchant, customer_phone, daraz_order_id)."""
    __tablename__ = "whatsapp_conversation"

    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    merchant_id: UUID = Field(foreign_key="merchant.id", nullable=False, index=True)
    daraz_order_id: Optional[str] = Field(default=None, max_length=50, index=True)

    # Customer identifier (phone number in E.164 format: 923xxxxxxxxx)
    customer_phone: str = Field(max_length=20, index=True)
    customer_name: Optional[str] = Field(default=None, max_length=100)

    status: ConversationStatus = Field(default=ConversationStatus.ACTIVE, index=True)
    confirmation_status: ConfirmationStatus = Field(
        default=ConfirmationStatus.PENDING, index=True
    )

    # Timestamps
    started_at: datetime = Field(default_factory=utc_now)
    last_message_at: datetime = Field(default_factory=utc_now)
    confirmed_at: Optional[datetime] = Field(default=None)

    # WhatsApp conversation tracking
    whatsapp_conversation_id: Optional[str] = Field(default=None, max_length=100)

    # Relationships
    messages: List["WhatsAppMessage"] = Relationship(back_populates="conversation")


class WhatsAppMessage(SQLModel, table=True):
    """Individual message within a WhatsApp conversation."""
    __tablename__ = "whatsapp_message"

    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    conversation_id: UUID = Field(foreign_key="whatsapp_conversation.id", nullable=False, index=True)

    role: MessageRole = Field(nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))

    # WhatsApp message ID for tracking delivered/read status
    whatsapp_message_id: Optional[str] = Field(default=None, max_length=100)

    # Metadata: template name, button payload, etc.
    metadata_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(default_factory=utc_now)

    # Relationship
    conversation: Optional[WhatsAppConversation] = Relationship(back_populates="messages")


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class MerchantSupportConfigUpdate(BaseModel):
    auto_confirm_orders: Optional[bool] = None
    confirmation_timeout_hours: Optional[int] = None
    custom_instructions: Optional[str] = None
    greeting_message: Optional[str] = None
    whatsapp_phone_number: Optional[str] = None
    is_whatsapp_enabled: Optional[bool] = None


class MerchantSupportConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    merchant_id: UUID
    whatsapp_phone_number: Optional[str] = None
    is_whatsapp_enabled: bool = False
    auto_confirm_orders: bool = True
    confirmation_timeout_hours: int = 24
    custom_instructions: Optional[str] = None
    greeting_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WhatsAppMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: MessageRole
    content: str
    whatsapp_message_id: Optional[str] = None
    created_at: datetime


class WhatsAppConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    merchant_id: UUID
    daraz_order_id: Optional[str] = None
    customer_phone: str
    customer_name: Optional[str] = None
    status: ConversationStatus
    confirmation_status: ConfirmationStatus
    started_at: datetime
    last_message_at: datetime
    confirmed_at: Optional[datetime] = None
    messages: List[WhatsAppMessageRead] = []


class TriggerConfirmationRequest(BaseModel):
    """Merchant triggers order confirmation for a specific Daraz order."""
    daraz_order_id: str
    customer_phone: str
    customer_name: Optional[str] = None
    order_details: Optional[dict] = None


class GenerateSummaryRequest(BaseModel):
    """Merchant requests a summary of a conversation."""
    conversation_id: UUID
