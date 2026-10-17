"""
Strongman Coach – API routes.

Provides backward-compatible /log, /history, /edit, /delete endpoints
that work with the new schema.
"""

from __future__ import annotations

import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.database import (
    Base,
    Exercise,
    Prescription,
    Session as DBSession,
    SetLog,
    get_engine,
    get_session_factory,
    init_db,
    migrate_from_training_entry,
    sessionmaker,
)

app = FastAPI(title="Strongman Coach")

# ---------------------------------------------------------------------------
# Startup: init DB and run migration
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()
    migrate_from_training_entry()


# ---------------------------------------------------------------------------
# Pydantic models for request/response
# ---------------------------------------------------------------------------

class TrainingEntryCreate(BaseModel):
    date: Optional[str] = None
    exercise_name: str
    weight: float
    reps: int
    sets: int = 1
    notes: Optional[str] = None


class TrainingEntryUpdate(BaseModel):
    date: Optional[str] = None
    exercise_name: Optional[str] = None
    weight: Optional[float] = None
    reps: Optional[int] = None
    sets: Optional[int] = None
    notes: Optional[str] = None


class TrainingEntryResponse(BaseModel):
    id: int
    date: Optional[str] = None
    exercise_name: str
    weight: float
    reps: int
    sets: int
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper: get a session
# ---------------------------------------------------------------------------

def _get_session():
    factory = get_session_factory()
    return factory()


# ---------------------------------------------------------------------------
# POST /log – Log a new training entry
# ---------------------------------------------------------------------------

@app.post("/log")
def log_entry(entry: TrainingEntryCreate):
    """Log a new training entry. Creates exercise, prescription, and set_log rows."""
    session = _get_session()
    try:
        # Ensure exercise exists
        ex = session.query(Exercise).filter_by(name=entry.exercise_name).first()
        if not ex:
            ex = Exercise(name=entry.exercise_name, role="accessory", metric_type="load_reps")
            session.add(ex)
            session.flush()

        # Find or create a session for today
        today = datetime.date.today()
        db_sess = session.query(DBSession).filter_by(
            scheduled_date=today, status="in_progress"
        ).first()

        if not db_sess:
            # Find any active program/block/cycle
            from app.database import Program, Block, Cycle
            program = session.query(Program).filter_by(is_active=True).first()
            if not program:
                program = Program(
                    athlete_id=1,
                    name="Default Program",
                    phase="accumulation",
                    start_date=today,
                    is_active=True,
                )
                session.add(program)
                session.flush()

            block = session.query(Block).filter_by(program_id=program.id).first()
            if not block:
                block = Block(
                    program_id=program.id,
                    block_number=1,
                    start_date=today,
                )
                session.add(block)
                session.flush()

            cycle = session.query(Cycle).filter_by(block_id=block.id).first()
            if not cycle:
                cycle = Cycle(
                    block_id=block.id,
                    cycle_number=1,
                    start_date=today,
                )
                session.add(cycle)
                session.flush()

            db_sess = DBSession(
                cycle_id=cycle.id,
                day_label="A",
                scheduled_date=today,
                actual_date=today,
                status="in_progress",
            )
            session.add(db_sess)
            session.flush()

        # Create prescriptions and set_logs for each set
        created_ids = []
        for set_num in range(1, entry.sets + 1):
            pres = Prescription(
                session_id=db_sess.id,
                exercise_id=ex.id,
                set_number=set_num,
                prescribed_reps=entry.reps,
                prescribed_load_lb=entry.weight,
            )
            session.add(pres)
            session.flush()

            e1rm = entry.weight * (1 + entry.reps / 30.0)

            slog = SetLog(
                prescription_id=pres.id,
                actual_load_lb=entry.weight,
                actual_reps=entry.reps,
                rpe=None,
                e1rm_lb=e1rm,
                confidence="low",
                pain_flag=False,
                note=entry.notes,
            )
            session.add(slog)
            created_ids.append(slog.id)

        session.commit()
        return {"logged": True, "set_log_ids": created_ids}

    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Failed to log entry")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# GET /history – Get training history
# ---------------------------------------------------------------------------

@app.get("/history")
def get_history(exercise: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None):
    """Get training history from set_log, joined with prescriptions and exercises."""
    session = _get_session()
    try:
        query = session.query(
            SetLog.id,
            DBSession.actual_date,
            Exercise.name.label("exercise_name"),
            SetLog.actual_load_lb.label("weight"),
            SetLog.actual_reps.label("reps"),
            SetLog.note,
        ).join(
            Prescription, SetLog.prescription_id == Prescription.id
        ).join(
            Exercise, Prescription.exercise_id == Exercise.id
        ).join(
            DBSession, Prescription.session_id == DBSession.id
        )

        if exercise:
            query = query.filter(Exercise.name.ilike(f"%{exercise}%"))
        if date_from:
            query = query.filter(DBSession.actual_date >= date_from)
        if date_to:
            query = query = query.filter(DBSession.actual_date <= date_to)

        rows = query.order_by(DBSession.actual_date.desc()).all()
        result = []
        for row in rows:
            result.append({
                "id": row.id,
                "date": str(row.date) if row.date else None,
                "exercise_name": row.exercise_name,
                "weight": row.weight,
                "reps": row.reps,
                "notes": row.note,
            })
        return result

    finally:
        session.close()


# ---------------------------------------------------------------------------
# PATCH /edit/{id} – Edit a training entry
# ---------------------------------------------------------------------------

@app.patch("/edit/{entry_id}")
def edit_entry(entry_id: int, updates: TrainingEntryUpdate):
    """Edit an existing set_log entry."""
    session = _get_session()
    try:
        slog = session.query(SetLog).filter_by(id=entry_id).first()
        if not slog:
            raise HTTPException(status_code=404, detail="Entry not found")

        if updates.weight is not None:
            slog.actual_load_lb = updates.weight
        if updates.reps is not None:
            slog.actual_reps = updates.reps
        if updates.notes is not None:
            slog.note = updates.notes

        # Recompute e1RM
        if updates.weight is not None and updates.reps is not None:
            slog.e1rm_lb = updates.weight * (1 + updates.reps / 30.0)

        session.commit()
        return {"updated": True, "id": entry_id}

    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Failed to update entry")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# DELETE /delete/{id} – Delete a training entry
# ---------------------------------------------------------------------------

@app.delete("/delete/{entry_id}")
def delete_entry(entry_id: int):
    """Delete a set_log entry and its prescription."""
    session = _get_session()
    try:
        slog = session.query(SetLog).filter_by(id=entry_id).first()
        if not slog:
            raise HTTPException(status_code=404, detail="Entry not found")

        pres_id = slog.prescription_id
        session.delete(slog)

        # Also delete the prescription
        pres = session.query(Prescription).filter_by(id=pres_id).first()
        if pres:
            session.delete(pres)

        session.commit()
        return {"deleted": True, "id": entry_id}

    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete entry")
    finally:
        session.close()
