"""Connections collection package."""

from connections.connection_exceptions import (
    ConnectionCollectorError,
    ConnectionPersistenceError,
    ConnectionSourceError,
    ConnectionValidationError,
)
from connections.connection_normalizer import (
    NormalizedConnection,
    normalize_connection_record,
)
from connections.connection_service import ConnectionRunSummary, ConnectionService
from connections.connection_source import ConnectionSource
from connections.mock_connection_source import (
    MockConnectionSource,
    get_default_fictional_connections,
)

__all__ = [
    "ConnectionCollectorError",
    "ConnectionSourceError",
    "ConnectionValidationError",
    "ConnectionPersistenceError",
    "ConnectionSource",
    "MockConnectionSource",
    "get_default_fictional_connections",
    "NormalizedConnection",
    "normalize_connection_record",
    "ConnectionRunSummary",
    "ConnectionService",
]

