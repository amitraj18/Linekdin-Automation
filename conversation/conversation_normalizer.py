"""Validation and normalization for conversation messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from collector.reply_normalizer import parse_timestamp
from conversation.conversation_exceptions import MessageValidationError

logger = logging.getLogger("linkedin_automation.conversation.normalizer")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class NormalizedMessage:
    """Normalized, validated internal representation of a conversation message."""

    external_message_id: Optional[str]
    external_conversation_id: Optional[str]
    external_contact_id: Optional[str]
    contact_id: Optional[int]
    sender_identifier: Optional[str]
    sender_name: Optional[str]
    message_text: str
    message_timestamp: Optional[datetime]
    collected_at: datetime
    message_direction: str
    processing_status: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert normalized message to dictionary representation."""
        return {
            "external_message_id": self.external_message_id,
            "external_conversation_id": self.external_conversation_id,
            "external_contact_id": self.external_contact_id,
            "contact_id": self.contact_id,
            "sender_identifier": self.sender_identifier,
            "sender_name": self.sender_name,
            "message_text": self.message_text,
            "message_timestamp": self.message_timestamp,
            "collected_at": self.collected_at,
            "message_direction": self.message_direction,
            "processing_status": self.processing_status,
        }


def normalize_message_direction(raw: Any) -> str:
    """Determine message direction ('incoming', 'outgoing', or 'unknown') from source metadata.

    Does not classify direction based on message text.
    """
    if raw is None:
        return "unknown"

    if isinstance(raw, bool):
        return "outgoing" if raw else "incoming"

    val_str = str(raw).strip().lower()
    if val_str in ("incoming", "inbound", "received", "in"):
        return "incoming"
    if val_str in ("outgoing", "outbound", "sent", "out"):
        return "outgoing"
    if val_str in ("unknown", "other"):
        return "unknown"

    return "unknown"


def normalize_message_record(
    raw: Any,
    conversation_id: Optional[str] = None,
    contact_id: Optional[int] = None,
    external_contact_id: Optional[str] = None,
) -> NormalizedMessage:
    """Validate and normalize a raw message record dictionary.

    Args:
        raw: Raw message dictionary from source.
        conversation_id: Optional parent conversation ID fallback.
        contact_id: Optional resolved contact ID.
        external_contact_id: Optional resolved external contact ID.

    Returns:
        NormalizedMessage dataclass.

    Raises:
        MessageValidationError: If raw record is not a dict or lacks non-empty message_text.
    """
    if not isinstance(raw, dict):
        raise MessageValidationError(f"Expected dictionary record, got {type(raw).__name__}")

    raw_text = raw.get("message_text") or raw.get("text") or raw.get("body")
    if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
        raise MessageValidationError(
            f"Message record is missing required non-empty 'message_text': {raw.get('external_message_id', 'unknown_id')}"
        )

    # Clean outer whitespace, preserving all internal formatting
    message_text = raw_text.strip()

    def _clean_str(key: str) -> Optional[str]:
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
        return None

    external_message_id = (
        _clean_str("external_message_id")
        or _clean_str("message_id")
        or _clean_str("id")
        or _clean_str("Message ID")
    )

    external_conv_id = (
        _clean_str("external_conversation_id")
        or _clean_str("conversation_id")
        or _clean_str("Conversation ID")
        or conversation_id
    )

    ext_contact_id = (
        _clean_str("external_contact_id")
        or _clean_str("contact_id_str")
        or _clean_str("recipient_id")
        or external_contact_id
    )

    # Parsed integer contact_id if supplied
    parsed_contact_id: Optional[int] = contact_id
    if parsed_contact_id is None:
        raw_cid = raw.get("contact_id")
        if raw_cid is not None:
            try:
                parsed_contact_id = int(str(raw_cid).strip())
            except ValueError:
                parsed_contact_id = None

    sender_identifier = (
        _clean_str("sender_identifier")
        or _clean_str("sender_id")
        or _clean_str("from_id")
    )
    sender_name = (
        _clean_str("sender_name")
        or _clean_str("from_name")
        or _clean_str("author_name")
    )

    # Determine message direction
    raw_direction = (
        raw.get("message_direction")
        if "message_direction" in raw
        else raw.get("direction")
    )
    if raw_direction is None and "is_sender_me" in raw:
        raw_direction = raw.get("is_sender_me")
    elif raw_direction is None and "is_outgoing" in raw:
        raw_direction = raw.get("is_outgoing")
    elif raw_direction is None and "is_incoming" in raw:
        raw_direction = not bool(raw.get("is_incoming"))

    message_direction = normalize_message_direction(raw_direction)

    # Parse timestamps
    message_timestamp = parse_timestamp(
        raw.get("message_timestamp") or raw.get("timestamp") or raw.get("created_at")
    )
    collected_at = parse_timestamp(raw.get("collected_at")) or _utc_now()

    # Determine processing status
    raw_status = _clean_str("processing_status") or "new"
    if raw_status not in ("new", "processed", "needs_review", "ignored"):
        raw_status = "new"

    return NormalizedMessage(
        external_message_id=external_message_id,
        external_conversation_id=external_conv_id,
        external_contact_id=ext_contact_id,
        contact_id=parsed_contact_id,
        sender_identifier=sender_identifier,
        sender_name=sender_name,
        message_text=message_text,
        message_timestamp=message_timestamp,
        collected_at=collected_at,
        message_direction=message_direction,
        processing_status=raw_status,
    )

