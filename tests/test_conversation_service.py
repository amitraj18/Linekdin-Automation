"""Tests for ConversationService workflow, persistence, and deduplication."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest
from sqlalchemy import select

from config import AppConfig
from conversation.conversation_service import ConversationService
from conversation.mock_conversation_source import MockConversationSource
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import ExcelFileLockedError, initialize_workbooks
from models import Contact, ConversationMessage, Reply


@pytest.fixture
def conversation_setup(tmp_path: Path):
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

    # Seed contacts corresponding to mock source
    with get_db_session(config=cfg) as session:
        c1 = Contact(name="Sarah Connor", external_contact_id="conn_ext_001", eligibility_status="eligible")
        c2 = Contact(name="John Matrix", external_contact_id="conn_ext_002", eligibility_status="eligible")
        c3 = Contact(name="Martin Riggs", external_contact_id="conn_ext_005", eligibility_status="eligible")
        session.add_all([c1, c2, c3])
        session.commit()

    yield cfg
    reset_engine_cache()


def test_conversation_service_dry_run(conversation_setup):
    """Verify dry_run=True does not persist records to SQLite or Excel."""
    cfg = conversation_setup
    source = MockConversationSource()
    service = ConversationService(config=cfg, source=source)

    summary = service.run(dry_run=True)
    assert summary.overall_status == "completed"
    assert summary.dry_run is True
    assert summary.conversations_fetched > 0
    assert summary.messages_fetched > 0

    with get_db_session(config=cfg) as session:
        conv_msgs = session.scalars(select(ConversationMessage)).all()
        assert len(conv_msgs) == 0
        replies = session.scalars(select(Reply)).all()
        assert len(replies) == 0


def test_conversation_service_live_collection_and_ordering(conversation_setup):
    """Verify live collection persists messages, syncs replies, and respects chronological ordering."""
    cfg = conversation_setup
    source = MockConversationSource()
    service = ConversationService(config=cfg, source=source)

    summary = service.run(dry_run=False)
    assert summary.overall_status == "completed"
    assert summary.new_messages_persisted > 0
    assert summary.excel_export_success is True

    with get_db_session(config=cfg) as session:
        conv_msgs = session.scalars(select(ConversationMessage)).all()
        assert len(conv_msgs) == summary.new_messages_persisted

        # Check chronological ordering in thread MOCK_CONV_005 (Martin Riggs - out-of-order in source)
        thread_005 = session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.external_conversation_id == "MOCK_CONV_005")
            .order_by(ConversationMessage.id.asc())
        ).all()
        assert len(thread_005) == 4
        # Message 1 (09:00) should be before Message 2 (10:30)
        assert thread_005[0].message_timestamp < thread_005[1].message_timestamp
        assert thread_005[0].external_message_id == "msg_005_1"
        assert thread_005[1].external_message_id == "msg_005_2"
        assert thread_005[2].external_message_id == "msg_005_3"

        # Check that incoming messages are also in Reply table
        replies = session.scalars(select(Reply)).all()
        assert len(replies) > 0
        for reply in replies:
            assert reply.reply_text is not None


def test_conversation_service_deduplication_across_runs(conversation_setup):
    """Verify running collection twice skips existing messages and does not create duplicates."""
    cfg = conversation_setup
    source = MockConversationSource()
    service = ConversationService(config=cfg, source=source)

    # First run
    s1 = service.run(dry_run=False)
    first_count = s1.new_messages_persisted
    assert first_count > 0

    # Second run
    s2 = service.run(dry_run=False)
    assert s2.new_messages_persisted == 0
    assert s2.duplicates_skipped == first_count

    with get_db_session(config=cfg) as session:
        conv_msgs = session.scalars(select(ConversationMessage)).all()
        assert len(conv_msgs) == first_count


def test_conversation_service_excel_sync_error_isolation(conversation_setup):
    """Verify failure during Excel export does not roll back SQLite persistence."""
    cfg = conversation_setup
    source = MockConversationSource()
    service = ConversationService(config=cfg, source=source)

    with patch("conversation.conversation_service.append_conversation_messages", side_effect=ExcelFileLockedError("Lock")):
        summary = service.run(dry_run=False)

    assert summary.overall_status == "partial"
    assert summary.excel_export_success is False
    assert summary.excel_export_error is not None

    # SQLite must still have persisted records
    with get_db_session(config=cfg) as session:
        conv_msgs = session.scalars(select(ConversationMessage)).all()
        assert len(conv_msgs) > 0


def test_conversation_service_filter_by_conversation_id(conversation_setup):
    """Verify filtering collection to a single specific conversation ID."""
    cfg = conversation_setup
    source = MockConversationSource()
    service = ConversationService(config=cfg, source=source)

    summary = service.run(conversation_id="MOCK_CONV_001")
    assert summary.conversations_fetched == 1
    with get_db_session(config=cfg) as session:
        conv_msgs = session.scalars(select(ConversationMessage)).all()
        assert len(conv_msgs) > 0
        assert all(m.external_conversation_id == "MOCK_CONV_001" for m in conv_msgs)
