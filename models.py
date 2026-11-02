"""SQLAlchemy 2.x declarative models for LinkedIn messaging automation.

Defines Contact, Message, Reply, and AutomationCycle entities with primary keys,
foreign keys, constraints, indexes, and relationships.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarative class for all ORM models."""


class Contact(Base):
    """Represents a connection/contact in the outreach and reply workflow."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_contact_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    eligibility_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="eligible", server_default="eligible"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )

    # Relationships
    messages: Mapped[List[Message]] = relationship(
        "Message",
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    replies: Mapped[List[Reply]] = relationship(
        "Reply",
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Reply.collected_at",
    )
    conversation_messages: Mapped[List[ConversationMessage]] = relationship(
        "ConversationMessage",
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.message_timestamp",
    )

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, name='{self.name}', status='{self.eligibility_status}')>"


class Message(Base):
    """Represents an intended or sent message (initial, reply, or follow-up)."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "message_type IN ('initial', 'reply', 'follow_up')",
            name="check_message_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped', 'unknown')",
            name="check_message_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    template_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Idempotency key is unique for an intended send to prevent duplicate sends
    idempotency_key: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )

    # Relationship
    contact: Mapped[Contact] = relationship("Contact", back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<Message(id={self.id}, contact_id={self.contact_id}, "
            f"type='{self.message_type}', status='{self.status}')>"
        )


class Reply(Base):
    """Represents a reply collected from a contact."""

    __tablename__ = "replies"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('new', 'processed', 'needs_review')",
            name="check_reply_processing_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_reply_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    conversation_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    reply_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    processing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="new",
        server_default="new",
    )
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    selected_template_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    # Relationship
    contact: Mapped[Contact] = relationship("Contact", back_populates="replies")

    def __repr__(self) -> str:
        return (
            f"<Reply(id={self.id}, contact_id={self.contact_id}, "
            f"status='{self.processing_status}', category='{self.category}')>"
        )


class ConversationMessage(Base):
    """Represents a message in a conversation thread (incoming or outgoing)."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "message_direction IN ('incoming', 'outgoing', 'unknown')",
            name="check_conv_message_direction",
        ),
        CheckConstraint(
            "processing_status IN ('new', 'processed', 'needs_review', 'ignored')",
            name="check_conv_message_processing_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    external_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(255), index=True, nullable=True
    )
    external_contact_id: Mapped[Optional[str]] = mapped_column(
        String(255), index=True, nullable=True
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sender_identifier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    message_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    message_direction: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="new", server_default="new"
    )

    # Relationship
    contact: Mapped[Optional[Contact]] = relationship(
        "Contact", back_populates="conversation_messages"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage(id={self.id}, contact_id={self.contact_id}, "
            f"conv_id='{self.external_conversation_id}', direction='{self.message_direction}', "
            f"status='{self.processing_status}')>"
        )


class AutomationCycle(Base):
    """Represents a cycle of the automation workflow and summary metrics."""

    __tablename__ = "automation_cycles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'partially_completed')",
            name="check_cycle_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="running",
        server_default="running",
    )
    initial_messages_processed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    replies_collected: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    responses_queued: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    followups_queued: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AutomationCycle(id={self.id}, status='{self.status}', started_at={self.started_at})>"

