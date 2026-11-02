"""Deterministic mock messaging adapter for testing and safe dry-run emulation.

Simulates confirmed success, explicit failure, and uncertain outcomes without
network, browser, or third-party platform interaction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sender.messaging_adapter import MessagingAdapter, SendResult

logger = logging.getLogger("linkedin_automation.sender.mock_adapter")


class MockMessagingAdapter(MessagingAdapter):
    """Deterministic mock adapter used as default and for test suites."""

    def __init__(
        self,
        default_outcome: str = "sent",
        recipient_outcomes: Optional[Dict[str, SendResult]] = None,
        simulate_exception: Optional[Exception] = None,
    ) -> None:
        """Initialize mock adapter.

        Args:
            default_outcome: Default outcome ("sent", "failed", or "unknown") for unmapped recipients.
            recipient_outcomes: Map of contact ID (str) or name to predefined SendResult.
            simulate_exception: Optional exception to raise when send is invoked.
        """
        self.default_outcome = default_outcome
        self.recipient_outcomes = recipient_outcomes or {}
        self.simulate_exception = simulate_exception
        self.sent_messages: List[Dict[str, Any]] = []

    @property
    def adapter_name(self) -> str:
        return "mock"

    def send(
        self,
        recipient_info: Dict[str, Any],
        message_text: str,
    ) -> SendResult:
        """Process mock message send."""
        if self.simulate_exception is not None:
            raise self.simulate_exception

        contact_id_str = str(recipient_info.get("id") or recipient_info.get("contact_id") or "")
        external_id = str(recipient_info.get("external_contact_id") or "")
        name = str(recipient_info.get("name") or "")

        now = datetime.now(timezone.utc)

        # Check for predefined recipient override
        if contact_id_str in self.recipient_outcomes:
            result = self.recipient_outcomes[contact_id_str]
        elif external_id in self.recipient_outcomes:
            result = self.recipient_outcomes[external_id]
        elif name in self.recipient_outcomes:
            result = self.recipient_outcomes[name]
        else:
            # Generate outcome based on default_outcome
            if self.default_outcome == "sent":
                result = SendResult(
                    outcome="sent",
                    external_message_id=f"mock_msg_{contact_id_str}_{int(now.timestamp())}",
                    timestamp=now,
                )
            elif self.default_outcome == "failed":
                result = SendResult(
                    outcome="failed",
                    error_code="MOCK_SEND_FAILED",
                    error_message=f"Simulated mock failure for recipient {name} ({contact_id_str})",
                )
            elif self.default_outcome == "unknown":
                result = SendResult(
                    outcome="unknown",
                    error_code="MOCK_SEND_TIMEOUT_UNCERTAIN",
                    error_message=f"Simulated network timeout/uncertain outcome for recipient {name}",
                )
            else:
                result = SendResult(outcome=self.default_outcome)

        # Record call details for test inspection
        self.sent_messages.append(
            {
                "recipient_info": dict(recipient_info),
                "message_text": message_text,
                "result": result,
                "recorded_at": now,
            }
        )

        logger.debug(
            "MockMessagingAdapter processed send for contact '%s' (ID: %s) -> outcome: %s",
            name,
            contact_id_str,
            result.outcome,
        )
        return result

