"""Command-line interface and entry point for the Reply Collector.

Supports collecting replies from configurable sources (mock default), dry-run execution,
and standalone Excel workbook reconstruction from authoritative SQLite storage.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from collector.collector_exceptions import CollectorError
from collector.collector_service import CollectionRunSummary, CollectorService
from collector.mock_reply_source import MockReplySource
from collector.reply_source import ReplySource
from config import AppConfig, load_config, setup_logging
from database import init_db
from excel_manager import initialize_workbooks


def run_collector(
    config: Optional[AppConfig] = None,
    source_name: str = "mock",
    limit: Optional[int] = None,
    dry_run: bool = False,
    custom_source: Optional[ReplySource] = None,
) -> CollectionRunSummary:
    """Execute reply collection workflow programmatically or from CLI.

    Args:
        config: Application configuration. Defaults to loaded project config.
        source_name: Name of the reply source (default: 'mock').
        limit: Maximum number of records to retrieve.
        dry_run: When True, simulates collection without DB or Excel writes.
        custom_source: Pre-instantiated ReplySource object.

    Returns:
        CollectionRunSummary.
    """
    cfg = config or load_config()
    setup_logging(cfg)

    # Ensure DB tables and Excel workbooks exist
    init_db(config=cfg)
    initialize_workbooks(cfg)

    source: ReplySource
    if custom_source is not None:
        source = custom_source
    else:
        if source_name.lower() == "mock":
            source = MockReplySource()
        else:
            raise CollectorError(
                f"Unsupported reply source '{source_name}'. "
                f"In Phase 3, only the 'mock' source is supported."
            )

    service = CollectorService(config=cfg, source=source)
    return service.run(limit=limit, dry_run=dry_run)


def run_rebuild_workbook(config: Optional[AppConfig] = None) -> int:
    """Reconstruct scraped_replies.xlsx directly from persisted SQLite database."""
    cfg = config or load_config()
    setup_logging(cfg)
    init_db(config=cfg)

    service = CollectorService(config=cfg)
    return service.rebuild_workbook()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI dispatcher for reply_collector.py."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Messaging Automation - Reply Collector (Phase 3)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source",
        type=str,
        default="mock",
        choices=["mock"],
        help="Reply data source provider (mock is default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate collection and validation without modifying SQLite or Excel.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of replies to collect in this run.",
    )
    parser.add_argument(
        "--rebuild-workbook",
        action="store_true",
        default=False,
        help="Reconstruct scraped_replies.xlsx directly from persisted SQLite replies.",
    )

    args = parser.parse_args(argv)

    try:
        if args.rebuild_workbook:
            count = run_rebuild_workbook()
            print(f"\n[OK] Successfully rebuilt scraped_replies.xlsx with {count} reply records from SQLite.")
            return 0

        summary = run_collector(
            source_name=args.source,
            limit=args.limit,
            dry_run=args.dry_run,
        )

        print("\n=== Reply Collector Run Summary ===")
        print(f"Run ID:              {summary.collection_run_id}")
        print(f"Source:              {summary.source_name}")
        print(f"Mode:                {'DRY-RUN' if summary.dry_run else 'ACTIVE'}")
        print(f"Overall Status:      {summary.overall_status}")
        print(f"Records Fetched:     {summary.records_fetched}")
        print(f"Records Validated:   {summary.records_validated}")
        print(f"New Persisted:       {summary.new_replies_persisted}")
        print(f"Duplicates Skipped:  {summary.duplicates_skipped}")
        print(f"Needs Review:        {summary.records_needing_review}")
        print(f"Records Failed:      {summary.records_failed}")
        print(f"Excel Export Status: {'SUCCESS' if summary.excel_export_success else 'FAILED'}")

        if summary.excel_export_error:
            print(f"Excel Export Error:  {summary.excel_export_error}")

        if summary.errors:
            print("\nErrors / Warnings:")
            for err in summary.errors:
                print(f"  - {err}")

        return 0 if summary.overall_status != "failed" else 1

    except Exception as exc:
        sys.stderr.write(f"Fatal collector error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
