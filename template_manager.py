"""Message template manager module.

Handles loading, validating, and rendering message templates from JSON with
strict placeholder validation and clear error reporting.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from config import AppConfig, CONFIG

logger = logging.getLogger("linkedin_automation.templates")

# Matches Python-style format placeholders like {first_name}, {company}, etc.
PLACEHOLDER_REGEX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class TemplateError(Exception):
    """Base exception for template operations."""


class TemplateNotFoundError(TemplateError):
    """Raised when a requested template key cannot be found in the catalog."""


class TemplateValidationError(TemplateError):
    """Raised when the templates file format or schema is invalid."""


class TemplatePlaceholderError(TemplateError):
    """Raised when required personalization placeholders cannot be resolved."""


def extract_placeholders(template_text: str) -> Set[str]:
    """Extract all placeholder names enclosed in single curly braces from a text."""
    return set(PLACEHOLDER_REGEX.findall(template_text))


def load_templates(file_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load and validate the JSON templates file."""
    path = Path(file_path or CONFIG.templates_file_path).resolve()
    if not path.exists():
        raise TemplateValidationError(f"Template file does not exist: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise TemplateValidationError(f"Malformed JSON in template file '{path.name}': {exc}") from exc
    except Exception as exc:
        raise TemplateError(f"Failed to read template file '{path.name}': {exc}") from exc

    if not isinstance(data, dict):
        raise TemplateValidationError(f"Templates root must be a JSON object/dictionary, got {type(data).__name__}.")

    validate_templates(data)
    return data


def validate_templates(templates: Dict[str, Any]) -> None:
    """Validate that templates dictionary contains valid structure and required fields."""
    if not templates:
        raise TemplateValidationError("Templates dictionary is empty.")

    required_keys = {
        "initial_outreach",
        "interested_reply",
        "request_more_info",
        "not_interested",
        "unclear_reply",
        "five_day_followup",
    }

    missing_standard_keys = required_keys - set(templates.keys())
    if missing_standard_keys:
        logger.warning(
            "Templates dictionary does not include all standard keys. Missing: %s",
            sorted(missing_standard_keys),
        )

    for key, item in templates.items():
        if not isinstance(item, dict):
            raise TemplateValidationError(f"Template entry '{key}' must be a JSON object.")

        if "body" not in item or not isinstance(item["body"], str) or not item["body"].strip():
            raise TemplateValidationError(f"Template entry '{key}' is missing a valid non-empty 'body' string.")

        # Ensure required_placeholders is a list if present
        if "required_placeholders" in item and not isinstance(item["required_placeholders"], list):
            raise TemplateValidationError(
                f"Template entry '{key}' has 'required_placeholders' that is not a list."
            )


def get_template(key: str, file_path: Optional[Path] = None) -> Dict[str, Any]:
    """Retrieve a single template definition by its key."""
    templates = load_templates(file_path)
    if key not in templates:
        raise TemplateNotFoundError(
            f"Template '{key}' not found. Available templates: {list(templates.keys())}"
        )
    return templates[key]


def validate_placeholders(
    template_body: str,
    context: Dict[str, Any],
    required_placeholders: Optional[List[str]] = None,
) -> None:
    """Check that all required and used placeholders can be resolved from context.

    Raises TemplatePlaceholderError if any placeholder is missing or empty.
    """
    found_in_body = extract_placeholders(template_body)
    required = set(required_placeholders or []) | found_in_body

    missing: List[str] = []
    for ph in sorted(required):
        val = context.get(ph)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(ph)

    if missing:
        raise TemplatePlaceholderError(
            f"Cannot render template. Missing required placeholder value(s): {', '.join(missing)}"
        )


def _prepare_contact_context(contact_data: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich context with convenient derived fields such as first_name."""
    ctx = dict(contact_data)
    # If first_name not provided, try to extract from 'name' or 'Contact Name'
    if not ctx.get("first_name"):
        name_val = ctx.get("name") or ctx.get("Contact Name")
        if name_val and isinstance(name_val, str) and name_val.strip():
            ctx["first_name"] = name_val.strip().split()[0]
    return ctx


def render_template(
    key: str,
    context: Dict[str, Any],
    file_path: Optional[Path] = None,
) -> str:
    """Load a template by key, validate context variables, and render the final text."""
    template_def = get_template(key, file_path)
    body: str = template_def["body"]
    reqs: List[str] = template_def.get("required_placeholders", [])

    enriched_context = _prepare_contact_context(context)
    validate_placeholders(body, enriched_context, reqs)

    try:
        # Use str.format with safe dictionary substitution
        return body.format(**enriched_context)
    except KeyError as exc:
        raise TemplatePlaceholderError(f"Missing placeholder value during rendering: {exc}") from exc

