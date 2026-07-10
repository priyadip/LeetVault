from pathlib import Path

from leetvault.db import (
    get_or_create_sync_state,
    make_engine,
    make_session_factory,
    session_scope,
    update_sync_state,
)


def test_get_or_create_sync_state_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site="com")
        assert state.last_offset == 0
        assert state.last_submission_id is None

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site="com")
        assert state.id is not None
        first_id = state.id

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site="com")
        assert state.id == first_id


def test_update_sync_state_persists_partial_fields(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "leetvault.db")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site="com")
        update_sync_state(session, state, last_offset=40, last_submission_id=999)

    with session_scope(factory) as session:
        state = get_or_create_sync_state(session, site="com")
        assert state.last_offset == 40
        assert state.last_submission_id == 999
        assert state.last_synced_timestamp is None
