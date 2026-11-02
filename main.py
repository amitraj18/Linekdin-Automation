"""Main CLI entry point for LinkedIn messaging automation.

Initializes configuration, database schema, Excel workbooks, and templates safely.
Never connects to LinkedIn or sends messages in Phase 1.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from config import AppConfig, ConfigurationError, load_config, setup_logging
from database import init_db
from excel_manager import ExcelError, initialize_workbooks
from template_manager import TemplateError, load_templates


def run_initialization(config: Optional[AppConfig] = None) -> int:
    """Execute Phase 1 initialization workflow.

    1. Load and validate configuration.
    2. Set up structured logging.
    3. Initialize database tables.
    4. Initialize and validate the three Excel workbooks.
    5. Load and validate message templates.
    6. Output concise initialization summary.
    """
    try:
        cfg = config or load_config()
        logger = setup_logging(cfg)

        logger.info("==================================================")
        logger.info("Initializing LinkedIn Automation - Phase 1 Foundation")
        logger.info("==================================================")
        logger.info("Environment: %s", cfg.app_env)
        logger.info("Project Root: %s", cfg.project_root)
        logger.info("Database URL: %s", cfg.database_url)
        logger.info("Contacts Workbook: %s", cfg.contacts_workbook_path)
        logger.info("Scraped Replies Workbook: %s", cfg.scraped_replies_workbook_path)
        logger.info("Cycle History Workbook: %s", cfg.automation_cycles_workbook_path)
        logger.info("Templates File: %s", cfg.templates_file_path)

        # 1. Database schema initialization
        init_db(config=cfg)
        logger.info("✓ Database schema verified and initialized.")

        # 2. Excel workbooks initialization
        initialize_workbooks(cfg)
        logger.info("✓ All 3 Excel workbooks created and verified with valid headers.")

        # 3. Template validation
        templates = load_templates(cfg.templates_file_path)
        logger.info(
            "✓ Loaded and validated %d message templates: %s",
            len(templates),
            ", ".join(sorted(templates.keys())),
        )

        logger.info("==================================================")
        logger.info("Phase 1 initialization completed successfully.")
        logger.info("==================================================")
        return 0

    except (ConfigurationError, ExcelError, TemplateError) as exc:
        sys.stderr.write(f"Initialization Error: {exc}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"Unexpected Error during initialization: {exc}\n")
        return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI argument parser and dispatcher."""
    parser = argparse.ArgumentParser(
        description="LinkedIn Messaging Automation System - Phase 1 Foundation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize database tables, Excel workbooks, and validate templates.",
    )

    args = parser.parse_args(argv)

    # In Phase 1, both running with --init or running with default invokes the initialization safely
    return run_initialization()


if __name__ == "__main__":
    sys.exit(main())

