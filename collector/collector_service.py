"""Reply collector service coordinating source retrieval, normalization,
contact resolution, deduplication, SQLite persistence, and Excel synchronization.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from collector.collector_exceptions import (
    CollectorError,
    ContactResolutionError,
    DeduplicationError,
    RecordValidationError,
    SourceError,
    WorkbookExportError,
)
from collector.mock_reply_source import MockReplySource
from collector.reply_normalizer import NormalizedReply, normalize_reply_record
from collector.reply_source import ReplySource
from config import AppConfig, CONFIG
from database import get_db_session, get_engine
from excel_manager import ExcelError, append_scraped_replies, rebuild_scraped_replies_workbook
from models import Contact, Reply

logger = logging.getLogger("linkedin_automation.collector.service")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class CollectionRunSummary:
    """Structured execution summary of a reply collection run."""

    collection_run_id: str
    source_name: str
    records_fetched: int = 0
    records_validated: int = 0
    new_replies_persisted: int = 0
    duplicates_skipped: int = 0
    records_needing_review: int = 0
    records_failed: int = 0
    excel_export_success: bool = True
    excel_export_error: Optional[str] = None
    completed_at: datetime = field(default_factory=_utc_now)
    overall_status: str = "completed"
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary representation."""
        return {
            "collection_run_id": self.collection_run_id,
            "source_name": self.source_name,
            "records_fetched": self.records_fetched,
            "records_validated": self.records_validated,
            "new_replies_persisted": self.new_replies_persisted,
            "duplicates_skipped": self.duplicates_skipped,
            "records_needing_review": self.records_needing_review,
            "records_failed": self.records_failed,
            "excel_export_success": self.excel_export_success,
            "excel_export_error": self.excel_export_error,
            "completed_at": self.completed_at.isoformat(),
            "overall_status": self.overall_status,
            "dry_run": self.dry_run,
            "errors": list(self.errors),
        }


class CollectorService:
    """Coordinates reply collection from a source into SQLite and scraped_replies.xlsx."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        source: Optional[ReplySource] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        """Initialize CollectorService."""
        self.config = config or CONFIG
        self.engine = engine or get_engine(self.config)
        self.source = source or MockReplySource()

    def resolve_contact(
        self,
        session: Session,
        normalized: NormalizedReply,
    ) -> Tuple[Optional[Contact], str]:
        """Attempt to resolve a reply to a known database Contact.

        Returns (contact, final_processing_status).
        If contact cannot be resolved confidently, returns (None, 'needs_review').
        """
        # 1. Direct contact_id resolution
        if normalized.contact_id is not None:
            c = session.get(Contact, normalized.contact_id)
            if c:
                return c, normalized.processing_status

        # 2. External contact ID resolution
        if normalized.external_contact_id:
            c = session.scalars(
                select(Contact).where(Contact.external_contact_id == normalized.external_contact_id)
            ).first()
            if c:
                return c, normalized.processing_status

        # 3. Match by name only if unique single match
        if normalized.contact_name:
            candidates = session.scalars(
                select(Contact).where(Contact.name == normalized.contact_name)
            ).all()
            if len(candidates) == 1:
                return candidates[0], normalized.processing_status
            elif len(candidates) > 1:
                logger.warning(
                    "Ambiguous contact match for name '%s': found %d contacts. Flagging for review.",
                    normalized.contact_name,
                    len(candidates),
                )
                return None, "needs_review"

        # Cannot resolve contact with confidence
        return None, "needs_review"

    def is_duplicate(
        self,
        session: Session,
        normalized: NormalizedReply,
        seen_in_batch: Set[str],
    ) -> bool:
        """Check whether a reply is a duplicate within the current batch or against SQLite."""
        # Check within current batch
        if normalized.external_reply_id:
            if normalized.external_reply_id in seen_in_batch:
                return True

            # Check database for external_reply_id
            existing = session.scalars(
                select(Reply).where(Reply.external_reply_id == normalized.external_reply_id)
            ).first()
            if existing:
                return True

        # Fallback deduplication when external_reply_id is absent
        if not normalized.external_reply_id and normalized.contact_id:
            existing = session.scalars(
                select(Reply).where(
                    Reply.contact_id == normalized.contact_id,
                    Reply.reply_text == normalized.reply_text,
                    Reply.reply_timestamp == normalized.reply_timestamp,
                )
            ).first()
            if existing:
                return True

        return False

    def run(
        self,
        limit: Optional[int] = None,
        dry_run: bool = False,
    ) -> CollectionRunSummary:
        """Execute the reply collection pipeline."""
        run_id = f"col_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
        summary = CollectionRunSummary(
            collection_run_id=run_id,
            source_name=self.source.source_name,
            dry_run=dry_run,
        )

        logger.info(
            "Starting reply collection run '%s' (source='%s', limit=%s, dry_run=%s)",
            run_id,
            self.source.source_name,
            limit,
            dry_run,
        )

        # 1. Fetch raw reply records from source
        try:
            raw_records = self.source.fetch_replies(limit=limit)
        except Exception as exc:
            err_msg = f"Failed to fetch replies from source '{self.source.source_name}': {exc}"
            logger.error(err_msg)
            summary.overall_status = "failed"
            summary.errors.append(err_msg)
            summary.completed_at = _utc_now()
            return summary

        summary.records_fetched = len(raw_records)
        logger.info("Fetched %d raw reply record(s) from source.", len(raw_records))

        if not raw_records:
            logger.info("Empty batch received; collection run complete.")
            summary.completed_at = _utc_now()
            return summary

        # Track external IDs seen in this run to catch in-batch duplicates
        seen_in_batch: Set[str] = set()
        persisted_records_for_excel: List[Dict[str, Any]] = []

        # 2. Process records individually in bounded transactions
        for raw_item in raw_records:
            # Step A: Validate and normalize
            try:
                norm = normalize_reply_record(raw_item)
                summary.records_validated += 1
            except RecordValidationError as exc:
                logger.warning("Record validation failure: %s", exc)
                summary.records_failed += 1
                summary.errors.append(str(exc))
                continue

            # Step B: Check duplicate
            try:
                with get_db_session(engine=self.engine) as session:
                    if self.is_duplicate(session, norm, seen_in_batch):
                        summary.duplicates_skipped += 1
                        logger.debug(
                            "Skipping duplicate reply: %s",
                            norm.external_reply_id or f"text_len_{len(norm.reply_text)}",
                        )
                        continue

                    # Step C: Resolve contact
                    contact, status = self.resolve_contact(session, norm)
                    if status == "needs_review":
                        summary.records_needing_review += 1

                    resolved_contact_id = contact.id if contact else norm.contact_id
                    resolved_contact_name = contact.name if contact else (norm.contact_name or "")

                    if dry_run:
                        # In dry-run mode, simulate persistence
                        summary.new_replies_persisted += 1
                        if norm.external_reply_id:
                            seen_in_batch.add(norm.external_reply_id)
                        continue

                    # Step D: Persist new reply in SQLite
                    reply_entity = Reply(
                        contact_id=resolved_contact_id,
                        external_reply_id=norm.external_reply_id,
                        conversation_id=norm.external_conversation_id,
                        reply_text=norm.reply_text,
                        reply_timestamp=norm.reply_timestamp,
                        collected_at=norm.collected_at,
                        processing_status=status,
                    )
                    session.add(reply_entity)
                    session.flush()
                    entity_id = reply_entity.id

                summary.new_replies_persisted += 1
                if norm.external_reply_id:
                    seen_in_batch.add(norm.external_reply_id)

                # Prepare row for Excel export
                persisted_records_for_excel.append(
                    {
                        "Contact ID": str(resolved_contact_id) if resolved_contact_id is not None else "",
                        "Contact Name": resolved_contact_name,
                        "Conversation ID": norm.external_conversation_id or "",
                        "Reply ID": norm.external_reply_id or f"rep_{entity_id}",
                        "Reply Text": norm.reply_text,
                        "Reply Timestamp": norm.reply_timestamp,
                        "Collection Timestamp": norm.collected_at,
                        "Processing Status": status,
                    }
                )

            except Exception as exc:
                err_msg = f"Failed to persist reply '{norm.external_reply_id}': {exc}"
                logger.error(err_msg)
                summary.records_failed += 1
                summary.errors.append(err_msg)

        # Step E: Export newly persisted records to scraped_replies.xlsx
        if not dry_run and persisted_records_for_excel:
            try:
                exported_count = append_scraped_replies(
                    persisted_records_for_excel,
                    file_path=self.config.scraped_replies_workbook_path,
                )
                logger.info(
                    "Exported %d reply row(s) to '%s'.",
                    exported_count,
                    self.config.scraped_replies_workbook_path.name,
                )
                summary.excel_export_success = True
            except ExcelError as exc:
                summary.excel_export_success = False
                summary.excel_export_error = str(exc)
                logger.error(
                    "Failed to export persisted replies to Excel (SQLite remains intact): %s",
                    exc,
                )

        summary.completed_at = _utc_now()
        if summary.records_failed > 0:
            summary.overall_status = "completed_with_errors"
        else:
            summary.overall_status = "completed"

        logger.info(
            "Collection run '%s' finished: status=%s, fetched=%d, persisted=%d, skipped=%d, review=%d, failed=%d",
            run_id,
            summary.overall_status,
            summary.records_fetched,
            summary.new_replies_persisted,
            summary.duplicates_skipped,
            summary.records_needing_review,
            summary.records_failed,
        )
        return summary

    def rebuild_workbook(self, file_path: Optional[Path] = None) -> int:
        """Reconstruct scraped_replies.xlsx directly from persisted SQLite reply records."""
        return rebuild_scraped_replies_workbook(
            file_path=file_path,
            config=self.config,
            engine=self.engine,
        )

