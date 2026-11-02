"""Connection service coordinating contact retrieval, normalization,
database upserts, Excel synchronization, and optional initial message sender execution.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from config import AppConfig, CONFIG
from connections.connection_exceptions import (
    ConnectionCollectorError,
    ConnectionPersistenceError,
    ConnectionSourceError,
    ConnectionValidationError,
)
from connections.connection_normalizer import (
    NormalizedConnection,
    normalize_connection_record,
)
from connections.connection_source import ConnectionSource
from connections.mock_connection_source import MockConnectionSource
from database import get_db_session, get_engine
from excel_manager import ExcelError, update_contact_status
from models import Contact
from sender.messaging_adapter import MessagingAdapter
from sender.sender_service import SenderRunSummary, SenderService

logger = logging.getLogger("linkedin_automation.connections.service")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class ConnectionRunSummary:
    """Structured execution summary of a connection collection and sender integration run."""

    run_id: str
    source_name: str
    mode: str = "collection_only"
    records_fetched: int = 0
    records_validated: int = 0
    contacts_inserted: int = 0
    contacts_updated: int = 0
    duplicates_skipped: int = 0
    records_needing_review: int = 0
    eligible_contacts: int = 0
    messages_attempted: int = 0
    messages_confirmed_sent: int = 0
    messages_failed: int = 0
    messages_unknown: int = 0
    excel_sync_success: bool = True
    excel_sync_error: Optional[str] = None
    browser_cleanup_success: bool = True
    overall_status: str = "completed"
    completed_at: datetime = field(default_factory=_utc_now)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary representation."""
        return {
            "run_id": self.run_id,
            "source_name": self.source_name,
            "mode": self.mode,
            "records_fetched": self.records_fetched,
            "records_validated": self.records_validated,
            "contacts_inserted": self.contacts_inserted,
            "contacts_updated": self.contacts_updated,
            "duplicates_skipped": self.duplicates_skipped,
            "records_needing_review": self.records_needing_review,
            "eligible_contacts": self.eligible_contacts,
            "messages_attempted": self.messages_attempted,
            "messages_confirmed_sent": self.messages_confirmed_sent,
            "messages_failed": self.messages_failed,
            "messages_unknown": self.messages_unknown,
            "excel_sync_success": self.excel_sync_success,
            "excel_sync_error": self.excel_sync_error,
            "browser_cleanup_success": self.browser_cleanup_success,
            "overall_status": self.overall_status,
            "completed_at": self.completed_at.isoformat(),
            "errors": list(self.errors),
        }


class ConnectionService:
    """Coordinates connection retrieval, normalization, persistence, Excel sync, and sender integration."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        source: Optional[ConnectionSource] = None,
        adapter: Optional[MessagingAdapter] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        """Initialize ConnectionService."""
        self.config = config or CONFIG
        self.engine = engine or get_engine(self.config)
        self.source = source or MockConnectionSource()
        self.adapter = adapter  # If None, SenderService resolves its default mock adapter

    def upsert_contact(
        self,
        session: Session,
        norm: NormalizedConnection,
    ) -> tuple[Contact, bool]:
        """Upsert contact based on external_contact_id or name.

        Returns (contact, is_new).
        Preserves existing eligibility_status if already set to ineligible or opt-out.
        """
        existing: Optional[Contact] = None

        if norm.external_contact_id:
            existing = session.scalars(
                select(Contact).where(Contact.external_contact_id == norm.external_contact_id)
            ).first()

        if existing is None and norm.name:
            # Check by exact name if no external ID matched
            existing = session.scalars(
                select(Contact).where(Contact.name == norm.name)
            ).first()

        if existing is not None:
            # Update non-destructive profile attributes
            if norm.profile_url:
                existing.profile_url = norm.profile_url
            if norm.external_contact_id and not existing.external_contact_id:
                existing.external_contact_id = norm.external_contact_id

            # Preserve safety/opt-out status: do not overwrite ineligible/opt_out with eligible
            if existing.eligibility_status.lower() in ("ineligible", "opt_out", "suppressed"):
                logger.debug(
                    "Preserving safety status '%s' for contact '%s' (ID %d)",
                    existing.eligibility_status,
                    existing.name,
                    existing.id,
                )
            else:
                existing.eligibility_status = norm.eligibility_status

            existing.updated_at = _utc_now()
            session.flush()
            return existing, False

        # Create new contact record
        new_contact = Contact(
            external_contact_id=norm.external_contact_id,
            name=norm.name,
            profile_url=norm.profile_url,
            eligibility_status=norm.eligibility_status,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        session.add(new_contact)
        session.flush()
        return new_contact, True

    def run(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
        send_messages: bool = False,
        sender_limit: Optional[int] = None,
    ) -> ConnectionRunSummary:
        """Execute the connection collection workflow, optionally followed by initial sender outreach."""
        run_id = f"conn_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
        mode = "dry_run" if dry_run else ("collect_and_send" if send_messages else "collection_only")

        summary = ConnectionRunSummary(
            run_id=run_id,
            source_name=self.source.source_name,
            mode=mode,
        )

        logger.info(
            "Starting connection run '%s' (source='%s', mode='%s', limit=%s, send_messages=%s)",
            run_id,
            self.source.source_name,
            mode,
            limit,
            send_messages,
        )

        # 1. Fetch raw connections from source
        try:
            raw_records = self.source.fetch_connections(limit=limit)
        except Exception as exc:
            err_msg = f"Failed to fetch connections from source '{self.source.source_name}': {exc}"
            logger.error(err_msg)
            summary.overall_status = "failed"
            summary.errors.append(err_msg)
            summary.completed_at = _utc_now()
            return summary

        summary.records_fetched = len(raw_records)
        logger.info("Fetched %d connection record(s) from source.", len(raw_records))

        if not raw_records:
            logger.info("Empty connection batch received; run complete.")
            summary.completed_at = _utc_now()
            return summary

        seen_external_ids: Set[str] = set()
        persisted_contacts_for_excel: List[Dict[str, Any]] = []

        # 2. Process records individually
        for raw_item in raw_records:
            try:
                norm = normalize_connection_record(raw_item)
                summary.records_validated += 1
            except ConnectionValidationError as exc:
                logger.warning("Connection validation failure: %s", exc)
                summary.errors.append(str(exc))
                continue

            if norm.needs_review:
                summary.records_needing_review += 1

            # In-batch duplicate check
            if norm.external_contact_id:
                if norm.external_contact_id in seen_external_ids:
                    logger.debug("Skipping duplicate connection in batch: %s", norm.external_contact_id)
                    summary.duplicates_skipped += 1
                    continue
                seen_external_ids.add(norm.external_contact_id)

            if dry_run:
                # In dry-run mode, simulate insert
                summary.contacts_inserted += 1
                continue

            # Persist / Upsert in bounded SQLite transaction
            try:
                with get_db_session(engine=self.engine) as session:
                    contact, is_new = self.upsert_contact(session, norm)
                    if is_new:
                        summary.contacts_inserted += 1
                    else:
                        summary.contacts_updated += 1

                    # Prepare for Excel update
                    persisted_contacts_for_excel.append(
                        {
                            "Contact ID": str(contact.id),
                            "Contact Name": contact.name,
                            "Profile URL": contact.profile_url or "",
                            "Eligibility Status": contact.eligibility_status,
                        }
                    )
            except Exception as exc:
                err_msg = f"Failed to persist contact '{norm.name}': {exc}"
                logger.error(err_msg)
                summary.errors.append(err_msg)

        # 3. Synchronize contacts.xlsx reporting sheet
        if not dry_run and persisted_contacts_for_excel:
            for c_dict in persisted_contacts_for_excel:
                try:
                    update_contact_status(
                        c_dict,
                        file_path=self.config.contacts_workbook_path,
                    )
                except ExcelError as exc:
                    summary.excel_sync_success = False
                    summary.excel_sync_error = str(exc)
                    logger.warning(
                        "Excel sync warning for contact '%s' (DB record preserved): %s",
                        c_dict.get("Contact ID"),
                        exc,
                    )

        # 4. Count eligible contacts currently in database
        try:
            with get_db_session(engine=self.engine) as session:
                sender_svc = SenderService(config=self.config, adapter=self.adapter, engine=self.engine)
                eligible_contacts = sender_svc.get_eligible_contacts(session)
                summary.eligible_contacts = len(eligible_contacts)
        except Exception as exc:
            logger.warning("Could not count eligible contacts: %s", exc)

        # 5. Optional Initial Sender execution
        if send_messages:
            logger.info("Executing integrated Initial Sender outreach (dry_run=%s)", dry_run)
            sender_svc = SenderService(config=self.config, adapter=self.adapter, engine=self.engine)
            sender_summary: SenderRunSummary = sender_svc.run(
                limit=sender_limit,
                dry_run=dry_run,
            )
            summary.messages_attempted = sender_summary.processed_count
            summary.messages_confirmed_sent = sender_summary.sent_count
            summary.messages_failed = sender_summary.failed_count
            summary.messages_unknown = sender_summary.unknown_count
            if sender_summary.errors:
                summary.errors.extend(sender_summary.errors)

        summary.completed_at = _utc_now()
        summary.overall_status = "completed" if not summary.errors else "completed_with_warnings"

        logger.info(
            "Connection run '%s' finished: status=%s, fetched=%d, inserted=%d, updated=%d, skipped=%d, sent=%d",
            run_id,
            summary.overall_status,
            summary.records_fetched,
            summary.contacts_inserted,
            summary.contacts_updated,
            summary.duplicates_skipped,
            summary.messages_confirmed_sent,
        )
        return summary

