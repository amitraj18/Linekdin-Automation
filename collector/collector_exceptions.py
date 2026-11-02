"""Custom exception hierarchy for the reply collector and scraped data pipeline."""

from __future__ import annotations


class CollectorError(Exception):
    """Base exception for all reply collector operations."""


class SourceError(CollectorError):
    """Raised when an error occurs fetching data from a reply source."""


class RecordValidationError(CollectorError):
    """Raised when incoming reply record data is malformed or invalid."""


class ContactResolutionError(CollectorError):
    """Raised when a reply record cannot be associated with a contact."""


class DeduplicationError(CollectorError):
    """Raised when an error occurs during deduplication checks."""


class WorkbookExportError(CollectorError):
    """Raised when writing to or rebuilding the scraped replies workbook fails."""

