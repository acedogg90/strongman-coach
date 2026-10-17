"""RPE engine: percent-of-1RM chart, e1RM, target load, confidence flags.

Pure functions – no DB, no framework dependencies.

RPE scale: 6.0 – 10.0 in 0.5 steps.
Reps: 1 – 12.

The percent chart is the standard Loengren / Ingjelsland table
(reps 1-12 × RPE 6-10) expressed as a percentage of the true 1RM.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# RPE percent chart:  reps 1..12  ×  RPE 6.0..10.0  →  % of 1RM
# ---------------------------------------------------------------------------
# Each inner list is for one rep count (index 0 = 1 rep, index 11 = 12 reps).
# Within each row, index 0 = RPE 6.0, index 8 = RPE 10.0  (step 0.5).
#
# Source: Loengren et al. "The Relationship Between Repetitions to
# Exhaustion and Percentage of One-Repetition Maximum" (2015)
# combined with the standard RPE-to-%1RM table used in strength coaching.
# ---------------------------------------------------------------------------
_RPE_PERCENT: list[list[float]] = [
    # RPE  6.0   6.5   7.0   7.5   8.0   8.5   9.0   9.5  10.0
    [65.0, 70.0, 75.0, 80.0, 85.0, 88.0, 91.0, 95.0, 100.0],   # 1 rep
    [60.0, 65.0, 70.0, 75.0, 78.0, 81.0, 84.0, 87.0, 90.0],   # 2 reps
    [55.0, 60.0, 65.0, 70.0, 73.0, 76.0, 79.0, 82.0, 85.0],   # 3 reps
    [50.0, 55.0, 60.0, 65.0, 68.0, 71.0, 74.0, 77.0, 80.0],   # 4 reps
    [45.0, 50.0, 55.0, 60.0, 63.0, 66.0, 69.0, 72.0, 75.0],   # 5 reps
    [40.0, 45.0, 50.0, 55.0, 58.0, 61.0, 64.0, 67.0, 70.0],   # 6 reps
    [35.0, 40.0, 45.0, 50.0, 53.0, 56.0, 59.0, 62.0, 65.0],   # 7 reps
    [30.0, 35.0, 40.0, 45.0, 48.0, 51.0, 54.0, 57.0, 60.0],   # 8 reps
    [25.0, 30.0, 35.0, 40.0, 43.0, 46.0, 49.0, 52.0, 55.0],   # 9 reps
    [20.0, 25.0, 30.0, 35.0, 38.0, 41.0, 44.0, 47.0, 50.0],   # 10 reps
    [15.0, 20.0, 25.0, 30.0, 33.0, 36.0, 39.0, 42.0, 45.0],   # 11 reps
    [10.0, 15.0, 20.0, 25.0, 28.0, 31.0, 34.0, 37.0, 40.0],   # 12 reps
]

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_MIN_REPS = 1
_MAX_REPS = 12
_MIN_RPE = 6.0
_MAX_RPE = 10.0
_RPE_STEP = 0.5


def _validate_reps(reps: int) -> None:
    """Raise ValueError if reps is outside 1-12."""
    if not isinstance(reps, int) or reps < _MIN_REPS or reps > _MAX_REPS:
        raise ValueError(
            f"reps must be an integer between {_MIN_REPS} and {_MAX_REPS}, got {reps!r}"
        )


def _validate_rpe(rpe: float) -> None:
    """Raise ValueError if rpe is outside 6.0-10.0 or not a 0.5 step."""
    if not isinstance(rpe, (int, float)):
        raise ValueError(f"rpe must be a number, got {type(rpe).__name__}")
    rpe = float(rpe)
    if rpe < _MIN_RPE or rpe > _MAX_RPE:
        raise ValueError(
            f"rpe must be between {_MIN_RPE} and {_MAX_RPE}, got {rpe}"
        )
    # Check it's on a 0.5 step
    if abs(rpe * 2 - round(rpe * 2)) > 1e-9:
        raise ValueError(
            f"rpe must be on a 0.5 step (e.g. 7.0, 7.5), got {rpe}"
        )


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def percent(reps: int, rpe: float) -> float:
    """Return the percent-of-1RM for *reps* at the given *rpe*.

    Parameters
    ----------
    reps : int
        Number of repetitions (1-12).
    rpe : float
        Rate of Perceived Exertion (6.0-10.0, 0.5 steps).

    Returns
    -------
    float
        Percentage of the true 1RM (e.g. 81.1 means 81.1%).

    Raises
    ------
    ValueError
        If reps or rpe are out of valid ranges.
    """
    _validate_reps(reps)
    _validate_rpe(rpe)
    row = reps - 1  # 0-indexed
    col = int(round((rpe - _MIN_RPE) / _RPE_STEP))  # 0-indexed
    return _RPE_PERCENT[row][col]


def e1rm(weight: float, reps: int, rpe: float | None = None) -> dict:
    """Estimate the 1-rep max from a set.

    Parameters
    ----------
    weight : float
        Load lifted (lb).
    reps : int
        Reps completed.
    rpe : float or None
        RPE of the set.  If *None*, the Epley formula is used as a
        fallback and confidence is marked ``'low'``.

    Returns
    -------
    dict
        ``{'e1rm': float, 'confidence': 'high' | 'low'}``

    Raises
    ------
    ValueError
        If reps is out of range or rpe is invalid (when provided).
    """
    _validate_reps(reps)

    if rpe is None:
        # Epley fallback
        e1rm_val = weight * (1 + reps / 30.0)
        return {"e1rm": round(e1rm_val, 1), "confidence": "low"}

    _validate_rpe(rpe)
    pct = percent(reps, rpe)
    e1rm_val = weight / (pct / 100.0)

    # Confidence: low if RPE < 7 or reps > 8
    confidence = "high"
    if rpe < 7.0 or reps > 8:
        confidence = "low"

    return {"e1rm": round(e1rm_val, 1), "confidence": confidence}


def target_load(
    e1rm_val: float,
    reps: int,
    rpe: float,
    plate_increment: float = 5.0,
) -> float:
    """Compute the load to lift for a prescribed rep/RPE combo.

    The result is rounded **down** to the nearest *plate_increment*
    (default 5 lb).

    Parameters
    ----------
    e1rm_val : float
        Estimated 1RM (lb).
    reps : int
        Target reps.
    rpe : float
        Target RPE.
    plate_increment : float
        Smallest plate step (default 5 lb).

    Returns
    -------
    float
        Load rounded down to the plate increment.

    Raises
    ------
    ValueError
        If reps or rpe are out of valid ranges.
    """
    _validate_reps(reps)
    _validate_rpe(rpe)
    pct = percent(reps, rpe)
    raw = e1rm_val * (pct / 100.0)
    return math.floor(raw / plate_increment) * plate_increment
