"""Data normalization and validation for collected replies.

Validates incoming reply record structures, standardizes timestamps,
preserves original reply text, and constructs clean normalized representations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from collector.collector_exceptions import RecordValidationError

logger = logging.getLogger("linkedin_automation.collector.normalizer")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def parse_timestamp(raw_val: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a timezone-aware UTC datetime."""
    if raw_val is None:
        return None

    if isinstance(raw_val, datetime):
        if raw_val.tzinfo is None:
            return raw_val.replace(tzinfo=timezone.utc)
        return raw_val.astimezone(timezone.utc)

    if isinstance(raw_val, (int, float)):
        try:
            return datetime.fromtimestamp(raw_val, tz=timezone.utc)
        except (OverflowError, ValueError) as exc:
            logger.warning("Could not parse epoch timestamp '%s': %s", raw_val, exc)
            return None

    if isinstance(raw_val, str):
        val_str = raw_val.strip()
        if not val_str:
            return None

        # Try ISO 8601 parsing (handles Z, +00:00, etc.)
        try:
            # Replace trailing Z with +00:00 for fromisoformat compatibility
            iso_candidate = val_str[:-1] + "+00:00" if val_str.endswith("Z") else val_str
            dt = datetime.fromisoformat(iso_candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

        # Try standard SQL datetime format YYYY-MM-DD HH:MM:SS
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(val_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        logger.warning("Unrecognized date format string: '%s'", val_str)
        return None

    return None


@dataclass(frozen=True)
class NormalizedReply:
    """Normalized, validated internal representation of a collected reply."""

    external_reply_id: Optional[str]
    external_conversation_id: Optional[str]
    external_contact_id: Optional[str]
    contact_id: Optional[int]
    contact_name: Optional[str]
    reply_text: str
    reply_timestamp: Optional[datetime]
    collected_at: datetime
    processing_status: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "external_reply_id": self.external_reply_id,
            "external_conversation_id": self.external_conversation_id,
            "external_contact_id": self.external_contact_id,
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "reply_text": self.reply_text,
            "reply_timestamp": self.reply_timestamp,
            "collected_at": self.collected_at,
            "processing_status": self.processing_status,
        }


def normalize_reply_record(raw: Any) -> NormalizedReply:
    """Validate and normalize a raw reply record dictionary into a NormalizedReply.

    Raises:
        RecordValidationError: If the record is not a dictionary or has empty reply_text.
    """
    if not isinstance(raw, dict):
        raise RecordValidationError(f"Expected dictionary record, got {type(raw).__name__}")

    # Validate reply text
    raw_text = raw.get("reply_text")
    if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
        raise RecordValidationError(
            f"Record is missing required non-empty 'reply_text': {raw.get('external_reply_id', 'unknown_id')}"
        )

    # Clean surrounding whitespace without mutating inner text
    reply_text = raw_text.strip()

    # Extract & clean identifiers
    def _clean_str(key: str) -> Optional[str]:
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
        return None

    external_reply_id = _clean_str("external_reply_id") or _clean_str("reply_id") or _clean_str("Reply ID")
    external_conversation_id = (
        _clean_str("external_conversation_id")
        or _clean_str("conversation_id")
        or _clean_str("Conversation ID")
    )
    external_contact_id = (
        _clean_str("external_contact_id")
        or _clean_str("sender_id")
        or _clean_str("External Contact ID")
    )

    # Parse contact_id if supplied as integer or digit string
    contact_id: Optional[int] = None
    raw_cid = raw.get("contact_id") or raw.get("Contact ID")
    if raw_cid is not None:
        try:
            contact_id = int(str(raw_cid).strip())
        except ValueError:
            contact_id = None

    contact_name = _clean_str("contact_name") or _clean_str("sender_name") or _clean_str("Contact Name")

    # Parse timestamps
    reply_timestamp = parse_timestamp(raw.get("reply_timestamp") or raw.get("Reply Timestamp"))
    collected_at = parse_timestamp(raw.get("collected_at")) or _utc_now()

    # Determine initial processing status
    raw_status = _clean_str("processing_status") or "new"
    if raw_status not in ("new", "processed", "needs_review"):
        raw_status = "new"

    return NormalizedReply(
        external_reply_id=external_reply_id,
        external_conversation_id=external_conversation_id,
        external_contact_id=external_contact_id,
        contact_id=contact_id,
        contact_name=contact_name,
        reply_text=reply_text,
        reply_timestamp=reply_timestamp,
        collected_at=collected_at,
        processing_status=raw_status,
    )

