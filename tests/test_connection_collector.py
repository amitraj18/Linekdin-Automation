"""CLI integration tests for connection_collector.py."""

from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest
from sqlalchemy import create_engine, select

from config import AppConfig
from connection_collector import main
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import initialize_workbooks
from models import Contact, Message


@pytest.fixture
def cli_setup(tmp_path: Path):
    """Set up isolated configuration and database environment for connection CLI tests."""
    reset_engine_cache()
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    templates_file = tmp_path / "templates.json"
    templates_file.write_text(
        '{"initial_outreach": {"key": "initial_outreach", "required_placeholders": ["first_name"], "body": "Hi {first_name}!"}}',
        encoding="utf-8",
    )

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
    )

    engine = create_engine(cfg.database_url, future=True)
    init_db(engine=engine, config=cfg)
    initialize_workbooks(cfg)

    yield cfg, engine

    engine.dispose()
    reset_engine_cache()


def test_cli_dry_run_leaves_state_unchanged(cli_setup, capsys):
    """Dry-run validates mock connection records without writing to DB or Excel."""
    cfg, engine = cli_setup

    with patch("connection_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--dry-run"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "DRY_RUN" in captured.out
    assert "Overall Status:         completed" in captured.out

    # Verify no contacts in SQLite
    with get_db_session(engine=engine) as session:
        contacts = session.scalars(select(Contact)).all()
        assert len(contacts) == 0

    # Verify no contacts in contacts.xlsx
    wb = openpyxl.load_workbook(cfg.contacts_workbook_path)
    ws = wb["Contacts"]
    assert ws.max_row == 1  # Only header
    wb.close()


def test_cli_collection_only_mode(cli_setup, capsys):
    """Default collection-only mode inserts contacts, updates Excel, but sends no messages."""
    cfg, engine = cli_setup

    with patch("connection_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--limit", "3"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Contacts Inserted:      3" in captured.out
    assert "Initial Sender Outreach" not in captured.out

    # Verify contacts persisted
    with get_db_session(engine=engine) as session:
        contacts = session.scalars(select(Contact)).all()
        assert len(contacts) == 3
        # Verify NO messages sent
        messages = session.scalars(select(Message)).all()
        assert len(messages) == 0


def test_cli_send_mode_triggers_outreach(cli_setup, capsys):
    """When --send is passed, outreach is triggered for eligible contacts."""
    cfg, engine = cli_setup

    with patch("connection_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--limit", "2", "--send"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Initial Sender Outreach" in captured.out
    assert "Messages Confirmed Sent:" in captured.out

    with get_db_session(engine=engine) as session:
        messages = session.scalars(select(Message)).all()
        assert len(messages) > 0
        assert messages[0].status == "sent"


def test_cli_invalid_source_argument():
    """Unsupported source argument exits with error code."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--source", "unsupported_platform"])
    assert exc_info.value.code != 0

