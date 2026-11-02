"""CLI integration tests for reply_collector.py."""

from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest
from sqlalchemy import create_engine, select

from config import AppConfig
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import initialize_workbooks
from models import Contact, Reply
from reply_collector import main, run_collector, run_rebuild_workbook


@pytest.fixture
def cli_setup(tmp_path: Path):
    """Set up isolated configuration and database environment for CLI tests."""
    reset_engine_cache()
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    templates_file = tmp_path / "templates.json"
    templates_file.write_text("{}", encoding="utf-8")

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
    """Dry-run validates records without modifying SQLite or Excel."""
    cfg, engine = cli_setup

    with patch("reply_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--dry-run"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out
    assert "Overall Status:      completed" in captured.out

    # Verify no records in SQLite
    with get_db_session(engine=engine) as session:
        replies = session.scalars(select(Reply)).all()
        assert len(replies) == 0

    # Verify no records in Excel (only header)
    wb = openpyxl.load_workbook(cfg.scraped_replies_workbook_path)
    ws = wb["ScrapedReplies"]
    assert ws.max_row == 1
    wb.close()


def test_cli_mock_collection_and_rebuild(cli_setup, capsys):
    """CLI collects mock replies into SQLite and Excel, and rebuilds cleanly."""
    cfg, engine = cli_setup

    with patch("reply_collector.load_config", return_value=cfg):
        # 1. Run collection with limit 2
        exit_code = main(["--source", "mock", "--limit", "2"])
        assert exit_code == 0

        # Verify 2 replies saved
        with get_db_session(engine=engine) as session:
            assert len(session.scalars(select(Reply)).all()) == 2

        # 2. Run rebuild workbook
        rebuild_code = main(["--rebuild-workbook"])
        assert rebuild_code == 0

    captured = capsys.readouterr()
    assert "New Persisted:       2" in captured.out
    assert "Successfully rebuilt scraped_replies.xlsx with 2 reply records" in captured.out


def test_cli_invalid_source_argument():
    """Unsupported source parameter exits with error."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--source", "unsupported_source"])
    assert exc_info.value.code != 0

