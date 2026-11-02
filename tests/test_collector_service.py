"""Unit and integration tests for CollectorService."""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest
from sqlalchemy import create_engine, select

from collector.collector_service import CollectorService
from collector.mock_reply_source import MockReplySource
from config import AppConfig
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import ExcelFileLockedError, initialize_workbooks, validate_workbook
from models import Contact, Reply


@pytest.fixture
def collector_setup(tmp_path: Path):
    """Set up isolated configuration, sqlite database, and excel workbooks."""
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


def test_contact_resolution_methods(collector_setup):
    """Contacts resolve by ID, external_contact_id, or unique name, and ambiguous names flag review."""
    cfg, engine = collector_setup

    with get_db_session(engine=engine) as session:
        c1 = Contact(name="Alice One", external_contact_id="ext_alice", eligibility_status="eligible")
        c2 = Contact(name="Bob Two", eligibility_status="eligible")
        # Two contacts with the same name to test ambiguous matching
        c3 = Contact(name="Charlie Ambiguous", eligibility_status="eligible")
        c4 = Contact(name="Charlie Ambiguous", eligibility_status="eligible")
        session.add_all([c1, c2, c3, c4])

    mock_replies = [
        # Match by external_contact_id
        {"external_reply_id": "r1", "external_contact_id": "ext_alice", "reply_text": "Reply 1"},
        # Match by unique name
        {"external_reply_id": "r2", "contact_name": "Bob Two", "reply_text": "Reply 2"},
        # Ambiguous name match -> needs_review
        {"external_reply_id": "r3", "contact_name": "Charlie Ambiguous", "reply_text": "Reply 3"},
        # Completely unknown contact -> needs_review
        {"external_reply_id": "r4", "contact_name": "Ghost User", "reply_text": "Reply 4"},
    ]

    service = CollectorService(config=cfg, source=MockReplySource(replies=mock_replies), engine=engine)
    summary = service.run()

    assert summary.new_replies_persisted == 4
    assert summary.records_needing_review == 2  # r3 and r4

    with get_db_session(engine=engine) as session:
        r1 = session.scalars(select(Reply).where(Reply.external_reply_id == "r1")).first()
        assert r1.contact.name == "Alice One"
        assert r1.processing_status == "new"

        r2 = session.scalars(select(Reply).where(Reply.external_reply_id == "r2")).first()
        assert r2.contact.name == "Bob Two"
        assert r2.processing_status == "new"

        r3 = session.scalars(select(Reply).where(Reply.external_reply_id == "r3")).first()
        assert r3.contact_id is None
        assert r3.processing_status == "needs_review"

        r4 = session.scalars(select(Reply).where(Reply.external_reply_id == "r4")).first()
        assert r4.contact_id is None
        assert r4.processing_status == "needs_review"


def test_deduplication_in_batch_and_across_runs(collector_setup):
    """Duplicates within a batch and in subsequent runs are skipped without altering existing data."""
    cfg, engine = collector_setup

    with get_db_session(engine=engine) as session:
        session.add(Contact(name="Dedupe User", external_contact_id="li_dedupe", eligibility_status="eligible"))

    batch = [
        {"external_reply_id": "dup_001", "external_contact_id": "li_dedupe", "reply_text": "Original text"},
        {"external_reply_id": "dup_001", "external_contact_id": "li_dedupe", "reply_text": "Duplicate in batch"},
    ]

    service = CollectorService(config=cfg, source=MockReplySource(replies=batch), engine=engine)
    summary1 = service.run()

    assert summary1.records_fetched == 2
    assert summary1.new_replies_persisted == 1
    assert summary1.duplicates_skipped == 1

    # Second run with identical data
    summary2 = service.run()
    assert summary2.records_fetched == 2
    assert summary2.new_replies_persisted == 0
    assert summary2.duplicates_skipped == 2

    # Verify existing reply text was preserved
    with get_db_session(engine=engine) as session:
        replies = session.scalars(select(Reply).where(Reply.external_reply_id == "dup_001")).all()
        assert len(replies) == 1
        assert replies[0].reply_text == "Original text"


def test_excel_export_and_isolation(collector_setup):
    """Persisted replies are exported to Excel; Excel failures do not affect SQLite."""
    cfg, engine = collector_setup

    with get_db_session(engine=engine) as session:
        session.add(Contact(name="Export User", external_contact_id="li_exp", eligibility_status="eligible"))

    batch = [{"external_reply_id": "exp_01", "external_contact_id": "li_exp", "reply_text": "Exportable reply"}]

    service = CollectorService(config=cfg, source=MockReplySource(replies=batch), engine=engine)
    summary = service.run()

    assert summary.new_replies_persisted == 1
    assert summary.excel_export_success is True

    # Verify row in Excel
    wb = openpyxl.load_workbook(cfg.scraped_replies_workbook_path)
    ws = wb["ScrapedReplies"]
    assert ws.max_row == 2
    row_vals = [cell.value for cell in ws[2]]
    assert "Exportable reply" in row_vals
    wb.close()

    # Now test with simulated Excel failure
    batch2 = [{"external_reply_id": "exp_02", "external_contact_id": "li_exp", "reply_text": "Second reply"}]
    service2 = CollectorService(config=cfg, source=MockReplySource(replies=batch2), engine=engine)

    with patch("collector.collector_service.append_scraped_replies", side_effect=ExcelFileLockedError("Locked")):
        summary2 = service2.run()

    assert summary2.new_replies_persisted == 1
    assert summary2.excel_export_success is False
    assert "Locked" in (summary2.excel_export_error or "")

    # SQLite has both replies intact
    with get_db_session(engine=engine) as session:
        all_replies = session.scalars(select(Reply)).all()
        assert len(all_replies) == 2


def test_rebuild_workbook_from_sqlite(collector_setup):
    """rebuild_workbook reconstructs scraped_replies.xlsx from SQLite with all records and correct headers."""
    cfg, engine = collector_setup

    with get_db_session(engine=engine) as session:
        c = Contact(name="Rebuild User", external_contact_id="li_reb", eligibility_status="eligible")
        session.add(c)
        session.flush()

        r1 = Reply(
            contact_id=c.id,
            external_reply_id="reb_01",
            conversation_id="conv_reb",
            reply_text="Recovered message 1",
            processing_status="new",
        )
        r2 = Reply(
            contact_id=c.id,
            external_reply_id="reb_02",
            conversation_id="conv_reb",
            reply_text="Recovered message 2 (processed)",
            processing_status="processed",
        )
        session.add_all([r1, r2])

    # Remove or corrupt the existing Excel file
    if cfg.scraped_replies_workbook_path.exists():
        cfg.scraped_replies_workbook_path.unlink()

    service = CollectorService(config=cfg, engine=engine)
    recovered_count = service.rebuild_workbook()

    assert recovered_count == 2
    assert cfg.scraped_replies_workbook_path.exists()

    # Verify reconstructed sheet
    wb = openpyxl.load_workbook(cfg.scraped_replies_workbook_path)
    ws = wb["ScrapedReplies"]
    assert ws.max_row == 3  # Header + 2 rows
    row2 = [cell.value for cell in ws[2]]
    row3 = [cell.value for cell in ws[3]]
    assert "reb_01" in row2 and "new" in row2
    assert "reb_02" in row3 and "processed" in row3
    wb.close()

