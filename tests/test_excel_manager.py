"""Unit tests for Excel infrastructure and workbook operations."""

from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest

from config import AppConfig
from excel_manager import (
    CONTACTS_COLUMNS,
    CONTACTS_SHEET,
    CYCLE_HISTORY_COLUMNS,
    CYCLE_HISTORY_SHEET,
    SCRAPED_REPLIES_COLUMNS,
    SCRAPED_REPLIES_SHEET,
    ExcelError,
    ExcelFileLockedError,
    InvalidWorkbookStructureError,
    append_cycle_history,
    append_scraped_replies,
    initialize_workbooks,
    load_contacts,
    update_contact_status,
    validate_workbook,
)


@pytest.fixture
def test_config(tmp_path: Path) -> AppConfig:
    """Provide an isolated AppConfig pointing to temporary paths."""
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    templates_file = tmp_path / "templates.json"
    templates_file.write_text("{}", encoding="utf-8")

    return AppConfig(
        project_root=tmp_path,
        data_dir=data_dir,
        logs_dir=logs_dir,
        database_path=data_dir / "test.db",
        database_url=f"sqlite:///{(data_dir / 'test.db').as_posix()}",
        contacts_workbook_path=data_dir / "contacts.xlsx",
        scraped_replies_workbook_path=data_dir / "scraped_replies.xlsx",
        automation_cycles_workbook_path=data_dir / "automation_cycles.xlsx",
        templates_file_path=templates_file,
        log_level="INFO",
        app_env="test",
        log_file_path=logs_dir / "automation.log",
    )


def test_workbooks_initialized_with_correct_headers(test_config: AppConfig):
    """All three workbooks are created with exact sheet names and headers."""
    initialize_workbooks(test_config)

    assert test_config.contacts_workbook_path.exists()
    assert test_config.scraped_replies_workbook_path.exists()
    assert test_config.automation_cycles_workbook_path.exists()

    assert validate_workbook(
        test_config.contacts_workbook_path, CONTACTS_SHEET, CONTACTS_COLUMNS
    )
    assert validate_workbook(
        test_config.scraped_replies_workbook_path,
        SCRAPED_REPLIES_SHEET,
        SCRAPED_REPLIES_COLUMNS,
    )
    assert validate_workbook(
        test_config.automation_cycles_workbook_path,
        CYCLE_HISTORY_SHEET,
        CYCLE_HISTORY_COLUMNS,
    )


def test_contact_status_update_and_preservation(test_config: AppConfig):
    """Contacts can be added, updated, and existing records are preserved."""
    initialize_workbooks(test_config)
    contacts_path = test_config.contacts_workbook_path

    # Insert first contact
    is_update = update_contact_status(
        {
            "Contact ID": "C001",
            "Contact Name": "John Doe",
            "Profile URL": "https://linkedin.com/in/johndoe",
            "Eligibility Status": "eligible",
            "Initial Message Status": "pending",
        },
        file_path=contacts_path,
    )
    assert is_update is False

    # Insert second contact
    update_contact_status(
        {
            "Contact ID": "C002",
            "Contact Name": "Jane Smith",
            "Eligibility Status": "eligible",
        },
        file_path=contacts_path,
    )

    records = load_contacts(contacts_path)
    assert len(records) == 2
    assert records[0]["Contact ID"] == "C001"
    assert records[1]["Contact ID"] == "C002"

    # Update C001
    updated = update_contact_status(
        {
            "Contact ID": "C001",
            "Initial Message Status": "sent",
            "Initial Message Timestamp": "2026-10-29 10:00:00",
        },
        file_path=contacts_path,
    )
    assert updated is True

    # Verify C001 updated while preserving name, and C002 remains unchanged
    updated_records = load_contacts(contacts_path)
    assert len(updated_records) == 2
    c001 = next(r for r in updated_records if r["Contact ID"] == "C001")
    assert c001["Contact Name"] == "John Doe"
    assert c001["Initial Message Status"] == "sent"

    c002 = next(r for r in updated_records if r["Contact ID"] == "C002")
    assert c002["Contact Name"] == "Jane Smith"


def test_scraped_replies_duplicate_prevention(test_config: AppConfig):
    """Repeated appends do not duplicate replies with identical Reply ID."""
    initialize_workbooks(test_config)
    replies_path = test_config.scraped_replies_workbook_path

    replies = [
        {
            "Contact ID": "C001",
            "Contact Name": "John Doe",
            "Conversation ID": "conv_101",
            "Reply ID": "REP_001",
            "Reply Text": "Sounds interesting, tell me more.",
            "Processing Status": "new",
        },
        {
            "Contact ID": "C002",
            "Contact Name": "Jane Smith",
            "Conversation ID": "conv_102",
            "Reply ID": "REP_002",
            "Reply Text": "Not interested at this time.",
            "Processing Status": "new",
        },
    ]

    added = append_scraped_replies(replies, file_path=replies_path)
    assert added == 2

    # Attempt to append the same list again
    added_second_time = append_scraped_replies(replies, file_path=replies_path)
    assert added_second_time == 0, "Duplicate replies should be skipped"


def test_cycle_history_duplicate_prevention(test_config: AppConfig):
    """Repeated appends do not duplicate identical Cycle ID + Contact ID records."""
    initialize_workbooks(test_config)
    cycles_path = test_config.automation_cycles_workbook_path

    cycle_records = [
        {
            "Cycle ID": "CYC_001",
            "Contact ID": "C001",
            "Contact Name": "John Doe",
            "Initial Message Status": "sent",
            "Response Status": "pending",
        }
    ]

    count1 = append_cycle_history(cycle_records, file_path=cycles_path)
    assert count1 == 1

    count2 = append_cycle_history(cycle_records, file_path=cycles_path)
    assert count2 == 0


def test_missing_file_handling():
    """Validating non-existent file raises InvalidWorkbookStructureError."""
    with pytest.raises(InvalidWorkbookStructureError, match="Workbook does not exist"):
        validate_workbook(Path("nonexistent.xlsx"), "Contacts", CONTACTS_COLUMNS)


def test_invalid_headers_detected(tmp_path: Path):
    """Workbooks with incorrect headers trigger validation error."""
    bad_file = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["Wrong Header 1", "Wrong Header 2"])
    wb.save(bad_file)
    wb.close()

    with pytest.raises(InvalidWorkbookStructureError, match="header mismatch"):
        validate_workbook(bad_file, "Contacts", CONTACTS_COLUMNS)


def test_locked_workbook_produces_clear_error(test_config: AppConfig):
    """When a file is locked or raises PermissionError on save, ExcelFileLockedError is raised."""
    initialize_workbooks(test_config)
    contacts_path = test_config.contacts_workbook_path

    with patch("os.replace", side_effect=PermissionError("Access denied by system")):
        with pytest.raises(ExcelFileLockedError, match="currently locked or open in Excel"):
            update_contact_status(
                {"Contact ID": "C999", "Contact Name": "Blocked User"},
                file_path=contacts_path,
            )

