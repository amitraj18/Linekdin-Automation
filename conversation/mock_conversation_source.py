"""Deterministic mock conversation data source for development and testing.

Simulates diverse messaging thread scenarios without LinkedIn credentials or network access.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from conversation.conversation_exceptions import (
    ConversationAuthError,
    ConversationRateLimitError,
    ConversationSourceError,
    ConversationTimeoutError,
)
from conversation.conversation_source import ConversationSource

logger = logging.getLogger("linkedin_automation.conversation.mock_source")


def get_default_mock_conversations() -> List[Dict[str, Any]]:
    """Return standard deterministic fictional conversation threads covering all required scenarios."""
    return [
        {
            # Scenario 1: Initial outgoing message followed by an interested reply
            "conversation_id": "MOCK_CONV_001",
            "external_contact_id": "conn_ext_001",
            "contact_name": "Sarah Connor",
            "messages": [
                {
                    "external_message_id": "msg_001_1",
                    "conversation_id": "MOCK_CONV_001",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Hi Sarah, thank you for connecting! I noticed your work and would love to exchange insights on modern workflow automation whenever convenient for you.",
                    "message_timestamp": "2026-10-29T10:00:00Z",
                },
                {
                    "external_message_id": "msg_001_2",
                    "conversation_id": "MOCK_CONV_001",
                    "sender_identifier": "conn_ext_001",
                    "sender_name": "Sarah Connor",
                    "message_direction": "incoming",
                    "message_text": "Hi! Yes, I am definitely interested in learning more about your automation workflow. When are you free?",
                    "message_timestamp": "2026-10-29T10:15:00Z",
                },
            ],
        },
        {
            # Scenario 2: Initial outgoing message followed by request for more info
            "conversation_id": "MOCK_CONV_002",
            "external_contact_id": "conn_ext_002",
            "contact_name": "John Matrix",
            "messages": [
                {
                    "external_message_id": "msg_002_1",
                    "conversation_id": "MOCK_CONV_002",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Hi John, thanks for connecting!",
                    "message_timestamp": "2026-10-29T10:00:00Z",
                },
                {
                    "external_message_id": "msg_002_2",
                    "conversation_id": "MOCK_CONV_002",
                    "sender_identifier": "conn_ext_002",
                    "sender_name": "John Matrix",
                    "message_direction": "incoming",
                    "message_text": "Could you please send over a brochure or case studies before we schedule a call?",
                    "message_timestamp": "2026-10-29T10:30:00Z",
                },
            ],
        },
        {
            # Scenario 3: Initial outgoing message followed by rejection
            "conversation_id": "MOCK_CONV_003",
            "external_contact_id": "conn_ext_003",
            "contact_name": "Kyle Reese",
            "messages": [
                {
                    "external_message_id": "msg_003_1",
                    "conversation_id": "MOCK_CONV_003",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Hi Kyle, thanks for connecting!",
                    "message_timestamp": "2026-10-29T10:00:00Z",
                },
                {
                    "external_message_id": "msg_003_2",
                    "conversation_id": "MOCK_CONV_003",
                    "sender_identifier": "conn_ext_003",
                    "sender_name": "Kyle Reese",
                    "message_direction": "incoming",
                    "message_text": "Thank you for reaching out, but we are not looking for new solutions at the moment.",
                    "message_timestamp": "2026-10-29T10:45:00Z",
                },
            ],
        },
        {
            # Scenario 4: Initial outgoing message followed by opt-out
            "conversation_id": "MOCK_CONV_004",
            "external_contact_id": "conn_ext_004",
            "contact_name": "Ellen Ripley",
            "messages": [
                {
                    "external_message_id": "msg_004_1",
                    "conversation_id": "MOCK_CONV_004",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Hi Ellen, thanks for connecting!",
                    "message_timestamp": "2026-10-29T10:00:00Z",
                },
                {
                    "external_message_id": "msg_004_2",
                    "conversation_id": "MOCK_CONV_004",
                    "sender_identifier": "conn_ext_004",
                    "sender_name": "Ellen Ripley",
                    "message_direction": "incoming",
                    "message_text": "Please remove me from your list. Unsubscribe.",
                    "message_timestamp": "2026-10-29T11:00:00Z",
                },
            ],
        },
        {
            # Scenario 5 & 14: Multiple incoming and outgoing messages in non-chronological source order
            "conversation_id": "MOCK_CONV_005",
            "external_contact_id": "conn_ext_005",
            "contact_name": "Martin Riggs",
            "messages": [
                {
                    "external_message_id": "msg_005_3",
                    "conversation_id": "MOCK_CONV_005",
                    "sender_identifier": "conn_ext_005",
                    "sender_name": "Martin Riggs",
                    "message_direction": "incoming",
                    "message_text": "Sounds promising, let's schedule for Thursday 2 PM.",
                    "message_timestamp": "2026-10-29T12:00:00Z",
                },
                {
                    "external_message_id": "msg_005_1",
                    "conversation_id": "MOCK_CONV_005",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Hi Martin, great to connect!",
                    "message_timestamp": "2026-10-29T09:00:00Z",
                },
                {
                    "external_message_id": "msg_005_2",
                    "conversation_id": "MOCK_CONV_005",
                    "sender_identifier": "conn_ext_005",
                    "sender_name": "Martin Riggs",
                    "message_direction": "incoming",
                    "message_text": "Hey, what kind of automation tools do you support?",
                    "message_timestamp": "2026-10-29T10:30:00Z",
                },
                {
                    "external_message_id": "msg_005_4",
                    "conversation_id": "MOCK_CONV_005",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Perfect, I will send a calendar invite.",
                    "message_timestamp": "2026-10-29T12:15:00Z",
                },
            ],
        },
        {
            # Scenario 6: Conversation containing ONLY outgoing messages (no reply received)
            "conversation_id": "MOCK_CONV_006",
            "external_contact_id": "conn_ext_006",
            "contact_name": "Outgoing Only Contact",
            "messages": [
                {
                    "external_message_id": "msg_006_1",
                    "conversation_id": "MOCK_CONV_006",
                    "sender_identifier": "self_user",
                    "sender_name": "Antigravity User",
                    "message_direction": "outgoing",
                    "message_text": "Hi there, hoping to connect regarding our open role.",
                    "message_timestamp": "2026-10-29T08:00:00Z",
                }
            ],
        },
        {
            # Scenario 7: Conversation with multiple incoming replies
            "conversation_id": "MOCK_CONV_007",
            "external_contact_id": "conn_ext_007",
            "contact_name": "Multiple Replies Contact",
            "messages": [
                {
                    "external_message_id": "msg_007_1",
                    "conversation_id": "MOCK_CONV_007",
                    "sender_identifier": "conn_ext_007",
                    "sender_name": "Multiple Replies Contact",
                    "message_direction": "incoming",
                    "message_text": "Hello, saw your profile!",
                    "message_timestamp": "2026-10-29T14:00:00Z",
                },
                {
                    "external_message_id": "msg_007_2",
                    "conversation_id": "MOCK_CONV_007",
                    "sender_identifier": "conn_ext_007",
                    "sender_name": "Multiple Replies Contact",
                    "message_direction": "incoming",
                    "message_text": "Are you available for a brief sync tomorrow?",
                    "message_timestamp": "2026-10-29T14:05:00Z",
                },
            ],
        },
        {
            # Scenario 8: Conversation with ambiguous / unresolvable contact
            "conversation_id": "MOCK_CONV_008",
            "external_contact_id": None,
            "contact_name": "Ambiguous Person",
            "messages": [
                {
                    "external_message_id": "msg_008_1",
                    "conversation_id": "MOCK_CONV_008",
                    "sender_identifier": "ambig_008",
                    "sender_name": "Ambiguous Person",
                    "message_direction": "incoming",
                    "message_text": "Hi, this is a message from an unassociated participant.",
                    "message_timestamp": "2026-10-29T15:00:00Z",
                }
            ],
        },
        {
            # Scenario 9: Conversation with missing optional metadata (no sender_identifier/name)
            "conversation_id": "MOCK_CONV_009",
            "external_contact_id": "conn_ext_009",
            "contact_name": "Minimalist Contact",
            "messages": [
                {
                    "external_message_id": "msg_009_1",
                    "conversation_id": "MOCK_CONV_009",
                    "message_direction": "incoming",
                    "message_text": "Message without optional sender_identifier or sender_name.",
                    "message_timestamp": "2026-10-29T16:00:00Z",
                }
            ],
        },
    ]


class MockConversationSource(ConversationSource):
    """Deterministic mock conversation source."""

    def __init__(
        self,
        conversations: Optional[List[Dict[str, Any]]] = None,
        simulate_failure: Optional[Exception] = None,
        simulate_error: bool = False,
        simulate_timeout: bool = False,
        simulate_auth_error: bool = False,
        simulate_rate_limit: bool = False,
        empty_inbox: bool = False,
        empty_source: bool = False,
    ) -> None:
        """Initialize mock conversation source.

        Args:
            conversations: Custom list of conversation dicts. If None, default set is used.
            simulate_failure: Generic exception to raise when fetching.
            simulate_error: When True, raises ConversationSourceError.
            simulate_timeout: When True, raises ConversationTimeoutError.
            simulate_auth_error: When True, raises ConversationAuthError.
            simulate_rate_limit: When True, raises ConversationRateLimitError.
            empty_inbox: When True, returns empty results.
            empty_source: Alias for empty_inbox.
        """
        if empty_inbox or empty_source:
            self._conversations: List[Dict[str, Any]] = []
        elif conversations is not None:
            self._conversations = conversations
        else:
            self._conversations = get_default_mock_conversations()

        if simulate_error and simulate_failure is None:
            simulate_failure = ConversationSourceError("Simulated general source failure.")

        self.simulate_failure = simulate_failure
        self.simulate_timeout = simulate_timeout
        self.simulate_auth_error = simulate_auth_error
        self.simulate_rate_limit = simulate_rate_limit

    @property
    def source_name(self) -> str:
        return "mock"

    def _check_simulated_errors(self) -> None:
        if self.simulate_auth_error:
            raise ConversationAuthError("Simulated authentication failure: invalid or expired session.")
        if self.simulate_rate_limit:
            raise ConversationRateLimitError("Simulated rate limit exceeded: too many requests.")
        if self.simulate_timeout:
            raise ConversationTimeoutError("Simulated conversation source timeout.")
        if self.simulate_failure is not None:
            if isinstance(self.simulate_failure, ConversationSourceError):
                raise self.simulate_failure
            raise ConversationSourceError(f"Simulated source failure: {self.simulate_failure}") from self.simulate_failure

    def fetch_conversations(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch mock conversation summaries."""
        self._check_simulated_errors()

        results = []
        for conv in self._conversations:
            item = dict(conv)
            if "contact_name" in item and "participant_name" not in item:
                item["participant_name"] = item["contact_name"]
            results.append(item)
        if limit is not None and limit > 0:
            results = results[:limit]

        logger.debug("MockConversationSource returning %d conversation(s).", len(results))
        return results

    def fetch_messages(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch messages for a specific conversation."""
        self._check_simulated_errors()

        for conv in self._conversations:
            cid = str(conv.get("conversation_id") or conv.get("external_conversation_id") or "")
            if cid == conversation_id:
                msgs = list(conv.get("messages", []))
                if limit is not None and limit > 0:
                    msgs = msgs[:limit]
                return msgs

        return []

