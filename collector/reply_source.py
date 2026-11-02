"""Abstract base interface for reply data sources.

Decouples data collection coordination from specific providers or messaging interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ReplySource(ABC):
    """Abstract interface defining the contract for reply sources."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the unique name or identifier for this source."""

    @abstractmethod
    def fetch_replies(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve a batch of reply records from the underlying source.

        Args:
            limit: Maximum number of records to retrieve.
            cursor: Optional pagination or continuation cursor.

        Returns:
            List of raw reply record dictionaries.

        Raises:
            SourceError: If the source encounters a network, API, or retrieval error.
        """

