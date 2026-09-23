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
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

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

        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            connect_args=connect_args,
        )
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
