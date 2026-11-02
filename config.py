"""Configuration module for LinkedIn messaging automation.

Centralizes project directories, database paths, Excel workbook locations,
template paths, environment settings, and logging configuration.
All paths are resolved relative to the project root directory.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Project root is the directory containing this config.py file
PROJECT_ROOT = Path(__file__).resolve().parent

# Load .env file from project root if it exists; do not overwrite existing environment variables
ENV_FILE_PATH = PROJECT_ROOT / ".env"
if ENV_FILE_PATH.exists():
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)


class ConfigurationError(Exception):
    """Raised when application configuration is invalid or missing required values."""


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration container."""

    project_root: Path
    data_dir: Path
    logs_dir: Path
    database_path: Path
    database_url: str
    contacts_workbook_path: Path
    scraped_replies_workbook_path: Path
    automation_cycles_workbook_path: Path
    templates_file_path: Path
    log_level: str
    app_env: str
    log_file_path: Path
    initial_template_key: str = "initial_outreach"
    max_initial_messages_per_run: int = 10
    messaging_adapter: str = "mock"

    def ensure_directories(self) -> None:
        """Create required directories (data and logs) if they do not exist."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(f"Failed to create application directories: {exc}") from exc

    def validate(self) -> None:
        """Validate paths, log levels, and application environment settings."""
        valid_envs = {"development", "staging", "production", "test"}
        if self.app_env.lower() not in valid_envs:
            raise ConfigurationError(
                f"Invalid APP_ENV '{self.app_env}'. Expected one of: {', '.join(sorted(valid_envs))}"
            )

        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in valid_log_levels:
            raise ConfigurationError(
                f"Invalid LOG_LEVEL '{self.log_level}'. Expected one of: {', '.join(sorted(valid_log_levels))}"
            )

        # Validate that template file exists or parent directory exists
        if not self.templates_file_path.parent.exists():
            raise ConfigurationError(
                f"Templates directory does not exist: {self.templates_file_path.parent}"
            )

        # Ensure directory paths are directories if they exist
        if self.data_dir.exists() and not self.data_dir.is_dir():
            raise ConfigurationError(f"Data path exists but is not a directory: {self.data_dir}")

        if self.logs_dir.exists() and not self.logs_dir.is_dir():
            raise ConfigurationError(f"Logs path exists but is not a directory: {self.logs_dir}")

        if self.max_initial_messages_per_run < 0:
            raise ConfigurationError(
                f"max_initial_messages_per_run must be non-negative, got {self.max_initial_messages_per_run}"
            )

        valid_adapters = {"mock"}
        if self.messaging_adapter.lower() not in valid_adapters:
            raise ConfigurationError(
                f"Invalid MESSAGING_ADAPTER '{self.messaging_adapter}'. Expected one of: {', '.join(sorted(valid_adapters))}"
            )


def _resolve_path(raw_path: str, base_dir: Path) -> Path:
    """Resolve a raw path string relative to base_dir if not absolute."""
    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def load_config(
    root_dir: Optional[Path] = None,
    env_overrides: Optional[dict[str, str]] = None,
) -> AppConfig:
    """Load configuration from environment variables, defaulting to safe project settings."""
    base_root = (root_dir or PROJECT_ROOT).resolve()
    overrides = env_overrides or {}

    def get_val(key: str, default: str) -> str:
        return overrides.get(key, os.getenv(key, default))

    app_env = get_val("APP_ENV", "development").strip()
    log_level = get_val("LOG_LEVEL", "INFO").strip().upper()

    data_dir = _resolve_path(get_val("DATA_DIR", "data"), base_root)
    logs_dir = _resolve_path(get_val("LOGS_DIR", "logs"), base_root)

    # Database path and URL resolution
    db_env_path = get_val("DATABASE_PATH", "")
    if db_env_path:
        database_path = _resolve_path(db_env_path, base_root)
    else:
        database_path = (data_dir / "linkedin_automation.db").resolve()

    db_url_env = get_val("DATABASE_URL", "")
    if db_url_env:
        database_url = db_url_env
        # If url is sqlite:///..., extract or keep sync
        if database_url.startswith("sqlite:///"):
            sqlite_target = database_url.replace("sqlite:///", "")
            database_path = _resolve_path(sqlite_target, base_root)
    else:
        # SQLite URL uses forward slashes
        database_url = f"sqlite:///{database_path.as_posix()}"

    contacts_path = _resolve_path(
        get_val("CONTACTS_WORKBOOK_PATH", str(data_dir / "contacts.xlsx")),
        base_root,
    )
    scraped_replies_path = _resolve_path(
        get_val("SCRAPED_REPLIES_WORKBOOK_PATH", str(data_dir / "scraped_replies.xlsx")),
        base_root,
    )
    automation_cycles_path = _resolve_path(
        get_val("AUTOMATION_CYCLES_WORKBOOK_PATH", str(data_dir / "automation_cycles.xlsx")),
        base_root,
    )
    templates_path = _resolve_path(
        get_val("TEMPLATES_FILE_PATH", str(base_root / "templates.json")),
        base_root,
    )

    log_file_path = logs_dir / "automation.log"

    initial_template_key = get_val("INITIAL_TEMPLATE_KEY", "initial_outreach").strip()
    raw_limit = get_val("MAX_INITIAL_MESSAGES_PER_RUN", "10").strip()
    try:
        max_initial_messages = int(raw_limit)
    except ValueError:
        raise ConfigurationError(
            f"Invalid MAX_INITIAL_MESSAGES_PER_RUN '{raw_limit}'. Must be an integer."
        )

    messaging_adapter = get_val("MESSAGING_ADAPTER", "mock").strip().lower()

    config = AppConfig(
        project_root=base_root,
        data_dir=data_dir,
        logs_dir=logs_dir,
        database_path=database_path,
        database_url=database_url,
        contacts_workbook_path=contacts_path,
        scraped_replies_workbook_path=scraped_replies_path,
        automation_cycles_workbook_path=automation_cycles_path,
        templates_file_path=templates_path,
        log_level=log_level,
        app_env=app_env,
        log_file_path=log_file_path,
        initial_template_key=initial_template_key,
        max_initial_messages_per_run=max_initial_messages,
        messaging_adapter=messaging_adapter,
    )

    config.ensure_directories()
    config.validate()
    return config


# Default singleton instance for general application use
CONFIG: AppConfig = load_config()


def setup_logging(config: Optional[AppConfig] = None) -> logging.Logger:
    """Set up structured console and file logging."""
    cfg = config or CONFIG
    cfg.ensure_directories()

    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    logger = logging.getLogger("linkedin_automation")
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler
        file_handler = logging.FileHandler(cfg.log_file_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

