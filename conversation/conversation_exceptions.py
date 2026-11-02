"""Exceptions hierarchy for conversation collection and messaging history."""

from __future__ import annotations


class ConversationError(Exception):
    """Base exception for all conversation collection operations."""


class ConversationSourceError(ConversationError):
    """Raised when an error occurs fetching conversations or messages from a source."""


class ConversationAuthError(ConversationSourceError):
    """Raised when source authentication or authorization fails."""


class ConversationRateLimitError(ConversationSourceError):
    """Raised when a source rate limit is exceeded."""


class ConversationTimeoutError(ConversationSourceError):
    """Raised when a request to a conversation source times out."""


class MessageValidationError(ConversationError):
    """Raised when incoming message record data is malformed or invalid."""


class ContactResolutionError(ConversationError):
    """Raised when an error occurs while resolving contacts for conversations."""


class ConversationPersistenceError(ConversationError):
    """Raised when persisting or updating conversation records in SQLite fails."""


class ConversationExcelError(ConversationError):
    """Raised when writing or rebuilding conversation records in Excel fails."""

