"""Command-line interface and entry point for Entry Point 2: Messaging Inbox and Conversation-History Collection.

Retrieves conversation history, normalizes and validates messages, resolves contacts,
persists full history to SQLite conversation_messages, syncs incoming replies to replies,
and synchronizes scraped_replies.xlsx (both ScrapedReplies and ConversationHistory sheets).
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from config import AppConfig, load_config, setup_logging
from conversation.conversation_exceptions import ConversationError
from conversation.conversation_service import ConversationRunSummary, ConversationService
from conversation.conversation_source import ConversationSource
from conversation.mock_conversation_source import MockConversationSource
from database import init_db
from excel_manager import initialize_workbooks, rebuild_scraped_replies_workbook


def run_conversation_collector(
    config: Optional[AppConfig] = None,
    source_name: str = "mock",
    limit: Optional[int] = None,
    conversation_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_workbook: bool = False,
    custom_source: Optional[ConversationSource] = None,
) -> ConversationRunSummary:
    """Execute conversation history collection workflow.

    Args:
        config: Application configuration. Defaults to loaded project config.
        source_name: Conversation source identifier ('mock' is default).
        limit: Maximum number of conversations to fetch.
        conversation_id: Optional specific conversation ID filter.
        dry_run: Simulate workflow without modifying database or Excel.
        rebuild_workbook: Reconstruct scraped_replies.xlsx directly from SQLite.
        custom_source: Pre-instantiated ConversationSource object.

    Returns:
        ConversationRunSummary.
    """
    cfg = config or load_config()
    setup_logging(cfg)

    # Ensure DB tables and Excel workbooks exist
    init_db(config=cfg)
    initialize_workbooks(cfg)

    # Handle rebuild-workbook mode directly
    if rebuild_workbook:
        count = rebuild_scraped_replies_workbook(config=cfg)
        summary = ConversationRunSummary(
            collection_run_id="REBUILD-WORKBOOK",
            source_name="sqlite",
            overall_status="completed",
            excel_export_success=True,
        )
        return summary

    source: ConversationSource
    if custom_source is not None:
        source = custom_source
    else:
        if source_name.lower() == "mock":
            source = MockConversationSource()
        else:
            raise ConversationError(
                f"Unsupported conversation source '{source_name}'. "
                f"In Phase 5, only the 'mock' source is supported until an authorized live messaging integration is verified."
            )

    service = ConversationService(config=cfg, source=source)
    return service.run(
        limit=limit,
        conversation_id=conversation_id,
        dry_run=dry_run,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI dispatcher for conversation_collector.py."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Messaging Automation - Entry Point 2: Inbox & Conversation-History Collection",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source",
        type=str,
        default="mock",
        choices=["mock"],
        help="Conversation source provider ('mock' is default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate collection without modifying SQLite or Excel.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of conversations to process.",
    )
    parser.add_argument(
        "--conversation-id",
        type=str,
        default=None,
        help="Filter collection to a single specific conversation ID.",
    )
    parser.add_argument(
        "--rebuild-workbook",
        action="store_true",
        default=False,
        help="Rebuild scraped_replies.xlsx workbook directly from SQLite conversation_messages and replies.",
    )

    args = parser.parse_args(argv)

    try:
        summary = run_conversation_collector(
            source_name=args.source,
            limit=args.limit,
            conversation_id=args.conversation_id,
            dry_run=args.dry_run,
            rebuild_workbook=args.rebuild_workbook,
        )

        print("\n=== Conversation Collector Run Summary ===")
        print(f"Run ID:                  {summary.run_id}")
        print(f"Source:                  {summary.source_name}")
        print(f"Mode:                    {summary.mode.upper()}")
        print(f"Overall Status:          {summary.overall_status}")
        print(f"Conversations Inspected: {summary.conversations_inspected}")
        print(f"Messages Fetched:        {summary.messages_fetched}")
        print(f"Messages Validated:      {summary.messages_validated}")
        print(f"Messages Persisted:      {summary.messages_persisted}")
        print(f"Duplicates Skipped:      {summary.duplicates_skipped}")
        print(f"Incoming Replies Synced: {summary.incoming_replies_synced}")
        print(f"Needs Review:            {summary.records_needing_review}")

        print(f"\nExcel Sync Status:       {'SUCCESS' if summary.excel_sync_success else 'FAILED'}")
        if summary.excel_sync_error:
            print(f"Excel Sync Error:        {summary.excel_sync_error}")

        if summary.errors:
            print("\nErrors / Warnings:")
            for err in summary.errors:
                print(f"  - {err}")

        return 0 if summary.overall_status.upper() in ("SUCCESS", "PARTIAL", "COMPLETED") else 1

    except Exception as exc:
        print(f"\n[FATAL ERROR] Conversation collection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
