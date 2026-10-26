"""Database engine and session management for KubeWatch.

Provides connection pooling, session factory, FastAPI dependency,
and context-managed transaction handling.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from fastapi import HTTPException, status
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level engine and session factory caches
_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy Engine with connection health checks and pooling.
    
    Loads URL from environment settings if not explicitly provided.
    Never hardcodes credentials.
    """
    url = database_url or get_settings().database_url
    if not url:
        raise ValueError(
            "Database URL is not configured. Set the DATABASE_URL environment variable."
        )

    # SQLite (used in unit tests) needs specific pooling & threading flags
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if ":memory:" in url else None,
            echo=False,
        )

    # PostgreSQL (psycopg 3) engine configuration
    return create_engine(
        url,
        pool_pre_ping=True,      # Tests connection liveness before checkout
        pool_size=5,             # Base pool connections
        max_overflow=10,         # Maximum temporary burst connections
        pool_timeout=30.0,       # Seconds to wait before giving up on checkout
        pool_recycle=1800,       # Recycle connections every 30 minutes
        echo=False,
    )


def get_engine() -> Engine:
    """Get or initialize the shared database engine singleton."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_db_engine()
    return _ENGINE


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Get or initialize the sessionmaker for creating Sessions."""
    global _SESSION_FACTORY
    target_engine = engine or get_engine()
    if _SESSION_FACTORY is None or engine is not None:
        factory = sessionmaker(
            bind=target_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        if engine is None:
            _SESSION_FACTORY = factory
        return factory
    return _SESSION_FACTORY


@contextmanager
def session_scope(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.
    
    Commits on success, rolls back on any exception, and always closes the session.
    """
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Database transaction rolled back due to error: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a transactional SQLAlchemy session.
    
    If the database is unconfigured or unavailable, raises HTTP 503 Service Unavailable.
    """
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database persistence is not configured on this server.",
        )

    try:
        engine = get_engine()
    except Exception as err:
        logger.error("Failed to connect to database engine: %s", err)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is currently unreachable.",
        ) from err

    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except HTTPException:
        # Re-raise HTTP exceptions without wrapping
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("Database error occurred during request: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while processing the request.",
        ) from exc
    except Exception as exc:
        session.rollback()
        logger.error("Unexpected error in database session: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


def check_db_health(engine: Engine | None = None) -> dict[str, str | bool]:
    """Verify database connectivity by executing a lightweight SELECT 1 query."""
    try:
        eng = engine or get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "connected": True}
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return {"status": "error", "connected": False, "error": str(exc)}
