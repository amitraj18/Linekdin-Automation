"""Unit tests for template manager module."""

import json
from pathlib import Path
import pytest

from template_manager import (
    TemplateNotFoundError,
    TemplatePlaceholderError,
    TemplateValidationError,
    get_template,
    load_templates,
    render_template,
)


@pytest.fixture
def valid_templates_file(tmp_path: Path) -> Path:
    """Create a temporary valid templates.json file."""
    templates = {
        "initial_outreach": {
            "key": "initial_outreach",
            "name": "Initial Outreach",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, let's connect!",
        },
        "interested_reply": {
            "key": "interested_reply",
            "name": "Interested Reply",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, excited to speak with you.",
        },
        "request_more_info": {
            "key": "request_more_info",
            "name": "More Info",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, here is the requested info.",
        },
        "not_interested": {
            "key": "not_interested",
            "name": "Not Interested",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, thank you for your time.",
        },
        "unclear_reply": {
            "key": "unclear_reply",
            "name": "Unclear Reply",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, could you clarify?",
        },
        "five_day_followup": {
            "key": "five_day_followup",
            "name": "Followup",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, following up on my previous message.",
        },
    }
    file_path = tmp_path / "templates.json"
    file_path.write_text(json.dumps(templates, indent=2), encoding="utf-8")
    return file_path


def test_load_valid_templates(valid_templates_file: Path):
    """Valid templates file loads into dictionary successfully."""
    data = load_templates(valid_templates_file)
    assert len(data) == 6
    assert "initial_outreach" in data


def test_unknown_template_key_raises_error(valid_templates_file: Path):
    """Accessing an unknown template key raises TemplateNotFoundError."""
    with pytest.raises(TemplateNotFoundError, match="Template 'non_existent_key' not found"):
        get_template("non_existent_key", file_path=valid_templates_file)


def test_render_template_with_valid_context(valid_templates_file: Path):
    """Valid context renders placeholder values correctly."""
    rendered = render_template(
        "initial_outreach",
        {"first_name": "Sarah"},
        file_path=valid_templates_file,
    )
    assert rendered == "Hi Sarah, let's connect!"


def test_render_template_extracts_first_name_from_full_name(valid_templates_file: Path):
    """Contact full name automatically yields first_name for rendering."""
    rendered = render_template(
        "initial_outreach",
        {"name": "Robert Oppenheimer"},
        file_path=valid_templates_file,
    )
    assert rendered == "Hi Robert, let's connect!"


def test_missing_required_placeholder_raises_error(valid_templates_file: Path):
    """Missing or empty required placeholder raises TemplatePlaceholderError."""
    with pytest.raises(TemplatePlaceholderError, match="Missing required placeholder value"):
        render_template(
            "initial_outreach",
            {"first_name": ""},
            file_path=valid_templates_file,
        )


def test_malformed_json_raises_validation_error(tmp_path: Path):
    """Corrupted or invalid JSON raises TemplateValidationError."""
    bad_json_file = tmp_path / "bad_templates.json"
    bad_json_file.write_text("{ this is not valid json :", encoding="utf-8")

    with pytest.raises(TemplateValidationError, match="Malformed JSON"):
        load_templates(bad_json_file)


def test_empty_template_body_raises_validation_error(tmp_path: Path):
    """Template missing body raises TemplateValidationError."""
    invalid_templates = {
        "initial_outreach": {
            "key": "initial_outreach",
            "body": "   ",
        }
    }
    file_path = tmp_path / "empty_body.json"
    file_path.write_text(json.dumps(invalid_templates), encoding="utf-8")

    with pytest.raises(TemplateValidationError, match="missing a valid non-empty 'body'"):
        load_templates(file_path)

