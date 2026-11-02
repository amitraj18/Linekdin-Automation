"""Validation and normalization of connection records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from connections.connection_exceptions import ConnectionValidationError

logger = logging.getLogger("linkedin_automation.connections.normalizer")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class NormalizedConnection:
    """Normalized, validated internal representation of an imported connection."""

    external_contact_id: Optional[str]
    name: str
    profile_url: Optional[str]
    headline: Optional[str]
    eligibility_status: str
    collected_at: datetime
    needs_review: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert normalized connection to dictionary representation."""
        return {
            "external_contact_id": self.external_contact_id,
            "name": self.name,
            "profile_url": self.profile_url,
            "headline": self.headline,
            "eligibility_status": self.eligibility_status,
            "collected_at": self.collected_at.isoformat(),
            "needs_review": self.needs_review,
        }


def normalize_connection_record(raw: Any) -> NormalizedConnection:
    """Validate and normalize a raw connection dictionary.

    Raises:
        ConnectionValidationError: If input is not a dictionary or has an invalid/missing name.
    """
    if not isinstance(raw, dict):
        raise ConnectionValidationError(f"Expected dictionary record, got {type(raw).__name__}")

    raw_name = raw.get("name") or raw.get("Contact Name") or raw.get("full_name")
    if not raw_name or not isinstance(raw_name, str) or not raw_name.strip():
        raise ConnectionValidationError("Connection record missing required non-empty 'name'.")

    name = raw_name.strip()

    def _clean_str(key: str) -> Optional[str]:
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
        return None

    external_contact_id = (
        _clean_str("external_contact_id")
        or _clean_str("id")
        or _clean_str("Contact ID")
        or _clean_str("external_id")
    )

    profile_url = _clean_str("profile_url") or _clean_str("Profile URL") or _clean_str("url")
    headline = _clean_str("headline") or _clean_str("title")

    raw_status = _clean_str("eligibility_status") or _clean_str("Eligibility Status") or "eligible"
    eligibility_status = raw_status.lower()

    # If missing external identifier, flag for review so it's not confused with a stable contact
    needs_review = external_contact_id is None

    return NormalizedConnection(
        external_contact_id=external_contact_id,
        name=name,
        profile_url=profile_url,
        headline=headline,
        eligibility_status=eligibility_status,
        collected_at=_utc_now(),
        needs_review=needs_review,
    )

