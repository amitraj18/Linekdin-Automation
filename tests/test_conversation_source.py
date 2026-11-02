"""Tests for conversation history sources, including MockConversationSource."""

import pytest
from conversation.conversation_exceptions import (
    ConversationAuthError,
    ConversationRateLimitError,
    ConversationSourceError,
    ConversationTimeoutError,
)
from conversation.mock_conversation_source import MockConversationSource


def test_mock_conversation_source_default_threads():
    """Verify default mock conversation source returns expected conversation threads."""
    source = MockConversationSource()
    assert source.source_name == "mock"

    convs = source.fetch_conversations()
    assert len(convs) >= 9

    first = convs[0]
    assert "conversation_id" in first
    assert "participant_name" in first
    assert "external_contact_id" in first


def test_mock_conversation_source_fetch_messages():
    """Verify fetch_messages retrieves messages for a specific conversation."""
    source = MockConversationSource()
    convs = source.fetch_conversations()
    target_id = convs[0]["conversation_id"]

    messages = source.fetch_messages(target_id)
    assert len(messages) >= 1
    for msg in messages:
        assert "message_text" in msg
        assert "external_message_id" in msg
        assert "message_direction" in msg


def test_mock_conversation_source_empty_for_unknown_id():
    """Verify fetch_messages returns empty list for an unknown conversation id."""
    source = MockConversationSource()
    assert source.fetch_messages("non_existent_conv_xyz") == []


def test_mock_conversation_source_limit():
    """Verify limit parameter restricts number of conversations returned."""
    source = MockConversationSource()
    assert len(source.fetch_conversations(limit=2)) == 2
    assert len(source.fetch_conversations(limit=1)) == 1


def test_mock_conversation_source_fetch_all_conversations():
    """Verify fetch_all_conversations embeds messages into each conversation."""
    source = MockConversationSource()
    all_convs = source.fetch_all_conversations(limit=3)
    assert len(all_convs) == 3
    for conv in all_convs:
        assert "messages" in conv
        assert isinstance(conv["messages"], list)


def test_mock_conversation_source_empty_flag():
    """Verify empty_source returns empty list."""
    source = MockConversationSource(empty_source=True)
    assert source.fetch_conversations() == []
    assert source.fetch_all_conversations() == []


def test_mock_conversation_source_simulate_errors():
    """Verify simulation of auth, rate limit, timeout, and general errors."""
    with pytest.raises(ConversationAuthError):
        MockConversationSource(simulate_auth_error=True).fetch_conversations()

    with pytest.raises(ConversationRateLimitError):
        MockConversationSource(simulate_rate_limit=True).fetch_conversations()

    with pytest.raises(ConversationTimeoutError):
        MockConversationSource(simulate_timeout=True).fetch_conversations()

    with pytest.raises(ConversationSourceError):
        MockConversationSource(simulate_error=True).fetch_conversations()

    # Verify error on message fetch as well
    source = MockConversationSource(simulate_error=True)
    with pytest.raises(ConversationSourceError):
        source.fetch_messages("c_001")

