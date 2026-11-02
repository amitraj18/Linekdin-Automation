"""Sender module package."""

from sender.messaging_adapter import MessagingAdapter, SendResult
from sender.mock_messaging_adapter import MockMessagingAdapter
from sender.sender_exceptions import (
    ContactValidationError,
    MessagingAdapterError,
    PersistenceError,
    SenderConfigurationError,
    SenderError,
    TemplateResolutionError,
)
from sender.sender_service import SenderRunSummary, SenderService

__all__ = [
    "MessagingAdapter",
    "SendResult",
    "MockMessagingAdapter",
    "SenderService",
    "SenderRunSummary",
    "SenderError",
    "SenderConfigurationError",
    "ContactValidationError",
    "MessagingAdapterError",
    "PersistenceError",
    "TemplateResolutionError",
]

