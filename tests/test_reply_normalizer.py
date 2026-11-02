"""Unit tests for reply record normalization and timestamp parsing."""

from datetime import datetime, timezone
import pytest

from collector.collector_exceptions import RecordValidationError
from collector.reply_normalizer import normalize_reply_record, parse_timestamp


def test_parse_timestamp_variations():
    """parse_timestamp parses ISO strings, standard SQL datetimes, and epoch timestamps."""
    # ISO string with Z
    dt1 = parse_timestamp("2026-10-29T10:15:00Z")
    assert dt1 is not None
    assert dt1.tzinfo == timezone.utc
    assert dt1.hour == 10 and dt1.minute == 15

    # SQL format
    dt2 = parse_timestamp("2026-10-29 14:30:00")
    assert dt2 is not None
    assert dt2.year == 2026 and dt2.hour == 14

    # Epoch timestamp
    dt3 = parse_timestamp(1700000000)
    assert dt3 is not None
    assert dt3.tzinfo == timezone.utc

    # Invalid / empty
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not_a_date") is None


def test_normalize_valid_record():
    """normalize_reply_record normalizes full valid dictionary correctly."""
    raw = {
        "external_reply_id": "rep_100",
        "external_conversation_id": "conv_200",
        "external_contact_id": "c_300",
        "contact_name": "Sarah Connor",
        "reply_text": "  Yes, let's talk! We should meet.  ",
        "reply_timestamp": "2026-10-29T12:00:00Z",
        "processing_status": "new",
    }
    norm = normalize_reply_record(raw)

    assert norm.external_reply_id == "rep_100"
    assert norm.external_conversation_id == "conv_200"
    assert norm.external_contact_id == "c_300"
    assert norm.contact_name == "Sarah Connor"
    # Strips outer whitespace, preserves inner whitespace
    assert norm.reply_text == "Yes, let's talk! We should meet."
    assert norm.reply_timestamp is not None
    assert norm.processing_status == "new"


def test_normalize_missing_optional_metadata():
    """Records with only reply_text succeed with None for optional fields."""
    raw = {"reply_text": "A brief message without metadata."}
    norm = normalize_reply_record(raw)

    assert norm.reply_text == "A brief message without metadata."
    assert norm.external_reply_id is None
    assert norm.external_conversation_id is None
    assert norm.external_contact_id is None
    assert norm.contact_id is None
    assert norm.processing_status == "new"


def test_normalize_empty_text_raises_validation_error():
    """Records missing reply_text or with only whitespace raise RecordValidationError."""
    with pytest.raises(RecordValidationError, match="missing required non-empty 'reply_text'"):
        normalize_reply_record({"reply_text": ""})

    with pytest.raises(RecordValidationError, match="missing required non-empty 'reply_text'"):
        normalize_reply_record({"reply_text": "   \n\t  "})

    with pytest.raises(RecordValidationError, match="missing required non-empty 'reply_text'"):
        normalize_reply_record({"other_field": "no text here"})


def test_normalize_non_dict_raises_error():
    """Passing a non-dictionary raises RecordValidationError."""
    with pytest.raises(RecordValidationError, match="Expected dictionary record"):
        normalize_reply_record("string instead of dict")

