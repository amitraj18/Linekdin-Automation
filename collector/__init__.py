"""Reply collector package."""

from collector.collector_exceptions import (
    CollectorError,
    ContactResolutionError,
    DeduplicationError,
    RecordValidationError,
    SourceError,
    WorkbookExportError,
)
from collector.collector_service import CollectionRunSummary, CollectorService
from collector.mock_reply_source import MockReplySource, get_default_fictional_replies
from collector.reply_normalizer import NormalizedReply, normalize_reply_record
from collector.reply_source import ReplySource

__all__ = [
    "CollectorError",
    "SourceError",
    "RecordValidationError",
    "ContactResolutionError",
    "DeduplicationError",
    "WorkbookExportError",
    "CollectionRunSummary",
    "CollectorService",
    "ReplySource",
    "MockReplySource",
    "get_default_fictional_replies",
    "NormalizedReply",
    "normalize_reply_record",
]

