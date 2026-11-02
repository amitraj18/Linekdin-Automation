"""Exceptions for the connections package."""

from __future__ import annotations


class ConnectionCollectorError(Exception):
    """Base exception for all connection collection operations."""


class ConnectionSourceError(ConnectionCollectorError):
    """Raised when an error occurs fetching data from a connection source."""


class ConnectionValidationError(ConnectionCollectorError):
    """Raised when a connection record structure is malformed or invalid."""


class ConnectionPersistenceError(ConnectionCollectorError):
    """Raised when persisting or updating contacts in the database fails."""

