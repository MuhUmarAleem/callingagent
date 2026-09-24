"""
Database engine and session management.

Key design decisions:
- Lazy connection: engine is created at import time but pool connects on first use.
  This allows /health to return "db_down" gracefully rather than crashing at startup.
- pool_pre_ping: validates connections before use (handles Supabase idle resets).
- Small pool: free-tier Supabase has limited connections.
- prepare_threshold=None: required for Supabase transaction pooler (PgBouncer)
  which does not support PostgreSQL prepared statements.
"""
import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.schema import SCHEMA_STATEMENTS

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url

        connect_args = {
            "connect_timeout": 5,
        }

        # Disable prepared statements for Supabase transaction pooler (PgBouncer)
        connect_args["prepare_threshold"] = None

        engine_kwargs = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        # Vercel Functions should not hold a connection pool across invocations.
        if os.environ.get("VERCEL") == "1":
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = 3
            engine_kwargs["max_overflow"] = 2

        _engine = create_engine(url, **engine_kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    return _engine, _SessionLocal


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager that provides a database session and handles commit/rollback."""
    _, SessionLocal = _get_engine()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db_health() -> bool:
    """Run SELECT 1 to verify DB connectivity. Returns True if healthy."""
    try:
        engine, _ = _get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("DB health check failed: %s", exc)
        return False


def _schema_exists(conn) -> bool:
    count = conn.execute(
        text(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('patients', 'call_logs')
            """
        )
    ).scalar()
    return int(count or 0) >= 2


def init_schema() -> bool:
    """Create tables only when they are missing. Skip DDL on every serverless request."""
    try:
        engine, _ = _get_engine()
        with engine.connect() as conn:
            if _schema_exists(conn):
                return True
        with engine.begin() as conn:
            for stmt in SCHEMA_STATEMENTS:
                conn.execute(text(stmt))
        logger.info("Database schema is ready.")
        return True
    except Exception as exc:
        logger.warning("Schema init failed: %s", exc)
        return False
