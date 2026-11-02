"""Initial message sender service.

Queries eligible contacts, validates records, personalizes initial outreach templates,
persists pending message records, calls the messaging adapter, updates SQLite and Excel,
and returns structured execution summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from config import AppConfig, CONFIG
from database import get_db_session, get_engine
from excel_manager import ExcelError, update_contact_status
from models import Contact, Message
from sender.messaging_adapter import MessagingAdapter, SendResult
from sender.mock_messaging_adapter import MockMessagingAdapter
from sender.sender_exceptions import (
    ContactValidationError,
    PersistenceError,
    SenderConfigurationError,
    SenderError,
    TemplateResolutionError,
)
from template_manager import TemplateError, get_template, render_template

logger = logging.getLogger("linkedin_automation.sender")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class SenderRunSummary:
    """Structured execution summary of an initial-sender run."""

    total_eligible_found: int = 0
    processed_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    unknown_count: int = 0
    skipped_count: int = 0
    excel_errors_count: int = 0
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary representation."""
        return {
            "total_eligible_found": self.total_eligible_found,
            "processed_count": self.processed_count,
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "unknown_count": self.unknown_count,
            "skipped_count": self.skipped_count,
            "excel_errors_count": self.excel_errors_count,
            "dry_run": self.dry_run,
            "errors": list(self.errors),
        }


class SenderService:
    """Coordinates initial message outreach to eligible contacts."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        adapter: Optional[MessagingAdapter] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        """Initialize SenderService with configuration, adapter, and database engine."""
        self.config = config or CONFIG
        self.engine = engine or get_engine(self.config)
        self.adapter = adapter or self._resolve_adapter()

    def _resolve_adapter(self) -> MessagingAdapter:
        """Resolve messaging adapter based on application configuration."""
        adapter_type = getattr(self.config, "messaging_adapter", "mock").lower()
        if adapter_type == "mock":
            return MockMessagingAdapter()
        raise SenderConfigurationError(
            f"Unsupported or unverified messaging adapter: '{adapter_type}'. "
            f"Only authorized adapters (such as 'mock') are supported."
        )

    def validate_contact(self, contact: Contact) -> None:
        """Validate that a contact has essential fields for initial messaging."""
        if not contact.id:
            raise ContactValidationError("Contact missing primary key identifier.")
        if not contact.name or not contact.name.strip():
            raise ContactValidationError(f"Contact ID {contact.id} has an empty or invalid name.")
        if contact.eligibility_status.lower() != "eligible":
            raise ContactValidationError(
                f"Contact '{contact.name}' (ID {contact.id}) is not marked 'eligible' "
                f"(status: '{contact.eligibility_status}')."
            )

    def get_eligible_contacts(
        self,
        session: Session,
        limit: Optional[int] = None,
    ) -> List[Contact]:
        """Query contacts eligible for initial message outreach.

        Eligibility criteria:
        - eligibility_status == 'eligible'
        - Has not received a confirmed initial message ('sent')
        - Has no pending or unknown initial message awaiting reconciliation
        - Ordered deterministically by contact.id
        """
        # Subquery for contacts who already have an initial message that is sent, pending, or unknown
        ineligible_contact_ids = (
            select(Message.contact_id)
            .where(
                Message.message_type == "initial",
                Message.status.in_(("sent", "pending", "unknown")),
            )
            .scalar_subquery()
        )

        stmt = (
            select(Contact)
            .where(
                Contact.eligibility_status == "eligible",
                Contact.id.not_in(ineligible_contact_ids),
            )
            .order_by(Contact.id.asc())
        )

        effective_limit = limit
        if effective_limit is None:
            effective_limit = getattr(self.config, "max_initial_messages_per_run", 10)

        if effective_limit > 0:
            stmt = stmt.limit(effective_limit)

        return list(session.scalars(stmt).all())

    def _generate_idempotency_key(self, contact_id: int, template_key: str) -> str:
        """Generate a stable, unique idempotency key for an intended initial send."""
        return f"initial_msg_contact_{contact_id}_{template_key}"

    def run(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
        template_key: Optional[str] = None,
    ) -> SenderRunSummary:
        """Execute the initial message outreach workflow."""
        summary = SenderRunSummary(dry_run=dry_run)
        t_key = template_key or getattr(self.config, "initial_template_key", "initial_outreach")

        logger.info(
            "Starting initial message run (dry_run=%s, limit=%s, template='%s', adapter='%s')",
            dry_run,
            limit,
            t_key,
            self.adapter.adapter_name,
        )

        # 1. Verify template can be loaded before proceeding
        try:
            get_template(t_key, file_path=self.config.templates_file_path)
        except TemplateError as exc:
            err = f"Template error for key '{t_key}': {exc}"
            logger.error(err)
            summary.errors.append(err)
            raise SenderConfigurationError(err) from exc

        # 2. Query eligible contacts
        with get_db_session(engine=self.engine) as session:
            contacts = self.get_eligible_contacts(session=session, limit=limit)
            # Detach contact data so we can work with them without keeping an open transaction
            contact_snapshots = [
                {
                    "id": c.id,
                    "external_contact_id": c.external_contact_id,
                    "name": c.name,
                    "profile_url": c.profile_url,
                    "eligibility_status": c.eligibility_status,
                }
                for c in contacts
            ]

        summary.total_eligible_found = len(contact_snapshots)
        logger.info("Found %d eligible contact(s) for initial outreach.", len(contact_snapshots))

        if not contact_snapshots:
            logger.info("No eligible contacts to process. Run complete.")
            return summary

        # 3. Process each contact independently
        for c_data in contact_snapshots:
            contact_id = c_data["id"]
            contact_name = c_data["name"]
            idempotency_key = self._generate_idempotency_key(contact_id, t_key)

            # Validate contact record
            if not contact_name or not contact_name.strip():
                logger.warning("Contact ID %d has empty name; skipping.", contact_id)
                summary.skipped_count += 1
                continue

            # Personalize message using template manager
            try:
                rendered_text = render_template(
                    t_key,
                    c_data,
                    file_path=self.config.templates_file_path,
                )
            except TemplateError as exc:
                err_msg = f"Failed to render template '{t_key}' for contact '{contact_name}' (ID {contact_id}): {exc}"
                logger.error(err_msg)
                summary.errors.append(err_msg)
                summary.skipped_count += 1
                continue

            # If dry-run, log and skip actual message creation & sending
            if dry_run:
                logger.info(
                    "[DRY-RUN] Would send initial message to '%s' (ID %d) using template '%s'",
                    contact_name,
                    contact_id,
                    t_key,
                )
                summary.processed_count += 1
                continue

            # 4. Check idempotency and persist pending message record
            message_id: Optional[int] = None
            try:
                with get_db_session(engine=self.engine) as session:
                    # Check if message already exists with this idempotency key
                    existing_msg = session.scalars(
                        select(Message).where(Message.idempotency_key == idempotency_key)
                    ).first()

                    if existing_msg:
                        if existing_msg.status in ("sent", "pending", "unknown"):
                            logger.info(
                                "Message already exists with status '%s' for contact ID %d (key: %s); skipping.",
                                existing_msg.status,
                                contact_id,
                                idempotency_key,
                            )
                            summary.skipped_count += 1
                            continue
                        elif existing_msg.status == "failed":
                            # Update existing failed message record to pending for retry
                            existing_msg.status = "pending"
                            existing_msg.message_text = rendered_text
                            existing_msg.error_message = None
                            session.flush()
                            message_id = existing_msg.id
                    else:
                        # Persist message with 'pending' status
                        pending_msg = Message(
                            contact_id=contact_id,
                            message_type="initial",
                            template_key=t_key,
                            message_text=rendered_text,
                            status="pending",
                            idempotency_key=idempotency_key,
                            created_at=_utc_now(),
                        )
                        session.add(pending_msg)
                        session.flush()
                        message_id = pending_msg.id
            except Exception as exc:
                err_msg = f"Failed to persist pending message for contact ID {contact_id}: {exc}"
                logger.error(err_msg)
                summary.errors.append(err_msg)
                summary.failed_count += 1
                continue

            summary.processed_count += 1

            # 5. Call messaging adapter (outside of database transaction)
            recipient_info = {
                "id": contact_id,
                "name": contact_name,
                "external_contact_id": c_data["external_contact_id"],
                "profile_url": c_data["profile_url"],
            }

            try:
                send_result = self.adapter.send(recipient_info, rendered_text)
            except Exception as exc:
                logger.error("Adapter exception sending to contact ID %d: %s", contact_id, exc)
                send_result = SendResult(
                    outcome="unknown",
                    error_message=f"Adapter execution exception: {exc}",
                )

            # 6. Persist confirmed outcome in SQLite
            sent_timestamp: Optional[datetime] = None
            try:
                with get_db_session(engine=self.engine) as session:
                    msg_record = session.get(Message, message_id)
                    if msg_record is None:
                        raise PersistenceError(f"Message ID {message_id} not found for status update.")

                    if send_result.outcome == "sent":
                        sent_timestamp = send_result.timestamp or _utc_now()
                        msg_record.status = "sent"
                        msg_record.sent_at = sent_timestamp
                        msg_record.error_message = None
                    elif send_result.outcome == "failed":
                        msg_record.status = "failed"
                        msg_record.error_message = send_result.error_message
                    else:  # unknown
                        msg_record.status = "unknown"
                        msg_record.error_message = send_result.error_message or "Send outcome could not be confirmed."
            except Exception as exc:
                err_msg = f"Failed to update message status for contact ID {contact_id}: {exc}"
                logger.error(err_msg)
                summary.errors.append(err_msg)

            # Track summary metric
            if send_result.outcome == "sent":
                summary.sent_count += 1
                logger.info("Successfully sent initial message to '%s' (ID %d).", contact_name, contact_id)
            elif send_result.outcome == "failed":
                summary.failed_count += 1
                logger.warning(
                    "Send failed for '%s' (ID %d): %s",
                    contact_name,
                    contact_id,
                    send_result.error_message,
                )
            else:
                summary.unknown_count += 1
                logger.warning(
                    "Send outcome unknown for '%s' (ID %d); recorded without automatic retry: %s",
                    contact_name,
                    contact_id,
                    send_result.error_message,
                )

            # 7. Update contacts.xlsx reporting workbook
            # If Excel fails or is locked, preserve SQLite record and log reconciliation need
            try:
                contact_row_update = {
                    "Contact ID": str(contact_id),
                    "Contact Name": contact_name,
                    "Profile URL": c_data.get("profile_url") or "",
                    "Eligibility Status": c_data.get("eligibility_status") or "eligible",
                    "Initial Message Status": send_result.outcome,
                    "Initial Message Timestamp": sent_timestamp,
                }
                update_contact_status(
                    contact_row_update,
                    file_path=self.config.contacts_workbook_path,
                )
            except ExcelError as exc:
                summary.excel_errors_count += 1
                logger.error(
                    "Failed to update contacts.xlsx for contact ID %d (needs reconciliation): %s",
                    contact_id,
                    exc,
                )

        logger.info(
            "Initial sender run complete: processed=%d, sent=%d, failed=%d, unknown=%d, skipped=%d, excel_errors=%d",
            summary.processed_count,
            summary.sent_count,
            summary.failed_count,
            summary.unknown_count,
            summary.skipped_count,
            summary.excel_errors_count,
        )
        return summary
