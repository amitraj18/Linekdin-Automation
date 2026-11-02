"""Unit and integration tests for ConnectionService."""

import json
from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest
from sqlalchemy import create_engine, select

from config import AppConfig
from connections.connection_service import ConnectionService
from connections.mock_connection_source import MockConnectionSource
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import ExcelFileLockedError, initialize_workbooks, load_contacts
from models import Contact, Message, Reply
from sender.mock_messaging_adapter import MockMessagingAdapter


@pytest.fixture
def connection_setup(tmp_path: Path):
    """Set up isolated configuration, sqlite database, templates, and workbooks."""
    reset_engine_cache()
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    templates_file = tmp_path / "templates.json"

    templates = {
        "initial_outreach": {
            "key": "initial_outreach",
            "name": "Initial Outreach",
            "required_placeholders": ["first_name"],
            "body": "Hi {first_name}, would love to connect!",
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


def test_collection_inserts_and_syncs_excel(connection_setup):
    """Mock connection source inserts new contacts and synchronizes contacts.xlsx."""
    cfg, engine = connection_setup

    mock_conns = [
        {"external_contact_id": "c1", "name": "Sarah Connor", "eligibility_status": "eligible"},
        {"external_contact_id": "c2", "name": "John Matrix", "eligibility_status": "eligible"},
        {"external_contact_id": "c3", "name": "Kyle Reese", "eligibility_status": "ineligible"},
    ]

    service = ConnectionService(config=cfg, source=MockConnectionSource(connections=mock_conns), engine=engine)
    summary = service.run(send_messages=False)

    assert summary.records_fetched == 3
    assert summary.contacts_inserted == 3
    assert summary.contacts_updated == 0
    assert summary.messages_attempted == 0  # Collection-only

    # Verify SQLite records
    with get_db_session(engine=engine) as session:
        contacts = session.scalars(select(Contact).order_by(Contact.id.asc())).all()
        assert len(contacts) == 3
        assert contacts[0].name == "Sarah Connor"
        assert contacts[2].eligibility_status == "ineligible"

    # Verify contacts.xlsx
    excel_records = load_contacts(cfg.contacts_workbook_path)
    assert len(excel_records) == 3
    assert excel_records[0]["Contact Name"] == "Sarah Connor"


def test_deduplication_and_opt_out_preservation(connection_setup):
    """Repeated collection does not create duplicate contacts and preserves safety status."""
    cfg, engine = connection_setup

    # Pre-seed contact marked as opt_out
    with get_db_session(engine=engine) as session:
        c = Contact(
            name="Opted Out User",
            external_contact_id="c_opt",
            profile_url="https://linkedin.com/in/old",
            eligibility_status="opt_out",
        )
        session.add(c)

    batch_with_duplicates = [
        {"external_contact_id": "c_opt", "name": "Opted Out User", "profile_url": "https://linkedin.com/in/new", "eligibility_status": "eligible"},
        {"external_contact_id": "c_new", "name": "New User", "eligibility_status": "eligible"},
        {"external_contact_id": "c_new", "name": "New User", "eligibility_status": "eligible"},  # Duplicate in same batch
    ]

    service = ConnectionService(config=cfg, source=MockConnectionSource(connections=batch_with_duplicates), engine=engine)
    summary = service.run(send_messages=False)

    assert summary.records_fetched == 3
    assert summary.contacts_inserted == 1
    assert summary.contacts_updated == 1
    assert summary.duplicates_skipped == 1

    # Verify opt-out was NOT overwritten with eligible
    with get_db_session(engine=engine) as session:
        opt_contact = session.scalars(select(Contact).where(Contact.external_contact_id == "c_opt")).first()
        assert opt_contact.eligibility_status == "opt_out"
        assert opt_contact.profile_url == "https://linkedin.com/in/new"

        all_contacts = session.scalars(select(Contact)).all()
        assert len(all_contacts) == 2


def test_sender_integration(connection_setup):
    """When send_messages=True, eligible contacts receive initial outreach via SenderService."""
    cfg, engine = connection_setup

    mock_conns = [
        {"external_contact_id": "s1", "name": "Alice Walker", "eligibility_status": "eligible"},
        {"external_contact_id": "s2", "name": "Bob Ineligible", "eligibility_status": "ineligible"},
    ]

    adapter = MockMessagingAdapter(default_outcome="sent")
    service = ConnectionService(
        config=cfg,
        source=MockConnectionSource(connections=mock_conns),
        adapter=adapter,
        engine=engine,
    )

    summary = service.run(send_messages=True)

    assert summary.contacts_inserted == 2
    assert summary.messages_attempted == 1  # Only Alice is eligible
    assert summary.messages_confirmed_sent == 1
    assert summary.messages_failed == 0

    # Verify Message record persisted
    with get_db_session(engine=engine) as session:
        msg = session.scalars(select(Message)).first()
        assert msg is not None
        assert msg.status == "sent"
        assert msg.contact.name == "Alice Walker"

    # Verify contacts.xlsx updated
    excel_records = load_contacts(cfg.contacts_workbook_path)
    alice_row = next(r for r in excel_records if r["Contact Name"] == "Alice Walker")
    assert alice_row["Initial Message Status"] == "sent"


def test_excel_failure_does_not_abort_database(connection_setup):
    """Excel write failure logs warning but leaves SQLite database contact records intact."""
    cfg, engine = connection_setup

    mock_conns = [{"external_contact_id": "f1", "name": "Resilient Contact"}]
    service = ConnectionService(config=cfg, source=MockConnectionSource(connections=mock_conns), engine=engine)

    with patch("connections.connection_service.update_contact_status", side_effect=ExcelFileLockedError("Locked")):
        summary = service.run(send_messages=False)

    assert summary.contacts_inserted == 1
    assert summary.excel_sync_success is False
    assert "Locked" in (summary.excel_sync_error or "")

    with get_db_session(engine=engine) as session:
        contact = session.scalars(select(Contact).where(Contact.name == "Resilient Contact")).first()
        assert contact is not None


def test_no_changes_to_reply_workbook_during_connection_collection(connection_setup):
    """Connection collection does not touch scraped_replies.xlsx."""
    cfg, engine = connection_setup

    wb = openpyxl.load_workbook(cfg.scraped_replies_workbook_path)
    initial_rows = wb["ScrapedReplies"].max_row
    wb.close()

    service = ConnectionService(config=cfg, engine=engine)
    service.run(send_messages=False)

    wb_after = openpyxl.load_workbook(cfg.scraped_replies_workbook_path)
    after_rows = wb_after["ScrapedReplies"].max_row
    wb_after.close()

    assert initial_rows == after_rows == 1

