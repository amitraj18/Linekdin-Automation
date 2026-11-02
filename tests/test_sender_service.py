"""Unit and integration tests for SenderService."""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select

from config import AppConfig
from database import get_db_session, init_db, reset_engine_cache
from excel_manager import ExcelFileLockedError, initialize_workbooks, load_contacts
from models import Contact, Message
from sender.messaging_adapter import SendResult
from sender.mock_messaging_adapter import MockMessagingAdapter
from sender.sender_exceptions import SenderConfigurationError
from sender.sender_service import SenderService


@pytest.fixture
def test_setup(tmp_path: Path):
    """Set up isolated configuration, sqlite database, excel sheets, and templates."""
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


def test_empty_contacts_returns_empty_summary(test_setup):
    """Running sender on an empty database returns 0 processed cleanly."""
    cfg, engine = test_setup
    service = SenderService(config=cfg, engine=engine)
    summary = service.run()

    assert summary.total_eligible_found == 0
    assert summary.processed_count == 0
    assert summary.sent_count == 0


def test_contact_eligibility_and_filtering(test_setup):
    """Sender filters out ineligible contacts, contacts with sent/pending/unknown messages."""
    cfg, engine = test_setup

    with get_db_session(engine=engine) as session:
        # 1. Eligible contact with no messages
        c1 = Contact(name="Eligible One", eligibility_status="eligible")
        # 2. Ineligible contact
        c2 = Contact(name="Ineligible Two", eligibility_status="ineligible")
        # 3. Contact already sent initial message
        c3 = Contact(name="Already Sent Three", eligibility_status="eligible")
        # 4. Contact with pending initial message
        c4 = Contact(name="Pending Four", eligibility_status="eligible")
        # 5. Contact with unknown status initial message
        c5 = Contact(name="Unknown Five", eligibility_status="eligible")
        # 6. Eligible contact with a failed initial message (or other non-blocking message)
        c6 = Contact(name="Eligible Six", eligibility_status="eligible")

        session.add_all([c1, c2, c3, c4, c5, c6])
        session.flush()

        msg_sent = Message(
            contact_id=c3.id,
            message_type="initial",
            message_text="Hello",
            status="sent",
            idempotency_key="idem_sent_3",
        )
        msg_pending = Message(
            contact_id=c4.id,
            message_type="initial",
            message_text="Hello",
            status="pending",
            idempotency_key="idem_pending_4",
        )
        msg_unknown = Message(
            contact_id=c5.id,
            message_type="initial",
            message_text="Hello",
            status="unknown",
            idempotency_key="idem_unknown_5",
        )
        session.add_all([msg_sent, msg_pending, msg_unknown])

    service = SenderService(config=cfg, engine=engine)
    with get_db_session(engine=engine) as session:
        eligible = service.get_eligible_contacts(session)
        names = [c.name for c in eligible]
        assert names == ["Eligible One", "Eligible Six"]


def test_per_run_limit(test_setup):
    """Sender honors per-run limit strictly."""
    cfg, engine = test_setup

    with get_db_session(engine=engine) as session:
        for i in range(5):
            session.add(Contact(name=f"User {i}", eligibility_status="eligible"))

    service = SenderService(config=cfg, engine=engine)
    summary = service.run(limit=2)

    assert summary.total_eligible_found == 2
    assert summary.processed_count == 2
    assert summary.sent_count == 2


def test_successful_send_persistence_and_excel_update(test_setup):
    """Confirmed mock sends update SQLite message record and contacts.xlsx."""
    cfg, engine = test_setup

    with get_db_session(engine=engine) as session:
        c = Contact(name="Diana Prince", eligibility_status="eligible")
        session.add(c)
        session.flush()
        c_id = c.id

    mock_adapter = MockMessagingAdapter(default_outcome="sent")
    service = SenderService(config=cfg, adapter=mock_adapter, engine=engine)
    summary = service.run()

    assert summary.sent_count == 1
    assert summary.failed_count == 0

    # Verify SQLite message record
    with get_db_session(engine=engine) as session:
        msg = session.scalars(select(Message).where(Message.contact_id == c_id)).first()
        assert msg is not None
        assert msg.status == "sent"
        assert msg.sent_at is not None
        assert msg.message_text == "Hi Diana, would love to connect!"

    # Verify Excel update
    contacts = load_contacts(cfg.contacts_workbook_path)
    assert len(contacts) == 1
    assert contacts[0]["Contact ID"] == str(c_id)
    assert contacts[0]["Initial Message Status"] == "sent"


def test_explicit_failure_and_unknown_outcomes(test_setup):
    """Explicit failures and unknown outcomes are recorded with error messages and not retried."""
    cfg, engine = test_setup

    with get_db_session(engine=engine) as session:
        c1 = Contact(name="Fail Person", eligibility_status="eligible")
        c2 = Contact(name="Timeout Person", eligibility_status="eligible")
        session.add_all([c1, c2])
        session.flush()
        c1_id = c1.id
        c2_id = c2.id

    custom_outcomes = {
        str(c1_id): SendResult(outcome="failed", error_message="Explicit failure response"),
        str(c2_id): SendResult(outcome="unknown", error_message="Request timed out"),
    }
    adapter = MockMessagingAdapter(recipient_outcomes=custom_outcomes)
    service = SenderService(config=cfg, adapter=adapter, engine=engine)
    summary = service.run()

    assert summary.failed_count == 1
    assert summary.unknown_count == 1
    assert summary.sent_count == 0

    with get_db_session(engine=engine) as session:
        m1 = session.scalars(select(Message).where(Message.contact_id == c1_id)).first()
        assert m1.status == "failed"
        assert "Explicit failure" in m1.error_message

        m2 = session.scalars(select(Message).where(Message.contact_id == c2_id)).first()
        assert m2.status == "unknown"
        assert "timed out" in m2.error_message


def test_independent_commits_isolation(test_setup):
    """Failure or exception on a later contact does not undo previous successful contacts."""
    cfg, engine = test_setup

    with get_db_session(engine=engine) as session:
        c1 = Contact(name="First Success", eligibility_status="eligible")
        c2 = Contact(name="Second Failure", eligibility_status="eligible")
        session.add_all([c1, c2])
        session.flush()
        c1_id = c1.id
        c2_id = c2.id

    custom_outcomes = {
        str(c1_id): SendResult(outcome="sent"),
        str(c2_id): SendResult(outcome="failed", error_message="Simulated error"),
    }
    adapter = MockMessagingAdapter(recipient_outcomes=custom_outcomes)
    service = SenderService(config=cfg, adapter=adapter, engine=engine)
    summary = service.run()

    assert summary.sent_count == 1
    assert summary.failed_count == 1

    with get_db_session(engine=engine) as session:
        m1 = session.scalars(select(Message).where(Message.contact_id == c1_id)).first()
        assert m1.status == "sent"
        m2 = session.scalars(select(Message).where(Message.contact_id == c2_id)).first()
        assert m2.status == "failed"


def test_excel_failure_does_not_abort_database_record(test_setup):
    """If Excel is locked or raises error, DB record is preserved and logged as excel error."""
    cfg, engine = test_setup

    with get_db_session(engine=engine) as session:
        c = Contact(name="Bruce Wayne", eligibility_status="eligible")
        session.add(c)
        session.flush()
        c_id = c.id

    adapter = MockMessagingAdapter(default_outcome="sent")
    service = SenderService(config=cfg, adapter=adapter, engine=engine)

    with patch("sender.sender_service.update_contact_status", side_effect=ExcelFileLockedError("File open in Excel")):
        summary = service.run()

    # DB record is still saved as 'sent'
    assert summary.sent_count == 1
    assert summary.excel_errors_count == 1

    with get_db_session(engine=engine) as session:
        msg = session.scalars(select(Message).where(Message.contact_id == c_id)).first()
        assert msg is not None
        assert msg.status == "sent"


def test_missing_template_raises_error(test_setup):
    """Running sender with non-existent template key raises SenderConfigurationError."""
    cfg, engine = test_setup
    service = SenderService(config=cfg, engine=engine)

    with pytest.raises(SenderConfigurationError, match="Template error"):
        service.run(template_key="non_existent_key")

