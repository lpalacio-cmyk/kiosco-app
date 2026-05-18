"""Conexión a la BD: engine, sesiones, init_db."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

load_dotenv()


def _is_streamlit_running() -> bool:
    try:
        from streamlit.runtime import exists as runtime_exists
        return runtime_exists()
    except Exception:
        return False


def _resolve_db_url() -> str:
    if _is_streamlit_running():
        try:
            import streamlit as st
            url = st.secrets.get("DB_URL")
            if url:
                return url
        except Exception:
            pass
    url = os.environ.get("DB_URL")
    if url:
        return url
    raise RuntimeError(
        "DB_URL no configurada. Setear en .streamlit/secrets.toml para "
        "Streamlit, o en variable de entorno DB_URL para CLI."
    )


def _enable_sqlite_fk(engine: Engine) -> None:
    # SQLite trae FKs desactivadas por default; Postgres no necesita esto.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _build_engine() -> Engine:
    url = _resolve_db_url()
    if url.startswith(("postgresql://", "postgresql+")):
        # NullPool: Supabase Transaction Pooler ya hace pooling server-side;
        # doble pooling rompe prepared statements.
        engine = create_engine(url, poolclass=NullPool, future=True)
    else:
        engine = create_engine(url, future=True)
    if url.startswith("sqlite"):
        _enable_sqlite_fk(engine)
    return engine


_engine_singleton: Engine | None = None
_cached_engine_fn = None


def get_engine() -> Engine:
    global _engine_singleton, _cached_engine_fn
    if _is_streamlit_running():
        if _cached_engine_fn is None:
            import streamlit as st
            _cached_engine_fn = st.cache_resource(_build_engine)
        return _cached_engine_fn()
    if _engine_singleton is None:
        _engine_singleton = _build_engine()
    return _engine_singleton


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal(bind=get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from models import Base  # diferido: models.py se crea en el siguiente paso
    Base.metadata.create_all(get_engine())
