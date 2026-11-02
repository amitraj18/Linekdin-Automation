"""Conversation package for Entry Point 2: Messaging Inbox and Conversation-History Collection.

Exports conversation source interfaces, normalization, resolution, persistence services,
and mock adapters.
"""

from conversation.conversation_exceptions import (
    ContactResolutionError,
    ConversationAuthError,
    ConversationError,
    ConversationExcelError,
    ConversationPersistenceError,
    ConversationRateLimitError,
    ConversationSourceError,
    ConversationTimeoutError,
    MessageValidationError,
)
from conversation.conversation_normalizer import (
    NormalizedMessage,
    normalize_message_direction,
    normalize_message_record,
)
from conversation.conversation_resolver import (
    ConversationResolver,
    ResolvedConversationContact,
)
from conversation.conversation_service import (
    ConversationRunSummary,
    ConversationService,
)
from conversation.conversation_source import ConversationSource
from conversation.mock_conversation_source import MockConversationSource

# Aliases for flexible naming
parse_flexible_timestamp = normalize_message_record
ConversationAuthenticationError = ConversationAuthError
ConversationConnectionError = ConversationSourceError
ConversationFormatError = MessageValidationError
ConversationValidationError = MessageValidationError
ConversationResolutionError = ContactResolutionError

__all__ = [
    "ConversationError",
    "ConversationSourceError",
    "ConversationAuthError",
    "ConversationAuthenticationError",
    "ConversationRateLimitError",
    "ConversationTimeoutError",
    "MessageValidationError",
    "ConversationValidationError",
    "ConversationFormatError",
    "ContactResolutionError",
    "ConversationResolutionError",
    "ConversationConnectionError",
    "ConversationPersistenceError",
    "ConversationExcelError",
    "ConversationSource",
    "NormalizedMessage",
    "normalize_message_record",
    "normalize_message_direction",
    "parse_flexible_timestamp",
    "ConversationResolver",
    "ResolvedConversationContact",
    "ConversationService",
    "ConversationRunSummary",
    "MockConversationSource",
]
