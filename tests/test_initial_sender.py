"""Unit and CLI integration tests for initial_sender.py."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select

from config import AppConfig
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import initialize_workbooks, load_contacts
from initial_sender import main, run_initial_sender
from models import Contact, Message
from sender.mock_messaging_adapter import MockMessagingAdapter


@pytest.fixture
def cli_setup(tmp_path: Path):
    """Set up isolated configuration and database environment for CLI tests."""
    reset_engine_cache()
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    templates_file = tmp_path / "templates.json"

    templates = {
        "initial_outreach": {
            "key": "initial_outreach",
            "name": "Initial Outreach",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, connecting from CLI test!",
        }
    }
    templates_file.write_text(json.dumps(templates), encoding="utf-8")

    db_file = data_dir / "test.db"
    cfg = AppConfig(
        project_root=tmp_path,
        data_dir=data_dir,
        logs_dir=logs_dir,
        database_path=db_file,
        database_url=f"sqlite:///{db_file.as_posix()}",
        contacts_workbook_path=data_dir / "contacts.xlsx",
        scraped_replies_workbook_path=data_dir / "scraped_replies.xlsx",
        automation_cycles_workbook_path=data_dir / "automation_cycles.xlsx",
        templates_file_path=templates_file,
        log_level="INFO",
        app_env="test",
        log_file_path=logs_dir / "automation.log",
        initial_template_key="initial_outreach",
        max_initial_messages_per_run=10,
        messaging_adapter="mock",
    )

    engine = create_engine(cfg.database_url, future=True)
    init_db(engine=engine, config=cfg)
    initialize_workbooks(cfg)

    yield cfg, engine

    engine.dispose()
    reset_engine_cache()


def test_dry_run_makes_no_adapter_calls_and_no_db_records(cli_setup):
    """Dry-run processes contacts logically without persisting messages or calling adapter."""
    cfg, engine = cli_setup

    with get_db_session(engine=engine) as session:
        session.add(Contact(name="Clark Kent", eligibility_status="eligible"))

    mock_adapter = MockMessagingAdapter()
    summary = run_initial_sender(
        config=cfg,
        dry_run=True,
        custom_adapter=mock_adapter,
    )

    assert summary.dry_run is True
    assert summary.total_eligible_found == 1
    assert summary.processed_count == 1
    assert summary.sent_count == 0
    assert len(mock_adapter.sent_messages) == 0

    # Verify no message records created
    with get_db_session(engine=engine) as session:
        messages = session.scalars(select(Message)).all()
        assert len(messages) == 0

    # Verify no contacts.xlsx updates
    contacts = load_contacts(cfg.contacts_workbook_path)
    assert len(contacts) == 0


def test_cli_main_dry_run(cli_setup, monkeypatch, capsys):
    """CLI main executes cleanly with --dry-run flag."""
    cfg, engine = cli_setup

    with get_db_session(engine=engine) as session:
        session.add(Contact(name="Barry Allen", eligibility_status="eligible"))

    with patch("initial_sender.load_config", return_value=cfg):
        exit_code = main(["--dry-run", "--limit", "1"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out
    assert "Total Eligible Found: 1" in captured.out


def test_cli_main_mock_run(cli_setup, capsys):
    """CLI main executes mock run, sends message, and exits with 0."""
    cfg, engine = cli_setup

    with get_db_session(engine=engine) as session:
        session.add(Contact(name="Arthur Curry", eligibility_status="eligible"))

    with patch("initial_sender.load_config", return_value=cfg):
        exit_code = main(["--limit", "5", "--adapter", "mock"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Sent:                 1" in captured.out

    with get_db_session(engine=engine) as session:
        msg = session.scalars(select(Message)).first()
        assert msg is not None
        assert msg.status == "sent"


def test_cli_invalid_adapter_argument():
    """Passing unsupported adapter to CLI exits with error code."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--adapter", "invalid_adapter"])
    assert exc_info.value.code != 0

