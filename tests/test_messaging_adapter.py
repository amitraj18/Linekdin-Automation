"""Unit tests for messaging adapter contracts and mock adapter behaviors."""

from datetime import datetime
import pytest

from sender.messaging_adapter import SendResult
from sender.mock_messaging_adapter import MockMessagingAdapter


def test_send_result_valid_outcomes():
    """SendResult accepts valid outcomes and rejects invalid ones."""
    res_sent = SendResult(outcome="sent", external_message_id="msg_123")
    assert res_sent.outcome == "sent"

    res_failed = SendResult(outcome="failed", error_message="Network issue")
    assert res_failed.outcome == "failed"

    res_unknown = SendResult(outcome="unknown", error_message="Timeout")
    assert res_unknown.outcome == "unknown"

    with pytest.raises(ValueError, match="Invalid SendResult outcome"):
        SendResult(outcome="invalid_status")


def test_mock_adapter_confirmed_success():
    """MockMessagingAdapter default behavior returns confirmed success."""
    adapter = MockMessagingAdapter(default_outcome="sent")
    assert adapter.adapter_name == "mock"

    recipient = {"id": 1, "name": "Alice Walker", "external_contact_id": "li_001"}
    result = adapter.send(recipient, "Hi Alice, let's connect!")

    assert result.outcome == "sent"
    assert result.external_message_id is not None
    assert isinstance(result.timestamp, datetime)
    assert len(adapter.sent_messages) == 1
    assert adapter.sent_messages[0]["recipient_info"]["name"] == "Alice Walker"
    assert adapter.sent_messages[0]["message_text"] == "Hi Alice, let's connect!"


def test_mock_adapter_explicit_failure():
    """MockMessagingAdapter returns explicit failure when configured."""
    adapter = MockMessagingAdapter(default_outcome="failed")
    recipient = {"id": 2, "name": "Bob Stone"}
    result = adapter.send(recipient, "Hi Bob!")

    assert result.outcome == "failed"
    assert result.error_code == "MOCK_SEND_FAILED"
    assert "Simulated mock failure" in (result.error_message or "")


def test_mock_adapter_uncertain_outcome():
    """MockMessagingAdapter returns uncertain outcome when configured."""
    adapter = MockMessagingAdapter(default_outcome="unknown")
    recipient = {"id": 3, "name": "Charlie Day"}
    result = adapter.send(recipient, "Hi Charlie!")

    assert result.outcome == "unknown"
    assert result.error_code == "MOCK_SEND_TIMEOUT_UNCERTAIN"


def test_mock_adapter_per_recipient_outcomes():
    """MockMessagingAdapter can return custom outcomes mapped by contact ID or name."""
    custom_map = {
        "10": SendResult(outcome="sent", external_message_id="custom_10"),
        "20": SendResult(outcome="failed", error_message="Custom fail for 20"),
        "David": SendResult(outcome="unknown", error_message="Uncertain for David"),
    }
    adapter = MockMessagingAdapter(default_outcome="sent", recipient_outcomes=custom_map)

    res1 = adapter.send({"id": 10, "name": "Ten"}, "Hello")
    assert res1.outcome == "sent"
    assert res1.external_message_id == "custom_10"

    res2 = adapter.send({"id": 20, "name": "Twenty"}, "Hello")
    assert res2.outcome == "failed"
    assert res2.error_message == "Custom fail for 20"

    res3 = adapter.send({"id": 99, "name": "David"}, "Hello")
    assert res3.outcome == "unknown"

    # Default fallback for unmapped recipient
    res4 = adapter.send({"id": 55, "name": "Unmapped"}, "Hello")
    assert res4.outcome == "sent"


def test_mock_adapter_simulate_exception():
    """MockMessagingAdapter raises configured exception when requested."""
    adapter = MockMessagingAdapter(simulate_exception=ConnectionResetError("Socket broken"))
    with pytest.raises(ConnectionResetError, match="Socket broken"):
        adapter.send({"id": 1, "name": "Test"}, "Hello")

