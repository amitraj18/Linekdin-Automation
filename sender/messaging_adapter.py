"""Standard interface and result contract for messaging adapters.

Decouples sender business logic from specific messaging transport mechanisms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, Set

SendOutcome = Literal["sent", "failed", "unknown"]
VALID_OUTCOMES: Set[str] = {"sent", "failed", "unknown"}


@dataclass(frozen=True)
class SendResult:
    """Standardized result returned by any messaging adapter send attempt."""

    outcome: str
    external_message_id: Optional[str] = None
    timestamp: Optional[datetime] = field(default=None)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"Invalid SendResult outcome '{self.outcome}'. Must be one of: {sorted(VALID_OUTCOMES)}"
            )


class MessagingAdapter(ABC):
    """Abstract base class defining the messaging adapter interface."""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Unique identifier name of this messaging adapter."""

    @abstractmethod
    def send(
        self,
        recipient_info: Dict[str, Any],
        message_text: str,
    ) -> SendResult:
        """Attempt to deliver a rendered message to a recipient.

        Args:
            recipient_info: Dictionary containing recipient attributes (id, name, external_id, etc.).
            message_text: The fully rendered, personalized message text.

        Returns:
            SendResult indicating 'sent', 'failed', or 'unknown' outcome.
        """

