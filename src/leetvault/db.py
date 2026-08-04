"""Engine/session factory and SyncState helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from leetvault.models import Base, SyncState


def _add_missing_columns(engine: Engine) -> None:
    """Additively migrate an existing DB to match the current models.

    `create_all` only creates missing *tables*, never new columns on existing ones, so a
    DB written by an older leetvault would keep working but silently lack any column added
    since. There's no migration framework here (and an additive-only schema doesn't need
    one), so this reconciles the difference directly. SQLite's ALTER TABLE ADD COLUMN is
    cheap and non-destructive.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all just made it, so it is already current
            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.default is None:
                    # Can't backfill a NOT NULL column with no default on existing rows;
                    # skip rather than corrupt the table. No such column exists today.
                    continue
                col_type = column.type.compile(engine.dialect)
                connection.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
                )


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = URL.create("sqlite", database=str(db_path))
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_or_create_sync_state(session: Session, site: str) -> SyncState:
    state = session.scalar(select(SyncState).where(SyncState.site == site))
    if state is None:
        state = SyncState(site=site, last_offset=0)
        session.add(state)
        session.flush()
    return state


def update_sync_state(
    session: Session,
    state: SyncState,
    *,
    last_offset: int | None = None,
    last_submission_id: int | None = None,
    last_synced_timestamp: int | None = None,
    last_full_import_completed_at: int | None = None,
) -> None:
    if last_offset is not None:
        state.last_offset = last_offset
    if last_submission_id is not None:
        state.last_submission_id = last_submission_id
    if last_synced_timestamp is not None:
        state.last_synced_timestamp = last_synced_timestamp
    if last_full_import_completed_at is not None:
        state.last_full_import_completed_at = last_full_import_completed_at
    session.add(state)
