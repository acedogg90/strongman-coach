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


class SessionCompleteRequest(BaseModel):
    """Request to complete a session."""
    readiness_sleep: Optional[int] = None
    readiness_soreness: Optional[int] = None
    readiness_stress: Optional[int] = None


class SetLogResponse(BaseModel):
    """Response for a logged set."""
    id: int
    prescription_id: int
    exercise_name: str
    actual_load_lb: float
    actual_reps: int
    rpe: Optional[float] = None
    e1rm_lb: Optional[float] = None
    confidence: str
    pain_flag: bool
    set_type: str
    note: Optional[str] = None
    logged_at: Optional[str] = None


class SessionCompleteResponse(BaseModel):
    """Response when completing a session."""
    session_id: int
    status: str
    adjustments: list[dict] = []
    skip_backoffs: bool = False
    allow_extra_set: bool = False
    early_deload: bool = False
    pain_flags: list[dict] = []
    next_e1rm_adjustment: float = 0.0
    suggested_variation_swap: Optional[str] = None


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
                exercise_id=ex.id,
                session_id=db_sess.id,
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


# ---------------------------------------------------------------------------
# POST /api/sessions \u2013 Create a new session
# ---------------------------------------------------------------------------

@app.post("/api/sessions")
def create_session(req: SessionCreate):
    """Create a new session with the correct day type and block phase."""
    db = _get_session()
    try:
        # Validate day_label
        if req.day_label.upper() not in ("A", "B", "C", "D"):
            raise HTTPException(status_code=400, detail="day_label must be A, B, C, or D")

        today = datetime.date.today()
        scheduled = req.scheduled_date
        if scheduled:
            try:
                scheduled = datetime.date.fromisoformat(scheduled)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid scheduled_date format")
        else:
            scheduled = today

        # Find active program
        program = db.query(Program).filter_by(is_active=True).first()
        if not program:
            program = Program(
                athlete_id=1,
                name="Default Program",
                phase="accumulation",
                start_date=today,
                is_active=True,
            )
            db.add(program)
            db.flush()

        # Find or create block for this program
        block = db.query(Block).filter_by(program_id=program.id).first()
        if not block:
            block = Block(
                program_id=program.id,
                block_number=1,
                start_date=today,
            )
            db.add(block)
            db.flush()

        # Find or create cycle for this block
        cycle = db.query(Cycle).filter_by(block_id=block.id).first()
        if not cycle:
            cycle = Cycle(
                block_id=block.id,
                cycle_number=1,
                start_date=today,
            )
            db.add(cycle)
            db.flush()

        # Create the session
        new_session = DBSession(
            cycle_id=cycle.id,
            day_label=req.day_label.upper(),
            scheduled_date=scheduled,
            actual_date=scheduled,
            status="in_progress",
            readiness_sleep=req.readiness_sleep,
            readiness_soreness=req.readiness_soreness,
            readiness_stress=req.readiness_stress,
        )
        db.add(new_session)
        db.flush()

        # Determine block phase from program
        block_phase = program.phase

        db.commit()

        return SessionResponse(
            id=new_session.id,
            cycle_id=new_session.cycle_id,
            day_label=new_session.day_label,
            scheduled_date=str(new_session.scheduled_date),
            actual_date=str(new_session.actual_date) if new_session.actual_date else None,
            status=new_session.status,
            readiness_sleep=new_session.readiness_sleep,
            readiness_soreness=new_session.readiness_soreness,
            readiness_stress=new_session.readiness_stress,
            created_at=str(new_session.created_at) if new_session.created_at else None,
            block_phase=block_phase,
        )

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create session")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/sets \u2013 Log a set for a session
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{session_id}/sets")
def log_set(session_id: int, req: SetLogRequest):
    """Log a set with exercise, weight, reps, rpe, set_type."""
    db = _get_session()
    try:
        # Validate session exists and is in_progress
        sess = db.query(DBSession).filter_by(id=session_id).first()
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.status != "in_progress":
            raise HTTPException(status_code=400, detail="Session is not in progress")

        # Validate set_type
        valid_set_types = ("warmup", "top", "backoff", "apre")
        if req.set_type not in valid_set_types:
            raise HTTPException(
                status_code=400,
                detail=f"set_type must be one of: {', '.join(valid_set_types)}",
            )

        # Ensure exercise exists
        ex = db.query(Exercise).filter_by(name=req.exercise_name).first()
        if not ex:
            ex = Exercise(name=req.exercise_name, role="accessory", metric_type="load_reps")
            db.add(ex)
            db.flush()

        # Create prescription for this set
        pres = Prescription(
            session_id=sess.id,
            exercise_id=ex.id,
            set_number=1,
            prescribed_reps=req.reps,
            prescribed_load_lb=req.weight,
            prescribed_rpe=req.rpe,
        )
        db.add(pres)
        db.flush()

        # Calculate e1RM using RPE engine if available
        e1rm_val = None
        confidence = "low"
        try:
            if req.rpe is not None and req.rpe >= 7.0 and req.reps <= 8:
                from app.strength.rpe import e1rm as calc_e1rm
                result = calc_e1rm(req.weight, req.reps, req.rpe)
                if isinstance(result, dict):
                    e1rm_val = result.get("e1rm")
                    confidence = result.get("confidence", "high")
                else:
                    e1rm_val = float(result)
                    confidence = "high"
            elif req.rpe is not None:
                # Epley fallback for low RPE or high reps
                e1rm_val = round(req.weight * (1 + req.reps / 30.0), 1)
                confidence = "low"
            else:
                # No RPE, use Epley
                e1rm_val = round(req.weight * (1 + req.reps / 30.0), 1)
                confidence = "low"
        except Exception:
            # Fallback to Epley on any error
            e1rm_val = round(req.weight * (1 + req.reps / 30.0), 1)
            confidence = "low"

        # Create set log
        slog = SetLog(
            exercise_id=ex.id,
            session_id=sess.id,
            prescription_id=pres.id,
            actual_load_lb=req.weight,
            actual_reps=req.reps,
            rpe=req.rpe,
            e1rm_lb=e1rm_val,
            confidence=confidence,
            pain_flag=req.pain_flag,
            set_type=req.set_type,
            note=req.note,
        )
        db.add(slog)
        db.flush()

        db.commit()

        return SetLogResponse(
            id=slog.id,
            prescription_id=slog.prescription_id,
            exercise_name=req.exercise_name,
            actual_load_lb=slog.actual_load_lb,
            actual_reps=slog.actual_reps,
            rpe=slog.rpe,
            e1rm_lb=slog.e1rm_lb,
            confidence=slog.confidence,
            pain_flag=slog.pain_flag,
            set_type=slog.set_type,
            note=slog.note,
            logged_at=str(slog.logged_at) if slog.logged_at else None,
        )

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to log set")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PATCH /api/sessions/{id}/complete \u2013 Complete a session and run adjustments
# ---------------------------------------------------------------------------

@app.patch("/api/sessions/{session_id}/complete")
def complete_session(session_id: int, req: SessionCompleteRequest = None):
    """Mark a session complete and trigger adjustment rule checks."""
    db = _get_session()
    try:
        sess = db.query(DBSession).filter_by(id=session_id).first()
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.status == "completed":
            raise HTTPException(status_code=400, detail="Session already completed")

        # Update readiness if provided
        if req:
            if req.readiness_sleep is not None:
                sess.readiness_sleep = req.readiness_sleep
            if req.readiness_soreness is not None:
                sess.readiness_soreness = req.readiness_soreness
            if req.readiness_stress is not None:
                sess.readiness_stress = req.readiness_stress

        sess.status = "completed"
        db.flush()

        # Gather data for adjustment evaluation
        # Get all set logs for this session
        set_logs = (
            db.query(SetLog)
            .join(Prescription, SetLog.prescription_id == Prescription.id)
            .filter(Prescription.session_id == sess.id)
            .all()
        )

        # Find top sets and their RPEs
        top_sets = [sl for sl in set_logs if sl.set_type == "top"]
        top_set_rpe = None
        if top_sets:
            top_set_rpe = top_sets[0].rpe

        # Get target RPE from prescriptions
        target_rpe = None
        prescriptions = db.query(Prescription).filter_by(session_id=sess.id).all()
        for pres in prescriptions:
            if pres.prescribed_rpe is not None:
                target_rpe = pres.prescribed_rpe
                break

        # Collect pain flags
        pain_flags = []
        for sl in set_logs:
            if sl.pain_flag:
                ex = db.query(Exercise).filter_by(id=sl.prescription.exercise_id).first()
                ex_name = ex.name if ex else "unknown"
                pain_flags.append({"exercise": ex_name, "pain_flag": True})

        # Get e1RM history for the cycle
        cycle = db.query(Cycle).filter_by(id=sess.cycle_id).first()
        e1rm_history = []
        cycles_since_improvement = 0
        if cycle:
            # Get all sessions in this block's cycles
            all_cycles = db.query(Cycle).filter_by(block_id=cycle.block_id).order_by(Cycle.cycle_number).all()
            for c in all_cycles:
                c_sessions = db.query(DBSession).filter_by(cycle_id=c.id, status="completed").all()
                best_e1rm = 0.0
                for cs in c_sessions:
                    cs_pres = db.query(Prescription).filter_by(session_id=cs.id).all()
                    for cp in cs_pres:
                        cs_logs = db.query(SetLog).filter_by(prescription_id=cp.id).all()
                        for csl in cs_logs:
                            if csl.e1rm_lb and csl.e1rm_lb > best_e1rm:
                                best_e1rm = csl.e1rm_lb
                if best_e1rm > 0:
                    e1rm_history.append(best_e1rm)

            # Calculate cycles since improvement
            if len(e1rm_history) >= 2:
                latest = e1rm_history[-1]
                for val in reversed(e1rm_history[:-1]):
                    if val < latest:
                        break
                    cycles_since_improvement += 1

        # Evaluate adjustments
        adjustments = evaluate_adjustments(
            top_set_rpe=top_set_rpe,
            target_rpe=target_rpe,
            e1rm_history=e1rm_history if e1rm_history else None,
            cycles_since_improvement=cycles_since_improvement,
            pain_flags=pain_flags if pain_flags else None,
        )

        db.commit()

        return SessionCompleteResponse(
            session_id=sess.id,
            status=sess.status,
            adjustments=[
                {
                    "rule_type": a.rule_type.value,
                    "triggered": a.triggered,
                    "message": a.message,
                    "details": a.details,
                }
                for a in adjustments.adjustments
            ],
            skip_backoffs=adjustments.skip_backoffs,
            allow_extra_set=adjustments.allow_extra_set,
            early_deload=adjustments.early_deload,
            pain_flags=[{"exercise": name} for name in adjustments.pain_flags],
            next_e1rm_adjustment=adjustments.next_e1rm_adjustment,
            suggested_variation_swap=adjustments.suggested_variation_swap,
        )

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to complete session")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/sessions \u2013 Get session history with filters
# ---------------------------------------------------------------------------

@app.get("/api/sessions")
def get_sessions(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    day_type: Optional[str] = None,
    block_phase: Optional[str] = None,
):
    """Get session history filtered by date range, day type, or block phase."""
    db = _get_session()
    try:
        query = db.query(DBSession)

        # Filter by date range
        if date_from:
            try:
                query = query.filter(DBSession.scheduled_date >= datetime.date.fromisoformat(date_from))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_from format")
        if date_to:
            try:
                query = query.filter(DBSession.scheduled_date <= datetime.date.fromisoformat(date_to))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_to format")

        # Filter by day type
        if day_type:
            query = query.filter(DBSession.day_label == day_type.upper())

        # Filter by block phase (join through cycle -> block -> program)
        if block_phase:
            query = (
                query
                .join(Cycle, DBSession.cycle_id == Cycle.id)
                .join(Block, Cycle.block_id == Block.id)
                .join(Program, Block.program_id == Program.id)
                .filter(Program.phase == block_phase)
            )

        sessions = query.order_by(DBSession.scheduled_date.desc()).all()

        result = []
        for sess in sessions:
            # Get block phase
            cycle = db.query(Cycle).filter_by(id=sess.cycle_id).first()
            block_phase_val = None
            if cycle:
                block = db.query(Block).filter_by(id=cycle.block_id).first()
                if block:
                    program = db.query(Program).filter_by(id=block.program_id).first()
                    if program:
                        block_phase_val = program.phase

            result.append(SessionResponse(
                id=sess.id,
                cycle_id=sess.cycle_id,
                day_label=sess.day_label,
                scheduled_date=str(sess.scheduled_date),
                actual_date=str(sess.actual_date) if sess.actual_date else None,
                status=sess.status,
                readiness_sleep=sess.readiness_sleep,
                readiness_soreness=sess.readiness_soreness,
                readiness_stress=sess.readiness_stress,
                created_at=str(sess.created_at) if sess.created_at else None,
                block_phase=block_phase_val,
            ))

        return result

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get sessions")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

class SettingRequest(BaseModel):
    """Request to update a setting."""
    key: str
    value: str


class SettingsResponse(BaseModel):
    """Response for settings."""
    key: str
    value: str


class AthleteUpdate(BaseModel):
    """Request to update athlete profile."""
    name: Optional[str] = None
    height_cm: Optional[float] = None
    age: Optional[int] = None
    training_age_months: Optional[int] = None
    units: Optional[str] = None
    plate_increment_lb: Optional[float] = None
    dumbbell_max_lb: Optional[int] = None


class BodyweightEntry(BaseModel):
    """Request to log bodyweight."""
    weight_lb: float
    date: Optional[str] = None
    notes: Optional[str] = None


class BodyweightResponse(BaseModel):
    """Response for bodyweight entry."""
    id: int
    weight_lb: float
    date: str
    notes: Optional[str] = None


class ImportRequest(BaseModel):
    """Request to import CSV data."""
    csv_data: str


@app.get("/api/settings")
def get_settings():
    """Get all settings for the athlete."""
    from app.strength.settings import load_all_settings, ensure_defaults
    db = _get_session()
    try:
        ensure_defaults(db)
        settings = load_all_settings(db)
        return [{"key": k, "value": v} for k, v in settings.items()]
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get settings")
    finally:
        db.close()


@app.patch("/api/settings")
def update_setting(req: SettingRequest):
    """Update a single setting."""
    from app.strength.settings import set_setting
    db = _get_session()
    try:
        row = set_setting(db, req.key, req.value)
        db.commit()
        return {"key": row.key, "value": row.value}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update setting")
    finally:
        db.close()


@app.patch("/api/settings/bulk")
def bulk_update_settings(req: dict):
    """Update multiple settings at once."""
    from app.strength.settings import save_all_settings, VALID_KEYS
    db = _get_session()
    try:
        # Filter to valid keys only
        valid_updates = {k: v for k, v in req.items() if k in VALID_KEYS}
        save_all_settings(db, valid_updates)
        db.commit()
        return {"updated": len(valid_updates)}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update settings")
    finally:
        db.close()


@app.get("/api/settings/export/csv")
def export_settings_csv():
    """Export all settings as CSV."""
    from app.strength.settings import load_all_settings, ensure_defaults
    from fastapi.responses import Response
    import csv
    import io
    db = _get_session()
    try:
        ensure_defaults(db)
        settings = load_all_settings(db)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["key", "value"])
        writer.writeheader()
        for key, value in settings.items():
            writer.writerow({"key": key, "value": value})
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=settings.csv"},
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to export settings")
    finally:
        db.close()


@app.post("/api/settings/import/csv")
def import_settings_csv(req: ImportRequest):
    """Import settings from CSV backup."""
    from app.strength.settings import save_all_settings, VALID_KEYS
    import csv
    import io
    db = _get_session()
    try:
        reader = csv.DictReader(io.StringIO(req.csv_data))
        settings = {}
        for row in reader:
            key = row.get("key", "").strip()
            if key in VALID_KEYS:
                settings[key] = row.get("value", "").strip()
        save_all_settings(db, settings)
        db.commit()
        return {"imported": len(settings)}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to import settings")
    finally:
        db.close()


@app.get("/api/athlete")
def get_athlete():
    """Get athlete profile."""
    from app.database import Athlete
    db = _get_session()
    try:
        athlete = db.query(Athlete).first()
        if not athlete:
            raise HTTPException(status_code=404, detail="No athlete found")
        return {
            "id": athlete.id,
            "name": athlete.name,
            "height_cm": athlete.height_cm,
            "age": athlete.age,
            "training_age_months": athlete.training_age_months,
            "units": athlete.units,
            "plate_increment_lb": athlete.plate_increment_lb,
            "dumbbell_max_lb": athlete.dumbbell_max_lb,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get athlete")
    finally:
        db.close()


@app.patch("/api/athlete")
def update_athlete(req: AthleteUpdate):
    """Update athlete profile."""
    from app.database import Athlete
    db = _get_session()
    try:
        athlete = db.query(Athlete).first()
        if not athlete:
            raise HTTPException(status_code=404, detail="No athlete found")

        if req.name is not None:
            athlete.name = req.name
        if req.height_cm is not None:
            athlete.height_cm = req.height_cm
        if req.age is not None:
            athlete.age = req.age
        if req.training_age_months is not None:
            athlete.training_age_months = req.training_age_months
        if req.units is not None:
            athlete.units = req.units
        if req.plate_increment_lb is not None:
            athlete.plate_increment_lb = req.plate_increment_lb
        if req.dumbbell_max_lb is not None:
            athlete.dumbbell_max_lb = req.dumbbell_max_lb

        db.commit()
        return {
            "id": athlete.id,
            "name": athlete.name,
            "height_cm": athlete.height_cm,
            "age": athlete.age,
            "training_age_months": athlete.training_age_months,
            "units": athlete.units,
            "plate_increment_lb": athlete.plate_increment_lb,
            "dumbbell_max_lb": athlete.dumbbell_max_lb,
        }
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update athlete")
    finally:
        db.close()


@app.get("/api/bodyweight")
def get_bodyweight():
    """Get all bodyweight entries."""
    from app.database import Bodyweight, Athlete
    db = _get_session()
    try:
        athlete = db.query(Athlete).first()
        if not athlete:
            raise HTTPException(status_code=404, detail="No athlete found")
        entries = (
            db.query(Bodyweight)
            .filter_by(athlete_id=athlete.id)
            .order_by(Bodyweight.date.desc())
            .all()
        )
        return [
            BodyweightResponse(
                id=e.id,
                weight_lb=e.weight_lb,
                date=e.date.isoformat() if e.date else "",
                notes=e.notes,
            )
            for e in entries
        ]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get bodyweight")
    finally:
        db.close()


@app.post("/api/bodyweight")
def add_bodyweight(req: BodyweightEntry):
    """Log a bodyweight entry."""
    from app.database import Bodyweight, Athlete
    import datetime as dt
    db = _get_session()
    try:
        athlete = db.query(Athlete).first()
        if not athlete:
            raise HTTPException(status_code=404, detail="No athlete found")

        entry_date = dt.date.today()
        if req.date:
            try:
                entry_date = dt.date.fromisoformat(req.date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format")

        entry = Bodyweight(
            athlete_id=athlete.id,
            weight_lb=req.weight_lb,
            date=entry_date,
            notes=req.notes,
        )
        db.add(entry)
        db.commit()
        return BodyweightResponse(
            id=entry.id,
            weight_lb=entry.weight_lb,
            date=entry.date.isoformat(),
            notes=entry.notes,
        )
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add bodyweight")
    finally:
        db.close()


@app.get("/api/export/csv")
def export_csv():
    """Export all session data as CSV."""
    from app.strength.settings import export_sessions_csv
    from fastapi.responses import Response
    db = _get_session()
    try:
        csv_data = export_sessions_csv(db)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=sessions.csv"},
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to export CSV")
    finally:
        db.close()


@app.post("/api/import/csv")
def import_csv(req: ImportRequest):
    """Import session data from CSV backup."""
    from app.strength.settings import import_sessions_csv
    db = _get_session()
    try:
        result = import_sessions_csv(db, req.csv_data)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to import CSV")
    finally:
        db.close()
