"""Unit tests for ReplySource interface and MockReplySource implementation."""

import pytest

from collector.collector_exceptions import SourceError
from collector.mock_reply_source import MockReplySource, get_default_fictional_replies


def test_mock_source_default_records():
    """MockReplySource returns deterministic fictional replies by default."""
    source = MockReplySource()
    assert source.source_name == "mock"

    replies = source.fetch_replies()
    assert len(replies) == 5
    assert replies[0]["external_reply_id"] == "mock_rep_001"
    assert "interested" in replies[0]["reply_text"].lower()


def test_mock_source_limit_slicing():
    """MockReplySource honors limit parameter."""
    source = MockReplySource()
    replies = source.fetch_replies(limit=2)
    assert len(replies) == 2
    assert replies[0]["external_reply_id"] == "mock_rep_001"
    assert replies[1]["external_reply_id"] == "mock_rep_002"


def test_mock_source_empty_batch():
    """MockReplySource handles empty reply list cleanly."""
    source = MockReplySource(replies=[])
    replies = source.fetch_replies()
    assert replies == []


def test_mock_source_simulated_failure():
    """MockReplySource raises SourceError when failure simulation is configured."""
    source = MockReplySource(simulate_failure=ConnectionError("Simulated network timeout"))
    with pytest.raises(SourceError, match="Mock source failure simulated"):
        source.fetch_replies()

