"""Deterministic mock reply source for development and testing.

Generates fictional test replies matching Phase 3 criteria without network or browser access.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from collector.collector_exceptions import SourceError
from collector.reply_source import ReplySource

logger = logging.getLogger("linkedin_automation.collector.mock_source")


def get_default_fictional_replies() -> List[Dict[str, Any]]:
    """Return standard deterministic fictional test replies representing diverse scenarios."""
    return [
        {
            "external_reply_id": "mock_rep_001",
            "external_conversation_id": "conv_101",
            "external_contact_id": "li_c1",
            "contact_name": "Sarah Connor",
            "reply_text": "Hi! Yes, I am definitely interested in learning more about your automation workflow. When are you free?",
            "reply_timestamp": "2026-10-29T10:15:00Z",
        },
        {
            "external_reply_id": "mock_rep_002",
            "external_conversation_id": "conv_102",
            "external_contact_id": "li_c2",
            "contact_name": "John Matrix",
            "reply_text": "Could you please send over a brochure or case studies before we schedule a call?",
            "reply_timestamp": "2026-10-29T10:30:00Z",
        },
        {
            "external_reply_id": "mock_rep_003",
            "external_conversation_id": "conv_103",
            "external_contact_id": "li_c3",
            "contact_name": "Kyle Reese",
            "reply_text": "Thank you for reaching out, but we are not looking for new solutions at the moment.",
            "reply_timestamp": "2026-10-29T10:45:00Z",
        },
        {
            "external_reply_id": "mock_rep_004",
            "external_conversation_id": "conv_101",
            "external_contact_id": "li_c1",
            "contact_name": "Sarah Connor",
            "reply_text": "Also, does your platform integrate with custom SQLite pipelines?",
            "reply_timestamp": "2026-10-29T11:00:00Z",
        },
        {
            "external_reply_id": "mock_rep_005",
            "external_conversation_id": "conv_104",
            "external_contact_id": "li_unknown_999",
            "contact_name": "Unknown Stranger",
            "reply_text": "Hello, got your message. What is this regarding?",
            "reply_timestamp": "2026-10-29T11:15:00Z",
        },
    ]


class MockReplySource(ReplySource):
    """Deterministic mock source that returns predefined fictional reply batches."""

    def __init__(
        self,
        replies: Optional[List[Dict[str, Any]]] = None,
        simulate_failure: Optional[Exception] = None,
    ) -> None:
        """Initialize mock source.

        Args:
            replies: Explicit list of reply dictionaries. If None, uses default fictional replies.
            simulate_failure: Optional exception to raise during fetch_replies.
        """
        self._replies = replies if replies is not None else get_default_fictional_replies()
        self.simulate_failure = simulate_failure

    @property
    def source_name(self) -> str:
        return "mock"

    def fetch_replies(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch mock reply records deterministically."""
        if self.simulate_failure is not None:
            if isinstance(self.simulate_failure, SourceError):
                raise self.simulate_failure
            raise SourceError(f"Mock source failure simulated: {self.simulate_failure}") from self.simulate_failure

        results = list(self._replies)
        if limit is not None and limit > 0:
            results = results[:limit]

        logger.debug("MockReplySource returning %d record(s).", len(results))
        return results

