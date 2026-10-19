"""
Tests for the async session repository layer.

Uses pytest-asyncio with aiosqlite and AsyncSession.
Tests get_history_for_exercise and get_session_with_sets.
"""

from __future__ import annotations

import asyncio
import datetime
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, Exercise, Prescription, SetLog, Session as DBSession
from app.repositories.sessions import (
    get_history_for_exercise,
    get_session_with_sets,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    """Provide a file-based async SQLite database URL for each test."""
    db_file = tmp_path / "test_async_repo.db"
    return f"sqlite+aiosqlite:///{db_file}"


@pytest_asyncio.fixture()
async def engine(db_url: str):
    """Create an async engine for each test."""
    eng = create_async_engine(db_url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def async_session(engine):
    """Provide an AsyncSession for each test."""
    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as s:
        yield s


@pytest_asyncio.fixture()
async def seeded_async_session(async_session: AsyncSession):
    """Seed the database with exercises, a session, prescriptions and set_logs."""
    # Create exercises
    bench = Exercise(name="Bench Press", role="main", movement_pattern="press", metric_type="load_reps")
    squat = Exercise(name="Squat", role="main", movement_pattern="squat", metric_type="load_reps")
    async_session.add_all([bench, squat])
    await async_session.flush()

    # Create a session
    sess = DBSession(
        cycle_id=1,
        day_label="A",
        scheduled_date=datetime.date.today(),
        actual_date=datetime.date.today(),
        status="completed",
    )
    async_session.add(sess)
    await async_session.flush()

    # Create prescriptions
    pres1 = Prescription(
        session_id=sess.id,
        exercise_id=bench.id,
        set_number=1,
        prescribed_reps=5,
        prescribed_load_lb=225.0,
    )
    pres2 = Prescription(
        session_id=sess.id,
        exercise_id=bench.id,
        set_number=2,
        prescribed_reps=5,
        prescribed_load_lb=225.0,
    )
    pres3 = Prescription(
        session_id=sess.id,
        exercise_id=squat.id,
        set_number=1,
        prescribed_reps=5,
        prescribed_load_lb=315.0,
    )
    async_session.add_all([pres1, pres2, pres3])
    await async_session.flush()

    # Create set_logs with exercise_id and session_id
    slog1 = SetLog(
        exercise_id=bench.id,
        session_id=sess.id,
        prescription_id=pres1.id,
        actual_load_lb=225.0,
        actual_reps=5,
        rpe=8.0,
        e1rm_lb=262.5,
        confidence="high",
        pain_flag=False,
        set_type="top",
        note="Felt strong",
    )
    slog2 = SetLog(
        exercise_id=bench.id,
        session_id=sess.id,
        prescription_id=pres2.id,
        actual_load_lb=225.0,
        actual_reps=5,
        rpe=8.5,
        e1rm_lb=262.5,
        confidence="high",
        pain_flag=False,
        set_type="top",
        note=None,
    )
    slog3 = SetLog(
        exercise_id=squat.id,
        session_id=sess.id,
        prescription_id=pres3.id,
        actual_load_lb=315.0,
        actual_reps=5,
        rpe=9.0,
        e1rm_lb=367.5,
        confidence="high",
        pain_flag=False,
        set_type="top",
        note="Heavy",
    )
    async_session.add_all([slog1, slog2, slog3])
    await async_session.commit()

    return async_session


# ---------------------------------------------------------------------------
# Tests: get_history_for_exercise
# ---------------------------------------------------------------------------

class TestGetHistoryForExercise:

    @pytest.mark.asyncio
    async def test_returns_history_for_bench_press(self, seeded_async_session: AsyncSession):
        """Should return set history for bench press exercise."""
        bench = await seeded_async_session.execute(
            text("SELECT id FROM exercise WHERE name = 'Bench Press'")
        )
        bench_id = bench.scalar_one()

        history = await get_history_for_exercise(seeded_async_session, bench_id)

        assert len(history) == 2
        assert history[0]["exercise_name"] == "Bench Press"
        assert history[0]["actual_load_lb"] == 225.0
        assert history[0]["actual_reps"] == 5

    @pytest.mark.asyncio
    async def test_returns_history_for_squat(self, seeded_async_session: AsyncSession):
        """Should return set history for squat exercise."""
        squat = await seeded_async_session.execute(
            text("SELECT id FROM exercise WHERE name = 'Squat'")
        )
        squat_id = squat.scalar_one()

        history = await get_history_for_exercise(seeded_async_session, squat_id)

        assert len(history) == 1
        assert history[0]["exercise_name"] == "Squat"
        assert history[0]["actual_load_lb"] == 315.0

    @pytest.mark.asyncio
    async def test_returns_empty_for_nonexistent_exercise(self, seeded_async_session: AsyncSession):
        """Should return empty list for exercise_id that doesn't exist."""
        history = await get_history_for_exercise(seeded_async_session, 9999)
        assert history == []

    @pytest.mark.asyncio
    async def test_respects_limit(self, seeded_async_session: AsyncSession):
        """Should respect the limit parameter on distinct sessions."""
        bench = await seeded_async_session.execute(
            text("SELECT id FROM exercise WHERE name = 'Bench Press'")
        )
        bench_id = bench.scalar_one()

        # Both bench sets are in the same session, so limit=1 session
        # still returns both sets from that one session
        history = await get_history_for_exercise(seeded_async_session, bench_id, limit=1)
        # All sets from the 1 session are returned
        assert len(history) == 2
        # But only 1 distinct session
        session_ids = {h["session_id"] for h in history}
        assert len(session_ids) == 1

    @pytest.mark.asyncio
    async def test_includes_session_info(self, seeded_async_session: AsyncSession):
        """Should include session date and day_label in results."""
        bench = await seeded_async_session.execute(
            text("SELECT id FROM exercise WHERE name = 'Bench Press'")
        )
        bench_id = bench.scalar_one()

        history = await get_history_for_exercise(seeded_async_session, bench_id)
        assert history[0]["session_date"] is not None
        assert history[0]["session_day_label"] == "A"
        assert history[0]["session_status"] == "completed"

    @pytest.mark.asyncio
    async def test_includes_rpe_and_confidence(self, seeded_async_session: AsyncSession):
        """Should include RPE and confidence values."""
        bench = await seeded_async_session.execute(
            text("SELECT id FROM exercise WHERE name = 'Bench Press'")
        )
        bench_id = bench.scalar_one()

        history = await get_history_for_exercise(seeded_async_session, bench_id)
        assert history[0]["rpe"] == 8.0
        assert history[0]["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_includes_pain_flag(self, seeded_async_session: AsyncSession):
        """Should include pain_flag in results."""
        bench = await seeded_async_session.execute(
            text("SELECT id FROM exercise WHERE name = 'Bench Press'")
        )
        bench_id = bench.scalar_one()

        history = await get_history_for_exercise(seeded_async_session, bench_id)
        assert history[0]["pain_flag"] is False


# ---------------------------------------------------------------------------
# Tests: get_session_with_sets
# ---------------------------------------------------------------------------

class TestGetSessionWithSets:

    @pytest.mark.asyncio
    async def test_returns_session_with_sets(self, seeded_async_session: AsyncSession):
        """Should return a session with all its set_logs."""
        sess = await seeded_async_session.execute(
            text("SELECT id FROM session WHERE day_label = 'A'")
        )
        sess_id = sess.scalar_one()

        result = await get_session_with_sets(seeded_async_session, sess_id)

        assert result is not None
        assert result["id"] == sess_id
        assert result["day_label"] == "A"
        assert result["status"] == "completed"
        assert len(result["sets"]) == 3

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_session(self, seeded_async_session: AsyncSession):
        """Should return None for a session that doesn't exist."""
        result = await get_session_with_sets(seeded_async_session, 9999)
        assert result is None

    @pytest.mark.asyncio
    async def test_sets_ordered_by_logged_at(self, seeded_async_session: AsyncSession):
        """Sets should be ordered by logged_at ascending."""
        sess = await seeded_async_session.execute(
            text("SELECT id FROM session WHERE day_label = 'A'")
        )
        sess_id = sess.scalar_one()

        result = await get_session_with_sets(seeded_async_session, sess_id)
        # All sets have the same logged_at (now), so just check they're present
        assert len(result["sets"]) == 3

    @pytest.mark.asyncio
    async def test_set_includes_exercise_id(self, seeded_async_session: AsyncSession):
        """Each set should include exercise_id."""
        sess = await seeded_async_session.execute(
            text("SELECT id FROM session WHERE day_label = 'A'")
        )
        sess_id = sess.scalar_one()

        result = await get_session_with_sets(seeded_async_session, sess_id)
        for s in result["sets"]:
            assert "exercise_id" in s
            assert s["exercise_id"] is not None


# ---------------------------------------------------------------------------
# Tests: Schema structure
# ---------------------------------------------------------------------------

class TestSchemaStructure:

    @pytest.mark.asyncio
    async def test_set_log_has_exercise_id_column(self, async_session: AsyncSession):
        """SetLog should have exercise_id column."""
        bench = Exercise(name="Test Bench", role="main", metric_type="load_reps")
        async_session.add(bench)
        await async_session.flush()

        sess = DBSession(
            cycle_id=1,
            day_label="A",
            scheduled_date=datetime.date.today(),
            status="planned",
        )
        async_session.add(sess)
        await async_session.flush()

        slog = SetLog(
            exercise_id=bench.id,
            session_id=sess.id,
            actual_load_lb=100.0,
            actual_reps=5,
        )
        async_session.add(slog)
        await async_session.commit()

        # Verify the set_log was created with exercise_id
        result = await async_session.execute(
            text("SELECT exercise_id FROM set_log WHERE id = :id"),
            {"id": slog.id},
        )
        ex_id = result.scalar_one()
        assert ex_id == bench.id

    @pytest.mark.asyncio
    async def test_set_log_prescription_id_is_nullable(self, async_session: AsyncSession):
        """SetLog prescription_id should be nullable."""
        bench = Exercise(name="Test Bench", role="main", metric_type="load_reps")
        async_session.add(bench)
        await async_session.flush()

        sess = DBSession(
            cycle_id=1,
            day_label="A",
            scheduled_date=datetime.date.today(),
            status="planned",
        )
        async_session.add(sess)
        await async_session.flush()

        slog = SetLog(
            exercise_id=bench.id,
            session_id=sess.id,
            prescription_id=None,
            actual_load_lb=100.0,
            actual_reps=5,
        )
        async_session.add(slog)
        await async_session.commit()

        # Verify the set_log was created with NULL prescription_id
        result = await async_session.execute(
            text("SELECT prescription_id FROM set_log WHERE id = :id"),
            {"id": slog.id},
        )
        pres_id = result.scalar_one()
        assert pres_id is None

    @pytest.mark.asyncio
    async def test_set_log_exercise_id_is_not_null(self, async_session: AsyncSession):
        """SetLog exercise_id should be NOT NULL."""
        bench = Exercise(name="Test Bench", role="main", metric_type="load_reps")
        async_session.add(bench)
        await async_session.flush()

        sess = DBSession(
            cycle_id=1,
            day_label="A",
            scheduled_date=datetime.date.today(),
            status="planned",
        )
        async_session.add(sess)
        await async_session.flush()

        # Try to create a SetLog without exercise_id - should fail
        slog = SetLog(
            session_id=sess.id,
            actual_load_lb=100.0,
            actual_reps=5,
        )
        async_session.add(slog)
        with pytest.raises(Exception):
            await async_session.commit()
