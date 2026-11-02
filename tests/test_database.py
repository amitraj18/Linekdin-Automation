"""Unit tests for database layer and SQLAlchemy ORM models."""

from datetime import datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError

from database import _enforce_sqlite_foreign_keys, get_db_session, init_db, reset_engine_cache
from models import AutomationCycle, Base, Contact, Message, Reply


@pytest.fixture
def test_engine(tmp_path: Path):
    """Create an isolated SQLite database engine with foreign keys enabled."""
    reset_engine_cache()
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", future=True)
    init_db(engine=engine)
    yield engine
    engine.dispose()
    reset_engine_cache()


def test_schema_initialization(test_engine):
    """Tables are successfully created during schema initialization."""
    table_names = Base.metadata.tables.keys()
    assert "contacts" in table_names
    assert "messages" in table_names
    assert "replies" in table_names
    assert "automation_cycles" in table_names


def test_crud_contact_message_reply_cycle(test_engine):
    """Records for Contact, Message, Reply, and AutomationCycle can be created and retrieved."""
    now = datetime.now(timezone.utc)

    # 1. Create contact
    with get_db_session(engine=test_engine) as session:
        contact = Contact(
            name="Alice Walker",
            external_contact_id="li_12345",
            profile_url="https://linkedin.com/in/alicewalker",
            eligibility_status="eligible",
        )
        session.add(contact)
        session.flush()
        contact_id = contact.id

    # 2. Retrieve contact and create message & reply
    with get_db_session(engine=test_engine) as session:
        contact = session.get(Contact, contact_id)
        assert contact is not None
        assert contact.name == "Alice Walker"

        message = Message(
            contact_id=contact.id,
            message_type="initial",
            template_key="initial_outreach",
            message_text="Hi Alice, let's connect!",
            status="pending",
            idempotency_key="msg_idem_001",
        )
        reply = Reply(
            contact_id=contact.id,
            external_reply_id="rep_999",
            reply_text="Sounds great, let's talk!",
            processing_status="new",
            category="interested",
        )
        cycle = AutomationCycle(
            started_at=now,
            status="running",
            initial_messages_processed=1,
        )
        session.add_all([message, reply, cycle])

    # 3. Verify relationships and records persisted
    with get_db_session(engine=test_engine) as session:
        contact = session.get(Contact, contact_id)
        assert len(contact.messages) == 1
        assert contact.messages[0].idempotency_key == "msg_idem_001"
        assert len(contact.replies) == 1
        assert contact.replies[0].category == "interested"

        cycles = session.scalars(select(AutomationCycle)).all()
        assert len(cycles) == 1
        assert cycles[0].status == "running"


def test_foreign_key_enforcement(test_engine):
    """Inserting a Message or Reply with a non-existent contact_id fails with IntegrityError."""
    with pytest.raises(IntegrityError):
        with get_db_session(engine=test_engine) as session:
            bad_message = Message(
                contact_id=999999,  # Non-existent contact
                message_type="initial",
                message_text="Hello?",
                status="pending",
                idempotency_key="bad_fk_001",
            )
            session.add(bad_message)


def test_transaction_rollback_on_failure(test_engine):
    """Errors during a session transaction trigger automatic rollback."""
    try:
        with get_db_session(engine=test_engine) as session:
            contact = Contact(name="Temporary Contact", eligibility_status="eligible")
            session.add(contact)
            session.flush()

            # Trigger an intentional error in the transaction block
            raise ValueError("Intentional business logic failure")
    except ValueError:
        pass

    with get_db_session(engine=test_engine) as session:
        contacts = session.scalars(
            select(Contact).where(Contact.name == "Temporary Contact")
        ).all()
        assert len(contacts) == 0, "Record should have been rolled back"


def test_unique_idempotency_key_prevents_duplicate_sends(test_engine):
    """Duplicate idempotency keys in Message table are rejected."""
    with get_db_session(engine=test_engine) as session:
        contact = Contact(name="Bob Smith", eligibility_status="eligible")
        session.add(contact)
        session.flush()
        c_id = contact.id

        msg1 = Message(
            contact_id=c_id,
            message_type="initial",
            message_text="Hello",
            status="pending",
            idempotency_key="unique_key_123",
        )
        session.add(msg1)

    with pytest.raises(IntegrityError):
        with get_db_session(engine=test_engine) as session:
            msg2 = Message(
                contact_id=c_id,
                message_type="initial",
                message_text="Hello again",
                status="pending",
                idempotency_key="unique_key_123",  # Duplicate key
            )
            session.add(msg2)

