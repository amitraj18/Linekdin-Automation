"""Unit tests for connection record normalization."""

import pytest

from connections.connection_exceptions import ConnectionValidationError
from connections.connection_normalizer import normalize_connection_record


def test_normalize_valid_connection():
    """Valid raw connection dict is normalized with correct types and fields."""
    raw = {
        "external_contact_id": "ext_999",
        "name": "  Sarah Connor  ",
        "profile_url": "https://linkedin.com/in/sarahconnor",
        "headline": "Engineering Director",
        "eligibility_status": "Eligible",
    }
    norm = normalize_connection_record(raw)

    assert norm.external_contact_id == "ext_999"
    assert norm.name == "Sarah Connor"
    assert norm.profile_url == "https://linkedin.com/in/sarahconnor"
    assert norm.headline == "Engineering Director"
    assert norm.eligibility_status == "eligible"
    assert norm.needs_review is False


def test_normalize_missing_external_id_flags_review():
    """Connection without external_contact_id is normalized but flagged for review."""
    raw = {"name": "No ID Contact"}
    norm = normalize_connection_record(raw)

    assert norm.name == "No ID Contact"
    assert norm.external_contact_id is None
    assert norm.needs_review is True


def test_normalize_empty_name_raises_validation_error():
    """Connection with missing or empty name raises ConnectionValidationError."""
    with pytest.raises(ConnectionValidationError, match="missing required non-empty 'name'"):
        normalize_connection_record({"name": "   "})

    with pytest.raises(ConnectionValidationError, match="missing required non-empty 'name'"):
        normalize_connection_record({"other_field": "123"})


def test_normalize_non_dict_raises_validation_error():
    """Non-dictionary input raises ConnectionValidationError."""
    with pytest.raises(ConnectionValidationError, match="Expected dictionary record"):
        normalize_connection_record(["list", "instead", "of", "dict"])

