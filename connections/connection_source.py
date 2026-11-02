"""Abstract base interface for connection data sources.

Decouples contact collection logic from specific authentication or retrieval mechanisms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ConnectionSource(ABC):
    """Abstract interface defining the contract for connection retrieval sources."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier name of this connection source."""

    @abstractmethod
    def fetch_connections(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch a batch of connection records from the source.

        Args:
            limit: Maximum records to return in this batch.
            cursor: Optional continuation cursor for pagination.

        Returns:
            List of raw connection dictionaries.

        Raises:
            ConnectionSourceError: If an authentication, permission, rate limit, or retrieval error occurs.
        """

