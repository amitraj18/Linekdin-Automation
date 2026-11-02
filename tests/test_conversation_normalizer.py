"""Tests for conversation message validation and normalization."""

from datetime import datetime, timezone
import pytest

from conversation.conversation_exceptions import MessageValidationError
from conversation.conversation_normalizer import (
    NormalizedMessage,
    normalize_message_direction,
    normalize_message_record,
)


def test_normalize_message_record_valid():
    """Verify normalizing a complete message record."""
    raw = {
        "external_message_id": "m_100",
        "external_conversation_id": "conv_100",
        "external_contact_id": "usr_100",
        "contact_id": 42,
        "sender_identifier": "usr_100",
        "sender_name": "Jane Doe",
        "message_text": "  Hello there! Would love to chat.  ",
        "message_timestamp": "2026-10-30T10:00:00Z",
        "collected_at": "2026-10-30T10:05:00Z",
        "message_direction": "incoming",
        "processing_status": "new",
    }
    normalized = normalize_message_record(raw)
    assert isinstance(normalized, NormalizedMessage)
    assert normalized.external_message_id == "m_100"
    assert normalized.external_conversation_id == "conv_100"
    assert normalized.external_contact_id == "usr_100"
    assert normalized.contact_id == 42
    assert normalized.sender_name == "Jane Doe"
    assert normalized.message_text == "Hello there! Would love to chat."
    assert normalized.message_direction == "incoming"
    assert normalized.processing_status == "new"
    assert normalized.message_timestamp == datetime(2026, 10, 30, 10, 0, 0, tzinfo=timezone.utc)


def test_normalize_message_record_missing_text_raises():
    """Verify missing or whitespace-only message_text raises MessageValidationError."""
    with pytest.raises(MessageValidationError):
        normalize_message_record({})

    with pytest.raises(MessageValidationError):
        normalize_message_record({"message_text": "   "})

    with pytest.raises(MessageValidationError):
        normalize_message_record("not a dict")


def test_normalize_message_direction_variants():
    """Verify message direction maps accurately from various string and boolean inputs."""
    assert normalize_message_direction("incoming") == "incoming"
    assert normalize_message_direction("inbound") == "incoming"
    assert normalize_message_direction("received") == "incoming"
    assert normalize_message_direction("IN") == "incoming"

    assert normalize_message_direction("outgoing") == "outgoing"
    assert normalize_message_direction("outbound") == "outgoing"
    assert normalize_message_direction("sent") == "outgoing"
    assert normalize_message_direction("OUT") == "outgoing"

    # Booleans
    assert normalize_message_direction(True) == "outgoing"
    assert normalize_message_direction(False) == "incoming"

    # Unknown
    assert normalize_message_direction(None) == "unknown"
    assert normalize_message_direction("something_else") == "unknown"


def test_normalize_message_direction_from_boolean_fields():
    """Verify direction inference from is_sender_me and is_outgoing boolean metadata."""
    msg1 = {"message_text": "Hi", "is_sender_me": True}
    assert normalize_message_record(msg1).message_direction == "outgoing"

    msg2 = {"message_text": "Hi", "is_sender_me": False}
    assert normalize_message_record(msg2).message_direction == "incoming"

    msg3 = {"message_text": "Hi", "is_outgoing": True}
    assert normalize_message_record(msg3).message_direction == "outgoing"

    msg4 = {"message_text": "Hi", "is_incoming": True}
    assert normalize_message_record(msg4).message_direction == "incoming"


def test_normalize_message_preserves_multiline_and_emoji():
    """Verify formatting, multi-line paragraphs and emojis are preserved intact."""
    complex_text = "Line 1\n\nLine 2 with emojis: 🚀 🤖 🎉\n\tIndented line"
    record = {"message_text": complex_text}
    normalized = normalize_message_record(record)
    assert normalized.message_text == complex_text


def test_normalize_message_record_fallback_conversation_id():
    """Verify fallback conversation_id is applied if not in record."""
    raw = {"message_text": "Reply here"}
    normalized = normalize_message_record(raw, conversation_id="fallback_conv_99")
    assert normalized.external_conversation_id == "fallback_conv_99"

