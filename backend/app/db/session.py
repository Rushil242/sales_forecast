"""Database engine and session management."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

LOG = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _configure_sqlite(engine: Engine) -> None:
    """WAL plus a busy timeout, so background jobs and requests can write concurrently."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")

    if is_sqlite and ":memory:" not in url:
        Path(url.split("sqlite:///")[-1]).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        url,
        # SQLite's default thread check would reject FastAPI's threadpool workers.
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=True,
        future=True,
    )
    if is_sqlite:
        _configure_sqlite(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    LOG.info("Database ready at %s", get_settings().database_url)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for use outside the request cycle (jobs, scripts)."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Drop cached engine/factory. Used by tests that swap the database URL."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
