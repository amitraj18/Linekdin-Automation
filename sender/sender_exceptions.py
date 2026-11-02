"""Exceptions for the sender package."""

from __future__ import annotations


class SenderError(Exception):
    """Base exception for all initial message sender errors."""


class SenderConfigurationError(SenderError):
    """Raised when sender configuration is invalid or missing."""


class ContactValidationError(SenderError):
    """Raised when a contact record fails validation requirements."""


class MessagingAdapterError(SenderError):
    """Raised when a messaging adapter encounters an unrecoverable failure."""


class PersistenceError(SenderError):
    """Raised when message or contact status persistence fails."""


class TemplateResolutionError(SenderError):
    """Raised when template loading or placeholder rendering fails."""

