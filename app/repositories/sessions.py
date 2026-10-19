"""
Async repository for session and set_log operations.

Uses SQLAlchemy 2.0 async patterns with AsyncSession and aiosqlite.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Exercise, SetLog, Session as DBSession


async def get_history_for_exercise(
    session: AsyncSession,
    exercise_id: int,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return the last *limit* sessions that contain sets for *exercise_id*.

    Uses async SQLAlchemy 2.0 select() with joinedload to avoid the
    prescription join that the old synchronous code used.

    Returns a list of dicts with session info and set details.
    """
    # Get distinct session_ids that have sets for this exercise, ordered by
    # logged_at descending, limited to *limit* sessions.
    stmt = (
        select(SetLog.session_id)
        .where(
            SetLog.exercise_id == exercise_id,
            SetLog.session_id.isnot(None),
        )
        .distinct()
        .order_by(SetLog.logged_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    session_ids = [row[0] for row in result.all()]

    if not session_ids:
        return []

    # Fetch all set_logs for those sessions
    sets_stmt = (
        select(SetLog)
        .where(
            SetLog.exercise_id == exercise_id,
            SetLog.session_id.in_(session_ids),
        )
        .order_by(SetLog.logged_at.desc())
    )
    sets_result = await session.execute(sets_stmt)
    sets = sets_result.scalars().all()

    # Fetch session details
    sess_stmt = (
        select(DBSession)
        .where(DBSession.id.in_(session_ids))
    )
    sess_result = await session.execute(sess_stmt)
    sessions = {s.id: s for s in sess_result.scalars().all()}

    # Fetch exercise name
    ex_stmt = select(Exercise).where(Exercise.id == exercise_id)
    ex_result = await session.execute(ex_stmt)
    exercise = ex_result.scalar_one_or_none()

    # Build response
    history: list[dict[str, Any]] = []
    for s in sets:
        db_sess = sessions.get(s.session_id)
        history.append({
            "set_log_id": s.id,
            "session_id": s.session_id,
            "exercise_id": s.exercise_id,
            "exercise_name": exercise.name if exercise else "Unknown",
            "actual_load_lb": s.actual_load_lb,
            "actual_reps": s.actual_reps,
            "rpe": s.rpe,
            "e1rm_lb": s.e1rm_lb,
            "confidence": s.confidence,
            "pain_flag": s.pain_flag,
            "set_type": s.set_type,
            "note": s.note,
            "logged_at": str(s.logged_at) if s.logged_at else None,
            "session_date": (
                str(db_sess.scheduled_date) if db_sess and db_sess.scheduled_date else None
            ),
            "session_day_label": db_sess.day_label if db_sess else None,
            "session_status": db_sess.status if db_sess else None,
        })

    return history


async def get_session_with_sets(
    session: AsyncSession,
    session_id: int,
) -> Optional[dict[str, Any]]:
    """Return a session with all its set_logs for a given exercise.

    Uses async SQLAlchemy 2.0 patterns.
    """
    sess_stmt = select(DBSession).where(DBSession.id == session_id)
    sess_result = await session.execute(sess_stmt)
    db_sess = sess_result.scalar_one_or_none()

    if not db_sess:
        return None

    sets_stmt = (
        select(SetLog)
        .where(SetLog.session_id == session_id)
        .order_by(SetLog.logged_at.asc())
    )
    sets_result = await session.execute(sets_stmt)
    sets = sets_result.scalars().all()

    return {
        "id": db_sess.id,
        "cycle_id": db_sess.cycle_id,
        "day_label": db_sess.day_label,
        "scheduled_date": str(db_sess.scheduled_date) if db_sess.scheduled_date else None,
        "actual_date": str(db_sess.actual_date) if db_sess.actual_date else None,
        "status": db_sess.status,
        "readiness_sleep": db_sess.readiness_sleep,
        "readiness_soreness": db_sess.readiness_soreness,
        "readiness_stress": db_sess.readiness_stress,
        "created_at": str(db_sess.created_at) if db_sess.created_at else None,
        "sets": [
            {
                "id": s.id,
                "exercise_id": s.exercise_id,
                "prescription_id": s.prescription_id,
                "actual_load_lb": s.actual_load_lb,
                "actual_reps": s.actual_reps,
                "rpe": s.rpe,
                "e1rm_lb": s.e1rm_lb,
                "confidence": s.confidence,
                "pain_flag": s.pain_flag,
                "set_type": s.set_type,
                "note": s.note,
                "logged_at": str(s.logged_at) if s.logged_at else None,
            }
            for s in sets
        ],
    }
