"""Contact and conversation resolution logic.

Resolves conversations and messages to existing database contacts using strict priority rules.
"""

from __future__ import annotations

import logging
from typing import NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Contact

logger = logging.getLogger("linkedin_automation.conversation.resolver")


class ResolvedConversationContact(NamedTuple):
    """Result of resolving a conversation to an internal Contact."""

    contact: Optional[Contact]
    status: str


class ConversationResolver:
    """Resolves contact references for conversation threads following strict hierarchy."""

    @staticmethod
    def resolve_contact(
        session: Session,
        external_contact_id: Optional[str] = None,
        contact_id: Optional[int] = None,
        participant_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ResolvedConversationContact:
        """Resolve a contact based on priority:
        1. Reliable external contact identifier (external_contact_id).
        2. Existing internal contact reference (contact_id).
        3. Unique exact display name match (only if exactly 1 match).

        If ambiguous or unresolved:
        Returns ResolvedConversationContact(None, 'needs_review').
        """
        # Priority 1: Reliable external contact identifier
        if external_contact_id:
            ext_clean = str(external_contact_id).strip()
            if ext_clean:
                contact = session.scalars(
                    select(Contact).where(Contact.external_contact_id == ext_clean)
                ).first()
                if contact:
                    return ResolvedConversationContact(contact, "new")

        # Priority 2: Existing internal contact reference
        if contact_id is not None:
            contact = session.get(Contact, contact_id)
            if contact:
                return ResolvedConversationContact(contact, "new")

        # Priority 3: Unique exact display name match (only if exactly 1 match)
        if participant_name:
            name_clean = str(participant_name).strip()
            if name_clean:
                candidates = session.scalars(
                    select(Contact).where(Contact.name == name_clean)
                ).all()
                if len(candidates) == 1:
                    return ResolvedConversationContact(candidates[0], "new")
                elif len(candidates) > 1:
                    logger.warning(
                        "Ambiguous contact match for name '%s': found %d contacts. Flagging for review.",
                        name_clean,
                        len(candidates),
                    )
                    return ResolvedConversationContact(None, "needs_review")

        # Could not resolve contact confidently
        logger.debug(
            "Contact could not be resolved for conversation '%s' (ext_id=%s, name=%s)",
            conversation_id,
            external_contact_id,
            participant_name,
        )
        return ResolvedConversationContact(None, "needs_review")
