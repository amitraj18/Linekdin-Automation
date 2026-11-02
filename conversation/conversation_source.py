"""Abstract base interface for conversation history data sources.

Decouples conversation message collection from specific messaging providers or APIs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ConversationSource(ABC):
    """Abstract interface defining the contract for conversation history sources."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the unique identifier or provider name for this source."""

    @abstractmethod
    def fetch_conversations(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch accessible conversation threads from the source.

        Args:
            limit: Maximum conversations to retrieve.
            cursor: Optional continuation cursor for pagination.

        Returns:
            List of conversation dictionary records.

        Raises:
            ConversationSourceError: If an authentication, rate limit, timeout, or retrieval error occurs.
        """

    @abstractmethod
    def fetch_messages(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch messages belonging to a specific conversation thread.

        Args:
            conversation_id: Unique conversation identifier.
            limit: Maximum messages to retrieve.
            cursor: Optional continuation cursor.

        Returns:
            List of raw message records for the thread.

        Raises:
            ConversationSourceError: If retrieval fails.
        """

    def fetch_all_conversations(
        self,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Convenience method returning conversations with their associated messages."""
        conversations = self.fetch_conversations(limit=limit)
        results = []
        for conv in conversations:
            conv_id = str(conv.get("conversation_id") or conv.get("external_conversation_id") or "")
            conv_record = dict(conv)
            if "messages" not in conv_record and conv_id:
                conv_record["messages"] = self.fetch_messages(conv_id)
            results.append(conv_record)
        return results

