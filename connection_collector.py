"""Command-line interface and entry point for Entry Point 1: Connection Collection and Initial Sender.

Retrieves connections, upserts contacts into SQLite, syncs contacts.xlsx,
and optionally triggers the initial message sender workflow.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from config import AppConfig, load_config, setup_logging
from connections.connection_exceptions import ConnectionCollectorError
from connections.connection_service import ConnectionRunSummary, ConnectionService
from connections.connection_source import ConnectionSource
from connections.mock_connection_source import MockConnectionSource
from database import init_db
from excel_manager import initialize_workbooks


def run_connection_collector(
    config: Optional[AppConfig] = None,
    source_name: str = "mock",
    limit: Optional[int] = None,
    dry_run: bool = False,
    send_messages: bool = False,
    sender_limit: Optional[int] = None,
    custom_source: Optional[ConnectionSource] = None,
) -> ConnectionRunSummary:
    """Execute connection collection and optional outreach workflow.

    Args:
        config: Application configuration. Defaults to loaded project config.
        source_name: Connection source identifier ('mock' is default).
        limit: Maximum connections to fetch.
        dry_run: Simulate workflow without modifying database or Excel.
        send_messages: If True, execute initial sender outreach after collection.
        sender_limit: Maximum initial messages to send if send_messages is True.
        custom_source: Pre-instantiated ConnectionSource object.

    Returns:
        ConnectionRunSummary.
    """
    cfg = config or load_config()
    setup_logging(cfg)

    # Ensure DB tables and Excel workbooks exist
    init_db(config=cfg)
    initialize_workbooks(cfg)

    source: ConnectionSource
    if custom_source is not None:
        source = custom_source
    else:
        if source_name.lower() == "mock":
            source = MockConnectionSource()
        else:
            raise ConnectionCollectorError(
                f"Unsupported connection source '{source_name}'. "
                f"In Phase 4, only the 'mock' source is supported until an authorized live integration is verified."
            )

    service = ConnectionService(config=cfg, source=source)
    return service.run(
        limit=limit,
        dry_run=dry_run,
        send_messages=send_messages,
        sender_limit=sender_limit,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI dispatcher for connection_collector.py."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Messaging Automation - Entry Point 1: Connection Collection & Initial Sender",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source",
        type=str,
        default="mock",
        choices=["mock"],
        help="Connection source provider ('mock' is default).",
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
        help="Maximum number of connections to collect.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        default=False,
        help="Explicitly trigger initial message outreach for eligible contacts after collection.",
    )
    parser.add_argument(
        "--sender-limit",
        type=int,
        default=None,
        help="Maximum number of initial messages to send when --send is enabled.",
    )

    args = parser.parse_args(argv)

    try:
        summary = run_connection_collector(
            source_name=args.source,
            limit=args.limit,
            dry_run=args.dry_run,
            send_messages=args.send,
            sender_limit=args.sender_limit,
        )

        print("\n=== Connection Collector Run Summary ===")
        print(f"Run ID:                 {summary.run_id}")
        print(f"Source:                 {summary.source_name}")
        print(f"Mode:                   {summary.mode.upper()}")
        print(f"Overall Status:         {summary.overall_status}")
        print(f"Records Fetched:        {summary.records_fetched}")
        print(f"Records Validated:      {summary.records_validated}")
        print(f"Contacts Inserted:      {summary.contacts_inserted}")
        print(f"Contacts Updated:       {summary.contacts_updated}")
        print(f"Duplicates Skipped:     {summary.duplicates_skipped}")
        print(f"Needs Review:           {summary.records_needing_review}")
        print(f"Eligible For Outreach:  {summary.eligible_contacts}")

        if args.send:
            print("\n--- Initial Sender Outreach ---")
            print(f"Messages Attempted:     {summary.messages_attempted}")
            print(f"Messages Confirmed Sent:{summary.messages_confirmed_sent}")
            print(f"Messages Failed:        {summary.messages_failed}")
            print(f"Messages Unknown:       {summary.messages_unknown}")

        print(f"\nExcel Sync Status:      {'SUCCESS' if summary.excel_sync_success else 'FAILED'}")
        if summary.excel_sync_error:
            print(f"Excel Sync Error:       {summary.excel_sync_error}")

        if summary.errors:
            print("\nErrors / Warnings:")
            for err in summary.errors:
                print(f"  - {err}")

        return 0 if summary.overall_status != "failed" else 1

    except Exception as exc:
        sys.stderr.write(f"Fatal connection collector error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

