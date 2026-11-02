"""Conversation history collector service.

Coordinates retrieval of conversation threads, message normalization, chronological ordering,
contact resolution, deduplication, SQLite persistence, and Excel synchronization.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from config import AppConfig, CONFIG
from conversation.conversation_exceptions import (
    ConversationError,
    ConversationPersistenceError,
    ConversationSourceError,
    MessageValidationError,
)
from conversation.conversation_normalizer import (
    NormalizedMessage,
    normalize_message_record,
)
from conversation.conversation_resolver import ConversationResolver
from conversation.conversation_source import ConversationSource
from conversation.mock_conversation_source import MockConversationSource
from database import get_db_session, get_engine
from excel_manager import (
    ExcelError,
    append_conversation_messages,
    append_scraped_replies,
    rebuild_scraped_replies_workbook,
)
from models import Contact, ConversationMessage, Reply

logger = logging.getLogger("linkedin_automation.conversation.service")


def _utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class ConversationRunSummary:
    """Structured execution summary of a conversation history collection run."""

    collection_run_id: str
    source_name: str
    conversations_fetched: int = 0
    messages_fetched: int = 0
    messages_validated: int = 0
    incoming_messages: int = 0
    outgoing_messages: int = 0
    new_messages_persisted: int = 0
    duplicates_skipped: int = 0
    records_needing_review: int = 0
    records_failed: int = 0
    excel_export_success: bool = True
    excel_export_error: Optional[str] = None
    completed_at: datetime = field(default_factory=_utc_now)
    overall_status: str = "completed"
    dry_run: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.collection_run_id

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "live"

    @property
    def conversations_inspected(self) -> int:
        return self.conversations_fetched

    @property
    def messages_persisted(self) -> int:
        return self.new_messages_persisted

    @property
    def incoming_replies_synced(self) -> int:
        return self.incoming_messages

    @property
    def excel_sync_success(self) -> bool:
        return self.excel_export_success

    @property
    def excel_sync_error(self) -> Optional[str]:
        return self.excel_export_error

    def to_dict(self) -> Dict[str, Any]:
        """Convert summary to dictionary representation."""
        return {
            "collection_run_id": self.collection_run_id,
            "source_name": self.source_name,
            "conversations_fetched": self.conversations_fetched,
            "messages_fetched": self.messages_fetched,
            "messages_validated": self.messages_validated,
            "incoming_messages": self.incoming_messages,
            "outgoing_messages": self.outgoing_messages,
            "new_messages_persisted": self.new_messages_persisted,
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


class ConversationService:
    """Coordinates conversation collection from a source into SQLite and scraped_replies.xlsx."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        source: Optional[ConversationSource] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        """Initialize ConversationService."""
        self.config = config or CONFIG
        self.engine = engine or get_engine(self.config)
        self.source = source or MockConversationSource()
        self.resolver = ConversationResolver()

    def is_duplicate_message(
        self,
        session: Session,
        norm: NormalizedMessage,
        seen_in_batch: Set[str],
    ) -> bool:
        """Check whether a message is already present in this batch or in SQLite."""
        # Check by external_message_id
        if norm.external_message_id:
            if norm.external_message_id in seen_in_batch:
                return True

            existing = session.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.external_message_id == norm.external_message_id
                )
            ).first()
            if existing is not None:
                return True

        # Fallback deduplication for records without external ID
        if norm.contact_id and norm.message_text:
            existing_fb = session.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.contact_id == norm.contact_id,
                    ConversationMessage.message_text == norm.message_text,
                    ConversationMessage.message_timestamp == norm.message_timestamp,
                    ConversationMessage.message_direction == norm.message_direction,
                )
            ).first()
            if existing_fb is not None:
                return True

        return False

    def run(
        self,
        limit: Optional[int] = None,
        conversation_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> ConversationRunSummary:
        """Execute conversation history collection workflow."""
        run_id = f"conv_run_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}"
        summary = ConversationRunSummary(
            collection_run_id=run_id,
            source_name=self.source.source_name,
            dry_run=dry_run,
        )

        logger.info(
            "Starting conversation collection run '%s' (source='%s', limit=%s, conv_id=%s, dry_run=%s)",
            run_id,
            self.source.source_name,
            limit,
            conversation_id,
            dry_run,
        )

        # 1. Fetch conversations from source
        try:
            if conversation_id:
                # Fetch messages for specific conversation
                raw_messages = self.source.fetch_messages(conversation_id)
                conversations = [
                    {
                        "conversation_id": conversation_id,
                        "messages": raw_messages,
                    }
                ]
            else:
                conversations = self.source.fetch_all_conversations(limit=limit)
        except Exception as exc:
            err_msg = f"Failed to fetch conversations from source '{self.source.source_name}': {exc}"
            logger.error(err_msg)
            summary.overall_status = "failed"
            summary.errors.append(err_msg)
            summary.completed_at = _utc_now()
            return summary

        summary.conversations_fetched = len(conversations)
        logger.info("Fetched %d conversation thread(s) from source.", len(conversations))

        if not conversations:
            logger.info("Empty conversation inbox received; run complete.")
            summary.completed_at = _utc_now()
            return summary

        seen_in_batch: Set[str] = set()
        incoming_replies_for_excel: List[Dict[str, Any]] = []
        conversation_messages_for_excel: List[Dict[str, Any]] = []

        # 2. Process each conversation
        for conv in conversations:
            conv_id = str(conv.get("conversation_id") or conv.get("external_conversation_id") or "")
            ext_contact_id = conv.get("external_contact_id")
            contact_name = conv.get("contact_name")
            messages_list = conv.get("messages", [])

            # Resolve contact for thread
            with get_db_session(engine=self.engine) as session:
                contact, resolution_status = self.resolver.resolve_contact(
                    session=session,
                    external_contact_id=ext_contact_id,
                    participant_name=contact_name,
                    conversation_id=conv_id,
                )
                resolved_contact_id = contact.id if contact else None
                resolved_contact_name = contact.name if contact else (contact_name or "")

            # Sort messages chronologically by timestamp (Scenario 14)
            def _sort_key(m: Any) -> datetime:
                if isinstance(m, dict):
                    ts = m.get("message_timestamp") or m.get("timestamp") or m.get("created_at")
                    from collector.reply_normalizer import parse_timestamp
                    parsed = parse_timestamp(ts)
                    if parsed:
                        return parsed
                return datetime.min.replace(tzinfo=timezone.utc)

            try:
                sorted_messages = sorted(messages_list, key=_sort_key)
            except Exception:
                sorted_messages = messages_list

            for raw_msg in sorted_messages:
                summary.messages_fetched += 1

                # Step A: Validate and normalize
                try:
                    norm = normalize_message_record(
                        raw=raw_msg,
                        conversation_id=conv_id,
                        contact_id=resolved_contact_id,
                        external_contact_id=ext_contact_id,
                    )
                    summary.messages_validated += 1
                except MessageValidationError as exc:
                    logger.warning("Message validation failure in conv '%s': %s", conv_id, exc)
                    summary.records_failed += 1
                    summary.errors.append(str(exc))
                    continue

                # Count directions
                if norm.message_direction == "incoming":
                    summary.incoming_messages += 1
                elif norm.message_direction == "outgoing":
                    summary.outgoing_messages += 1

                # Step B: Check duplicate
                try:
                    with get_db_session(engine=self.engine) as session:
                        if self.is_duplicate_message(session, norm, seen_in_batch):
                            summary.duplicates_skipped += 1
                            logger.debug("Skipping duplicate message: %s", norm.external_message_id)
                            continue

                        # Determine processing status
                        msg_status = norm.processing_status
                        if resolution_status == "needs_review" or norm.message_direction == "unknown":
                            msg_status = "needs_review"
                            summary.records_needing_review += 1

                        if dry_run:
                            summary.new_messages_persisted += 1
                            if norm.external_message_id:
                                seen_in_batch.add(norm.external_message_id)
                            continue

                        # Step C: Persist in SQLite conversation_messages
                        conv_msg_entity = ConversationMessage(
                            external_message_id=norm.external_message_id,
                            external_conversation_id=norm.external_conversation_id,
                            external_contact_id=norm.external_contact_id,
                            contact_id=resolved_contact_id,
                            sender_identifier=norm.sender_identifier,
                            sender_name=norm.sender_name or resolved_contact_name,
                            message_text=norm.message_text,
                            message_timestamp=norm.message_timestamp,
                            collected_at=norm.collected_at,
                            message_direction=norm.message_direction,
                            processing_status=msg_status,
                        )
                        session.add(conv_msg_entity)
                        session.flush()

                        # Step D: If incoming reply, also sync to Reply table
                        if norm.message_direction == "incoming":
                            existing_reply = None
                            if norm.external_message_id:
                                existing_reply = session.scalars(
                                    select(Reply).where(Reply.external_reply_id == norm.external_message_id)
                                ).first()

                            if existing_reply is None:
                                reply_entity = Reply(
                                    contact_id=resolved_contact_id,
                                    external_reply_id=norm.external_message_id,
                                    conversation_id=norm.external_conversation_id,
                                    reply_text=norm.message_text,
                                    reply_timestamp=norm.message_timestamp,
                                    collected_at=norm.collected_at,
                                    processing_status=msg_status,
                                )
                                session.add(reply_entity)
                                session.flush()

                    summary.new_messages_persisted += 1
                    if norm.external_message_id:
                        seen_in_batch.add(norm.external_message_id)

                    # Prepare for Excel sync
                    if norm.message_direction == "incoming":
                        incoming_replies_for_excel.append({
                            "Contact ID": str(resolved_contact_id) if resolved_contact_id is not None else "",
                            "Contact Name": resolved_contact_name,
                            "Conversation ID": norm.external_conversation_id or "",
                            "Reply ID": norm.external_message_id or f"rep_{conv_msg_entity.id}",
                            "Reply Text": norm.message_text,
                            "Reply Timestamp": norm.message_timestamp,
                            "Collection Timestamp": norm.collected_at,
                            "Processing Status": msg_status,
                        })

                    conversation_messages_for_excel.append({
                        "Contact ID": str(resolved_contact_id) if resolved_contact_id is not None else "",
                        "Contact Name": resolved_contact_name,
                        "Conversation ID": norm.external_conversation_id or "",
                        "Message ID": norm.external_message_id or f"msg_{conv_msg_entity.id}",
                        "Sender Identifier": norm.sender_identifier or "",
                        "Sender Name": norm.sender_name or resolved_contact_name,
                        "Message Direction": norm.message_direction,
                        "Message Text": norm.message_text,
                        "Message Timestamp": norm.message_timestamp,
                        "Collection Timestamp": norm.collected_at,
                        "Processing Status": msg_status,
                    })

                except Exception as exc:
                    err_msg = f"Failed to persist message '{norm.external_message_id}': {exc}"
                    logger.error(err_msg)
                    summary.records_failed += 1
                    summary.errors.append(err_msg)

        # 3. Synchronize scraped_replies.xlsx
        if not dry_run and (incoming_replies_for_excel or conversation_messages_for_excel):
            try:
                if incoming_replies_for_excel:
                    append_scraped_replies(
                        incoming_replies_for_excel,
                        file_path=self.config.scraped_replies_workbook_path,
                    )
                if conversation_messages_for_excel:
                    append_conversation_messages(
                        conversation_messages_for_excel,
                        file_path=self.config.scraped_replies_workbook_path,
                    )
                summary.excel_export_success = True
            except ExcelError as exc:
                summary.excel_export_success = False
                summary.excel_export_error = str(exc)
                logger.error("Excel export failure (SQLite remains authoritative): %s", exc)

        summary.completed_at = _utc_now()
        if not summary.excel_export_success:
            summary.overall_status = "partial"
        elif summary.records_failed > 0:
            summary.overall_status = "completed_with_errors"
        else:
            summary.overall_status = "completed"

        logger.info(
            "Conversation run '%s' finished: status=%s, convs=%d, msgs=%d, incoming=%d, outgoing=%d, persisted=%d, skipped=%d, review=%d",
            run_id,
            summary.overall_status,
            summary.conversations_fetched,
            summary.messages_fetched,
            summary.incoming_messages,
            summary.outgoing_messages,
            summary.new_messages_persisted,
            summary.duplicates_skipped,
            summary.records_needing_review,
        )
        return summary

    def rebuild_workbook(self, file_path: Optional[Path] = None) -> int:
        """Rebuild scraped_replies.xlsx directly from persisted SQLite database."""
        return rebuild_scraped_replies_workbook(
            file_path=file_path,
            config=self.config,
            engine=self.engine,
        )
