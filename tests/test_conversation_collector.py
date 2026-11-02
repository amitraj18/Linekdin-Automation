"""Tests for conversation_collector CLI entry point."""

import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from config import AppConfig
from conversation_collector import main, run_conversation_collector
from database import init_db, reset_engine_cache
from excel_manager import initialize_workbooks


@pytest.fixture
def cli_setup(tmp_path: Path):
    """Set up isolated configuration, sqlite database, and Excel workbooks."""
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

    init_db(config=cfg)
    initialize_workbooks(cfg)

    yield cfg
    reset_engine_cache()


def test_cli_dry_run(cli_setup):
    """Test CLI runs successfully in dry-run mode."""
    cfg = cli_setup
    with patch("conversation_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--dry-run"])
        assert exit_code == 0


def test_cli_with_limit(cli_setup):
    """Test CLI with --limit flag."""
    cfg = cli_setup
    with patch("conversation_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--limit", "2"])
        assert exit_code == 0


def test_cli_with_conversation_id(cli_setup):
    """Test CLI with --conversation-id flag."""
    cfg = cli_setup
    with patch("conversation_collector.load_config", return_value=cfg):
        exit_code = main(["--source", "mock", "--conversation-id", "conv_001"])
        assert exit_code == 0


def test_cli_rebuild_workbook(cli_setup):
    """Test CLI --rebuild-workbook flag."""
    cfg = cli_setup
    with patch("conversation_collector.load_config", return_value=cfg):
        exit_code = main(["--rebuild-workbook"])
        assert exit_code == 0


def test_cli_unsupported_source_exits_error(cli_setup):
    """Test unsupported source parameter produces error exit."""
    cfg = cli_setup
    with patch("conversation_collector.load_config", return_value=cfg):
        # argparse choices restricts it, or run_conversation_collector directly raises
        with pytest.raises(SystemExit):
            main(["--source", "invalid_source_123"])

