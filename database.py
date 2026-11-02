"""Database layer for SQLite access using SQLAlchemy 2.x.

Provides engine creation, foreign key pragma enforcement for SQLite,
reusable session context management, transaction handling, and explicit
table schema initialization.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from config import AppConfig, CONFIG
from models import Base

logger = logging.getLogger("linkedin_automation.database")

# Internal engine and session factory caches
_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker[Session]] = None


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """Enforce SQLite foreign key constraints upon connection."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


def get_engine(config: Optional[AppConfig] = None) -> Engine:
    """Retrieve or create the SQLAlchemy engine for the specified configuration."""
    global _ENGINE
    cfg = config or CONFIG
    if _ENGINE is None or (config is not None and str(_ENGINE.url) != cfg.database_url):
        logger.debug("Creating database engine for URL: %s", cfg.database_url)
        _ENGINE = create_engine(
            cfg.database_url,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False} if cfg.database_url.startswith("sqlite") else {},
        )
    return _ENGINE


def get_session_factory(engine: Optional[Engine] = None, config: Optional[AppConfig] = None) -> sessionmaker[Session]:
    """Retrieve or create the session factory bound to the active engine."""
    global _SESSION_FACTORY
    eng = engine or get_engine(config)
    if _SESSION_FACTORY is None or _SESSION_FACTORY.kw.get("bind") != eng:
        _SESSION_FACTORY = sessionmaker(
            bind=eng,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SESSION_FACTORY


@contextmanager
def get_db_session(engine: Optional[Engine] = None, config: Optional[AppConfig] = None) -> Generator[Session, None, None]:
    """Provide a transactional SQLAlchemy session scope.

    Commits on successful completion, rolls back on exception,
    and reliably closes the session.
    """
    factory = get_session_factory(engine, config)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("Database error occurred during transaction; rolled back: %s", exc)
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Unexpected error during database transaction; rolled back: %s", exc)
        raise
    finally:
        session.close()


def init_db(engine: Optional[Engine] = None, config: Optional[AppConfig] = None) -> None:
    """Explicitly create all defined tables in the database.

    Does not run on module import; must be invoked explicitly.
    """
    cfg = config or CONFIG
    cfg.ensure_directories()
    eng = engine or get_engine(cfg)
    try:
        logger.info("Initializing database schema at: %s", eng.url)
        Base.metadata.create_all(bind=eng)

        # Apply backward-compatible column migrations if database already existed
        with eng.begin() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            if "replies" in inspector.get_table_names():
                col_defs = {c["name"]: c for c in inspector.get_columns("replies")}
                needs_table_rebuild = False
                if "contact_id" in col_defs and not col_defs["contact_id"].get("nullable", True):
                    needs_table_rebuild = True

                if "conversation_id" not in col_defs:
                    conn.exec_driver_sql("ALTER TABLE replies ADD COLUMN conversation_id VARCHAR(255);")
                    logger.info("Migrated replies table: added conversation_id column.")

                if needs_table_rebuild:
                    conn.exec_driver_sql(
                        "CREATE TABLE replies_new ("
                        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                        "contact_id INTEGER, "
                        "external_reply_id VARCHAR(255) UNIQUE, "
                        "conversation_id VARCHAR(255), "
                        "reply_text TEXT NOT NULL, "
                        "reply_timestamp DATETIME, "
                        "collected_at DATETIME NOT NULL, "
                        "processing_status VARCHAR(32) DEFAULT 'new' NOT NULL, "
                        "category VARCHAR(64), "
                        "selected_template_key VARCHAR(128), "
                        "CONSTRAINT check_reply_processing_status CHECK (processing_status IN ('new', 'processed', 'needs_review')), "
                        "FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE CASCADE);"
                    )
                    conn.exec_driver_sql(
                        "INSERT INTO replies_new ("
                        "id, contact_id, external_reply_id, conversation_id, reply_text, reply_timestamp, collected_at, processing_status, category, selected_template_key"
                        ") SELECT id, contact_id, external_reply_id, conversation_id, reply_text, reply_timestamp, collected_at, processing_status, category, selected_template_key FROM replies;"
                    )
                    conn.exec_driver_sql("DROP TABLE replies;")
                    conn.exec_driver_sql("ALTER TABLE replies_new RENAME TO replies;")
                    logger.info("Migrated replies table: made contact_id nullable.")

        logger.info("Database schema initialized successfully.")
    except SQLAlchemyError as exc:
        logger.error("Failed to initialize database schema: %s", exc)
        raise


def reset_engine_cache() -> None:
    """Clear cached engine and session factory instances (useful for test isolation)."""
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None

