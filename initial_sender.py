"""Command-line entry point and execution wrapper for the initial message sender.

Loads project configuration, sets up logging, initializes the SenderService,
and executes outreach in dry-run or mock mode.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from config import AppConfig, load_config, setup_logging
from database import init_db
from excel_manager import initialize_workbooks
from sender.messaging_adapter import MessagingAdapter
from sender.mock_messaging_adapter import MockMessagingAdapter
from sender.sender_exceptions import SenderError
from sender.sender_service import SenderRunSummary, SenderService


def run_initial_sender(
    config: Optional[AppConfig] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    adapter_name: Optional[str] = None,
    template_key: Optional[str] = None,
    custom_adapter: Optional[MessagingAdapter] = None,
) -> SenderRunSummary:
    """Execute the initial sender workflow programmatically or from CLI.

    Args:
        config: Application configuration. Defaults to loaded project config.
        limit: Maximum number of eligible contacts to process in this run.
        dry_run: When True, simulates workflow without creating DB records or calling adapter.
        adapter_name: Adapter identifier ("mock").
        template_key: Template key for outreach (defaults to config setting).
        custom_adapter: Optional pre-configured MessagingAdapter instance.

    Returns:
        SenderRunSummary containing counts and outcome details.
    """
    cfg = config or load_config()
    logger = setup_logging(cfg)

    # Ensure DB and workbooks exist
    init_db(config=cfg)
    initialize_workbooks(cfg)

    # Determine adapter
    adapter: MessagingAdapter
    if custom_adapter is not None:
        adapter = custom_adapter
    else:
        chosen_adapter = (adapter_name or cfg.messaging_adapter).lower()
        if chosen_adapter == "mock":
            adapter = MockMessagingAdapter()
        else:
            raise SenderError(
                f"Unsupported messaging adapter '{chosen_adapter}'. "
                f"In Phase 2, only the 'mock' adapter is supported."
            )

    service = SenderService(config=cfg, adapter=adapter)
    summary = service.run(
        limit=limit,
        dry_run=dry_run,
        template_key=template_key,
    )

    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI argument parser and dispatcher for initial_sender.py."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Messaging Automation - Initial Message Sender (Phase 2)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate initial message workflow without persisting records or sending messages.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of eligible contacts to process in this run.",
    )
    parser.add_argument(
        "--adapter",
        type=str,
        default="mock",
        choices=["mock"],
        help="Messaging adapter to use (mock is the default).",
    )
    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="Template key to use for initial messages (defaults to config setting).",
    )

    args = parser.parse_args(argv)

    try:
        summary = run_initial_sender(
            limit=args.limit,
            dry_run=args.dry_run,
            adapter_name=args.adapter,
            template_key=args.template,
        )

        print("\n=== Initial Sender Run Summary ===")
        print(f"Mode: {'DRY-RUN' if summary.dry_run else 'ACTIVE (Mock Adapter)'}")
        print(f"Total Eligible Found: {summary.total_eligible_found}")
        print(f"Processed:            {summary.processed_count}")
        print(f"Sent:                 {summary.sent_count}")
        print(f"Failed:               {summary.failed_count}")
        print(f"Unknown:              {summary.unknown_count}")
        print(f"Skipped:              {summary.skipped_count}")
        print(f"Excel Errors:         {summary.excel_errors_count}")

        if summary.errors:
            print("\nErrors encountered:")
            for err in summary.errors:
                print(f"  - {err}")

        return 0

    except Exception as exc:
        sys.stderr.write(f"Fatal sender error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

