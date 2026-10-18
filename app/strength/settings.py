"""Settings persistence layer and CSV export/import utilities.

Provides:
- get_setting / set_setting helpers that read/write the `settings` table
- load_all_settings / save_all_settings for bulk operations
- CSV export of all session data (set_log + event_log)
- CSV import to restore from backup

All functions are pure or use the DB session passed in – no global state.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy.orm import Session

from app.database import (
    Athlete,
    Bodyweight,
    EventLog,
    Exercise,
    Prescription,
    Settings,
    SetLog,
)

# ---------------------------------------------------------------------------
# Default settings keyed by name
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    # Athlete profile
    "bodyweight": "0",
    "goal_weight": "0",
    # Block phase drop percentages (midpoints of RTS ranges)
    "drop_pct_accumulation": "5.5",
    "drop_pct_intensification": "4.5",
    "drop_pct_realization": "2.5",
    # Target RPE per cycle (default 8.0 for all cycles)
    "target_rpe_cycle_1": "8.0",
    "target_rpe_cycle_2": "8.5",
    "target_rpe_cycle_3": "9.0",
    # Notification settings
    "rest_timer_notifications": "true",
    "workout_reminders": "true",
    # Safety
    "safety_notice_seen": "false",
    # Existing defaults
    "units": "lb",
    "weight_class": "105",
    "benchmarks": "{}",
}

# Valid setting keys
VALID_KEYS = set(DEFAULT_SETTINGS.keys())

# ---------------------------------------------------------------------------
# Setting helpers
# ---------------------------------------------------------------------------


def get_athlete_id(session: Session) -> int:
    """Return the athlete id (there is only one athlete)."""
    athlete = session.query(Athlete).first()
    if athlete is None:
        raise ValueError("No athlete found – run migration first")
    return athlete.id


def get_setting(session: Session, key: str, default: str | None = None) -> str:
    """Read a single setting value by key.

    Returns *default* if the key does not exist in the database.
    """
    athlete_id = get_athlete_id(session)
    row = (
        session.query(Settings)
        .filter_by(athlete_id=athlete_id, key=key)
        .first()
    )
    if row is not None:
        return row.value
    if default is not None:
        return default
    return DEFAULT_SETTINGS.get(key, "")


def set_setting(session: Session, key: str, value: str) -> Settings:
    """Upsert a single setting row.

    Returns the (new or updated) Settings row.
    """
    athlete_id = get_athlete_id(session)
    row = (
        session.query(Settings)
        .filter_by(athlete_id=athlete_id, key=key)
        .first()
    )
    if row is None:
        row = Settings(athlete_id=athlete_id, key=key, value=value)
        session.add(row)
    else:
        row.value = value
    session.flush()
    return row


def load_all_settings(session: Session) -> dict[str, str]:
    """Return a dict of all settings for the athlete."""
    athlete_id = get_athlete_id(session)
    rows = session.query(Settings).filter_by(athlete_id=athlete_id).all()
    return {row.key: row.value for row in rows}


def save_all_settings(session: Session, settings: dict[str, str]) -> None:
    """Bulk-save settings. Upserts each key/value pair."""
    for key, value in settings.items():
        set_setting(session, key, value)
    session.flush()


def ensure_defaults(session: Session) -> None:
    """Seed missing default settings if they don't exist."""
    current = load_all_settings(session)
    for key, value in DEFAULT_SETTINGS.items():
        if key not in current:
            set_setting(session, key, value)
    session.flush()

# ---------------------------------------------------------------------------
# CSV Export / Import
# ---------------------------------------------------------------------------


def export_sessions_csv(session: Session) -> str:
    """Export all session data as CSV.

    Returns a CSV string with columns:
    session_date, day_label, exercise_name, set_number,
    actual_load_lb, actual_reps, rpe, e1rm_lb, confidence,
    pain_flag, note, logged_at
    """
    set_logs = session.query(SetLog).join(Prescription).join(Exercise).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "session_date", "day_label", "exercise_name", "set_number",
        "actual_load_lb", "actual_reps", "rpe", "e1rm_lb", "confidence",
        "pain_flag", "note", "logged_at",
    ])

    for slog in set_logs:
        pres = slog.prescription
        writer.writerow([
            pres.session.scheduled_date.isoformat() if pres.session.scheduled_date else "",
            pres.session.day_label,
            pres.exercise.name,
            pres.set_number,
            slog.actual_load_lb,
            slog.actual_reps,
            slog.rpe if slog.rpe is not None else "",
            slog.e1rm_lb if slog.e1rm_lb is not None else "",
            slog.confidence,
            slog.pain_flag,
            slog.note or "",
            slog.logged_at.isoformat() if slog.logged_at else "",
        ])

    return output.getvalue()


def import_sessions_csv(session: Session, csv_data: str) -> dict[str, int]:
    """Import session data from CSV backup.

    Creates exercises, prescriptions, and set_logs as needed.
    Returns a dict with counts: {'exercises': N, 'set_logs': N}.

    The CSV must have the same columns as produced by export_sessions_csv.
    """
    reader = csv.DictReader(io.StringIO(csv_data))

    exercise_map: dict[str, int] = {}
    set_log_count = 0

    for row in reader:
        # Resolve exercise
        ex_name = row.get("exercise_name", "").strip()
        if not ex_name:
            continue

        ex = session.query(Exercise).filter_by(name=ex_name).first()
        if ex is None:
            ex = Exercise(name=ex_name, role="accessory", metric_type="load_reps")
            session.add(ex)
            session.flush()
        exercise_map[ex_name] = ex.id

        # Parse values
        actual_load = float(row["actual_load_lb"]) if row.get("actual_load_lb") else 0.0
        actual_reps = int(row["actual_reps"]) if row.get("actual_reps") else 1
        rpe_val = float(row["rpe"]) if row.get("rpe") else None
        e1rm_val = float(row["e1rm_lb"]) if row.get("e1rm_lb") else None
        confidence = row.get("confidence", "low")
        pain_flag = row.get("pain_flag", "false").lower() in ("true", "1", "yes")
        note = row.get("note", "") or ""

        # Compute e1RM if missing (Epley fallback)
        if e1rm_val is None and actual_load > 0 and actual_reps > 0:
            e1rm_val = actual_load * (1 + actual_reps / 30.0)

        # Create set_log directly (bypass prescription for import simplicity)
        # We need a prescription to attach to, so create one
        from app.database import Session as DBSession, Program, Block, Cycle

        # Find or create a session for the date
        sched_date_str = row.get("session_date", "").strip()
        if sched_date_str:
            import datetime
            sched_date = datetime.date.fromisoformat(sched_date_str)
        else:
            sched_date = None

        day_label = row.get("day_label", "A") or "A"

        # Find existing session or create one
        db_sess = session.query(DBSession).filter_by(
            scheduled_date=sched_date,
            day_label=day_label,
        ).first()

        if db_sess is None:
            # Need a program/block/cycle
            program = session.query(Program).filter_by(is_active=True).first()
            if not program:
                program = Program(
                    athlete_id=get_athlete_id(session),
                    name="Imported Data",
                    phase="accumulation",
                    start_date=sched_date or datetime.date.today(),
                    is_active=True,
                )
                session.add(program)
                session.flush()

            block = session.query(Block).filter_by(program_id=program.id).first()
            if not block:
                block = Block(
                    program_id=program.id,
                    block_number=1,
                    start_date=sched_date or datetime.date.today(),
                )
                session.add(block)
                session.flush()

            cycle = session.query(Cycle).filter_by(block_id=block.id).first()
            if not cycle:
                cycle = Cycle(
                    block_id=block.id,
                    cycle_number=1,
                    start_date=sched_date or datetime.date.today(),
                )
                session.add(cycle)
                session.flush()

            db_sess = DBSession(
                cycle_id=cycle.id,
                day_label=day_label,
                scheduled_date=sched_date,
                status="completed",
            )
            session.add(db_sess)
            session.flush()

        # Create prescription
        pres = Prescription(
            session_id=db_sess.id,
            exercise_id=exercise_map[ex_name],
            set_number=int(row.get("set_number", 1)) if row.get("set_number") else 1,
            prescribed_reps=actual_reps,
            prescribed_load_lb=actual_load,
        )
        session.add(pres)
        session.flush()

        # Create set_log
        slog = SetLog(
            prescription_id=pres.id,
            actual_load_lb=actual_load,
            actual_reps=actual_reps,
            rpe=rpe_val,
            e1rm_lb=e1rm_val,
            confidence=confidence,
            pain_flag=pain_flag,
            note=note,
        )
        session.add(slog)
        set_log_count += 1

    return {"exercises": len(exercise_map), "set_logs": set_log_count}
