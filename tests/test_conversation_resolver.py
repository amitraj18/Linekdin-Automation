"""Tests for contact resolution hierarchy in conversations."""

from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from conversation.conversation_resolver import ConversationResolver, ResolvedConversationContact
from database import init_db, reset_engine_cache
from models import Base, Contact


@pytest.fixture
def memory_db():
    """Create in-memory SQLite database for contact resolution tests."""
    reset_engine_cache()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed test contacts
        c1 = Contact(
            name="Alice Smith",
            external_contact_id="linkedin_alice_1",
            profile_url="https://linkedin.com/in/alicesmith",
            eligibility_status="eligible",
        )
        c2 = Contact(
            name="Bob Jones",
            external_contact_id="linkedin_bob_2",
            profile_url="https://linkedin.com/in/bobjones",
            eligibility_status="eligible",
        )
        # Duplicate name contacts to test ambiguity
        c3 = Contact(
            name="Charlie Brown",
            external_contact_id="linkedin_cb_3",
            profile_url="https://linkedin.com/in/charlie1",
            eligibility_status="eligible",
        )
        c4 = Contact(
            name="Charlie Brown",
            external_contact_id="linkedin_cb_4",
            profile_url="https://linkedin.com/in/charlie2",
            eligibility_status="eligible",
        )
        session.add_all([c1, c2, c3, c4])
        session.commit()
        yield engine
    reset_engine_cache()


def test_resolve_by_external_contact_id(memory_db):
    """Priority 1: resolve contact by external_contact_id."""
    with Session(memory_db) as session:
        contact, status = ConversationResolver.resolve_contact(
            session=session,
            external_contact_id="linkedin_alice_1",
        )
        assert contact is not None
        assert contact.name == "Alice Smith"
        assert status == "new"


def test_resolve_by_internal_contact_id(memory_db):
    """Priority 2: resolve contact by internal contact_id."""
    with Session(memory_db) as session:
        alice = session.query(Contact).filter_by(name="Alice Smith").one()
        contact, status = ConversationResolver.resolve_contact(
            session=session,
            contact_id=alice.id,
        )
        assert contact is not None
        assert contact.id == alice.id
        assert status == "new"


def test_resolve_by_unique_participant_name(memory_db):
    """Priority 3: resolve contact by unique display name match."""
    with Session(memory_db) as session:
        contact, status = ConversationResolver.resolve_contact(
            session=session,
            participant_name="Bob Jones",
        )
        assert contact is not None
        assert contact.name == "Bob Jones"
        assert contact.external_contact_id == "linkedin_bob_2"
        assert status == "new"


def test_resolve_ambiguous_name_returns_needs_review(memory_db):
    """Ambiguous case: multiple contacts match the same name -> returns (None, 'needs_review')."""
    with Session(memory_db) as session:
        contact, status = ConversationResolver.resolve_contact(
            session=session,
            participant_name="Charlie Brown",
        )
        assert contact is None
        assert status == "needs_review"


def test_resolve_unmatched_contact_returns_needs_review(memory_db):
    """Unknown case: contact cannot be found -> returns (None, 'needs_review')."""
    with Session(memory_db) as session:
        contact, status = ConversationResolver.resolve_contact(
            session=session,
            external_contact_id="completely_unknown_user",
            participant_name="Stranger In The Night",
        )
        assert contact is None
        assert status == "needs_review"

