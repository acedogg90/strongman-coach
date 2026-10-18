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
    Block,
    Cycle,
    Exercise,
    Prescription,
    Program,
    Session as DBSession,
    SetLog,
    get_engine,
    get_session_factory,
    init_db,
    migrate_from_training_entry,
    sessionmaker,
)
from app.strength.warmup_backoff import (
    generate_warmups,
    calculate_backoff,
    calculate_backoff_series,
    get_default_drop_pct,
)
from app.strength.adjustment_rules import evaluate_adjustments

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


class WarmupRequest(BaseModel):
    """Request to generate warm-up sets for an exercise."""
    exercise_name: str
    top_set_weight: float
    reps: int = 3
    plate_increment: float = 2.5
    bar_weight: float = 45.0


class BackoffRequest(BaseModel):
    """Request to generate back-off sets for an exercise."""
    exercise_name: str
    top_set_weight: float
    reps: int = 3
    rpe: Optional[float] = None
    drop_pct: Optional[float] = None
    phase: Optional[str] = None
    notes: Optional[str] = None
    max_sets: int = 6


class SessionCreate(BaseModel):
    """Request to create a new session."""
    day_label: str  # A, B, C, or D
    scheduled_date: Optional[str] = None
    readiness_sleep: Optional[int] = None
    readiness_soreness: Optional[int] = None
    readiness_stress: Optional[int] = None


class SetLogRequest(BaseModel):
    """Request to log a set."""
    exercise_name: str
    weight: float
    reps: int
    rpe: Optional[float] = None
    set_type: str = "top"  # warmup, top, backoff, apre
    pain_flag: bool = False
    note: Optional[str] = None


class SessionResponse(BaseModel):
    """Response for a session."""
    id: int
    cycle_id: int
    day_label: str
    scheduled_date: Optional[str] = None
    actual_date: Optional[str] = None
    status: str
    readiness_sleep: Optional[int] = None
    readiness_soreness: Optional[int] = None
    readiness_stress: Optional[int] = None
    created_at: Optional[str] = None
    block_phase: Optional[str] = None


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
# POST /warmups – Generate and store warm-up prescriptions for an exercise
# ---------------------------------------------------------------------------

@app.post("/warmups")
def generate_warmup_sets(req: WarmupRequest):
    """Generate warm-up sets and store them as prescriptions in the session.

    Warm-ups are auto-generated as a progression toward the top-set weight:
    empty bar → 40% → 60% → 80% of top-set weight, rounded to plate increment.
    """
    session = _get_session()
    try:
        # Ensure exercise exists
        ex = session.query(Exercise).filter_by(name=req.exercise_name).first()
        if not ex:
            ex = Exercise(name=req.exercise_name, role="accessory", metric_type="load_reps")
            session.add(ex)
            session.flush()

        # Find or create a session for today
        today = datetime.date.today()
        db_sess = session.query(DBSession).filter_by(
            scheduled_date=today, status="in_progress"
        ).first()

        if not db_sess:
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

        # Generate warm-up sets
        warmups = generate_warmups(
            top_set_weight=req.top_set_weight,
            reps=req.reps,
            plate_increment=req.plate_increment,
            bar_weight=req.bar_weight,
        )

        # Store each warm-up as a prescription
        prescription_ids = []
        for i, warmup in enumerate(warmups):
            pres = Prescription(
                session_id=db_sess.id,
                exercise_id=ex.id,
                set_number=i + 1,
                prescribed_reps=warmup.reps,
                prescribed_load_lb=warmup.load_lb,
                is_warmup=True,
                is_backoff=False,
                fatigue_drop_pct=0.0,
            )
            session.add(pres)
            session.flush()
            prescription_ids.append(pres.id)

        session.commit()
        return {
            "generated": True,
            "prescription_ids": prescription_ids,
            "warmup_count": len(warmups),
            "warmups": [
                {"load_lb": w.load_lb, "reps": w.reps, "is_empty_bar": w.is_empty_bar}
                for w in warmups
            ],
        }

    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Failed to generate warm-up sets")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# POST /backoffs – Generate and store back-off prescriptions for an exercise
# ---------------------------------------------------------------------------

@app.post("/backoffs")
def generate_backoff_sets(req: BackoffRequest):
    """Generate back-off sets and store them as prescriptions in the session.

    Back-off sets calculate weight as top_set_weight × (1 - drop_pct/100)
    using the configured drop percentage per block phase.
    """
    session = _get_session()
    try:
        # Ensure exercise exists
        ex = session.query(Exercise).filter_by(name=req.exercise_name).first()
        if not ex:
            ex = Exercise(name=req.exercise_name, role="accessory", metric_type="load_reps")
            session.add(ex)
            session.flush()

        # Find or create a session for today
        today = datetime.date.today()
        db_sess = session.query(DBSession).filter_by(
            scheduled_date=today, status="in_progress"
        ).first()

        if not db_sess:
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

        # Determine drop percentage
        if req.drop_pct is not None:
            drop_pct = req.drop_pct
        elif req.phase is not None:
            drop_pct = get_default_drop_pct(req.phase)
        else:
            drop_pct = get_default_drop_pct("accumulation")

        # Generate back-off series
        backoffs = calculate_backoff_series(
            top_set_weight=req.top_set_weight,
            drop_pct=drop_pct,
            exercise=req.exercise_name,
            reps=req.reps,
            rpe=req.rpe,
            notes=req.notes or "",
            max_sets=req.max_sets,
        )

        # Store each back-off as a prescription
        prescription_ids = []
        for i, backoff in enumerate(backoffs):
            pres = Prescription(
                session_id=db_sess.id,
                exercise_id=ex.id,
                set_number=i + 1,
                prescribed_reps=backoff.reps,
                prescribed_load_lb=backoff.weight_lb,
                is_warmup=False,
                is_backoff=True,
                fatigue_drop_pct=backoff.drop_pct,
            )
            session.add(pres)
            session.flush()
            prescription_ids.append(pres.id)

        session.commit()
        return {
            "generated": True,
            "prescription_ids": prescription_ids,
            "backoff_count": len(backoffs),
            "backoffs": [
                {
                    "weight_lb": b.weight_lb,
                    "reps": b.reps,
                    "rpe": b.rpe,
                    "drop_pct": b.drop_pct,
                    "notes": b.notes,
                }
                for b in backoffs
            ],
        }

    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Failed to generate back-off sets")
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
            DBSession.actual_date.label("date"),
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
