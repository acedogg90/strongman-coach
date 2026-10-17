"""Warm-up set generation and fatigue-percent back-off set logging.

Warm-ups are auto-suggested as a progression toward the top-set weight:
    bar (empty) → 40% → 60% → 80% → top set

Back-off sets use the RTS fatigue-percent table (2–7% drop) with a
configurable drop percentage per block phase:

    Accumulation:      5–6 %
    Intensification:   4–5 %
    Realization:       2–3 %
    Deload:            0 %

All calculations are pure functions – no DB or framework dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Standard Olympic bar weight in pounds
BAR_WEIGHT_LB: float = 45.0

# Default warm-up progression percentages (of top-set weight)
# bar → 40% → 60% → 80% → 100% (top set)
WARMUP_PERCENTAGES: list[float] = [0.0, 0.4, 0.6, 0.8]

# RTS fatigue-percent drop table per block phase.
# Each phase maps to a (min_drop, max_drop) tuple.
# The midpoint is used as the default drop percentage.
RTS_DROP_TABLE: dict[str, tuple[float, float]] = {
    "accumulation": (5.0, 6.0),
    "intensification": (4.0, 5.0),
    "realization": (2.0, 3.0),
    "deload": (0.0, 0.0),
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class WarmupSet:
    """A single warm-up set in the progression."""

    load_lb: float
    reps: int = 3
    is_empty_bar: bool = False


@dataclass
class BackoffSet:
    """A back-off set derived from the top-set weight."""

    exercise: str
    weight_lb: float
    reps: int
    rpe: float | None = None
    notes: str = ""
    drop_pct: float = 0.0


# ---------------------------------------------------------------------------
# Warm-up generation
# ---------------------------------------------------------------------------


def generate_warmups(
    top_set_weight: float,
    bar_weight: float = BAR_WEIGHT_LB,
    plate_increment: float = 2.5,
    reps: int = 3,
) -> list[WarmupSet]:
    """Generate a warm-up progression toward *top_set_weight*.

    The progression is:
        1. Empty bar (bar_weight)
        2. 40 % of top-set weight
        3. 60 % of top-set weight
        4. 80 % of top-set weight

    Loads are rounded **down** to the nearest *plate_increment* so the
    athlete can actually load the bar.  If a calculated warm-up load is
    less than or equal to the bar weight, that step is skipped (the empty
    bar already covers it).

    Parameters
    ----------
    top_set_weight : float
        The working / top-set weight in pounds.
    bar_weight : float
        Weight of the bar in pounds (default 45 lb Olympic bar).
    plate_increment : float
        Smallest plate step for rounding (default 2.5 lb).
    reps : int
        Reps for each warm-up set (default 3).

    Returns
    -------
    list[WarmupSet]
        Ordered list of warm-up sets from lightest to heaviest.
    """
    if top_set_weight <= 0:
        raise ValueError(f"top_set_weight must be positive, got {top_set_weight}")

    warmups: list[WarmupSet] = []

    # Step 1: empty bar
    warmups.append(WarmupSet(load_lb=bar_weight, reps=reps, is_empty_bar=True))

    # Steps 2–4: percentage-based warm-ups
    for pct in WARMUP_PERCENTAGES:
        if pct == 0.0:
            # Already covered by the empty-bar step
            continue
        raw_load = top_set_weight * pct
        # Round down to plate increment
        rounded = math.floor(raw_load / plate_increment) * plate_increment

        # Skip if rounded load is at or below bar weight
        if rounded <= bar_weight:
            continue

        warmups.append(WarmupSet(load_lb=rounded, reps=reps, is_empty_bar=False))

    return warmups


# ---------------------------------------------------------------------------
# Back-off set calculation
# ---------------------------------------------------------------------------


def get_default_drop_pct(phase: str) -> float:
    """Return the default fatigue drop percentage for a block phase.

    Uses the midpoint of the RTS table range for the given phase.

    Parameters
    ----------
    phase : str
        One of ``'accumulation'``, ``'intensification'``,
        ``'realization'``, or ``'deload'``.

    Returns
    -------
    float
        Default drop percentage (e.g. 5.5 for accumulation).

    Raises
    ------
    ValueError
        If *phase* is not a recognised block phase.
    """
    phase_lower = phase.lower()
    if phase_lower not in RTS_DROP_TABLE:
        valid = ", ".join(sorted(RTS_DROP_TABLE.keys()))
        raise ValueError(
            f"Unknown block phase {phase!r}. Valid phases: {valid}"
        )
    lo, hi = RTS_DROP_TABLE[phase_lower]
    return (lo + hi) / 2.0


def calculate_backoff(
    top_set_weight: float,
    drop_pct: float,
    exercise: str = "",
    reps: int = 3,
    rpe: float | None = None,
    notes: str = "",
) -> BackoffSet:
    """Calculate a back-off set weight from the top-set weight.

    The back-off weight is computed as::

        backoff_weight = top_set_weight × (1 - drop_pct / 100)

    Parameters
    ----------
    top_set_weight : float
        The top-set working weight in pounds.
    drop_pct : float
        Fatigue drop percentage (e.g. 5.5 for a 5.5 % drop).
    exercise : str
        Name of the exercise (stored for logging).
    reps : int
        Reps for the back-off set.
    rpe : float or None
        Target RPE for the back-off set.
    notes : str
        Optional notes for the back-off set.

    Returns
    -------
    BackoffSet
        A back-off set with computed weight.

    Raises
    ------
    ValueError
        If *top_set_weight* is not positive or *drop_pct* is out of range.
    """
    if top_set_weight <= 0:
        raise ValueError(f"top_set_weight must be positive, got {top_set_weight}")
    if drop_pct < 0 or drop_pct > 100:
        raise ValueError(
            f"drop_pct must be between 0 and 100, got {drop_pct}"
        )

    backoff_weight = top_set_weight * (1.0 - drop_pct / 100.0)

    return BackoffSet(
        exercise=exercise,
        weight_lb=round(backoff_weight, 1),
        reps=reps,
        rpe=rpe,
        notes=notes,
        drop_pct=drop_pct,
    )


def calculate_backoff_series(
    top_set_weight: float,
    drop_pct: float,
    exercise: str = "",
    reps: int = 3,
    rpe: float | None = None,
    notes: str = "",
    max_sets: int = 6,
) -> list[BackoffSet]:
    """Generate a series of back-off sets with increasing fatigue drop.

    Each successive set increases the drop by the configured *drop_pct*,
    up to *max_sets* total back-off sets.

    Parameters
    ----------
    top_set_weight : float
        The top-set working weight in pounds.
    drop_pct : float
        Base fatigue drop percentage; each subsequent set adds this
        amount (e.g. 5 %, 10 %, 15 % …).
    exercise : str
        Name of the exercise.
    reps : int
        Reps for each back-off set.
    rpe : float or None
        Target RPE for back-off sets.
    notes : str
        Optional notes.
    max_sets : int
        Maximum number of back-off sets (default 6, per spec).

    Returns
    -------
    list[BackoffSet]
        Ordered list of back-off sets.
    """
    sets: list[BackoffSet] = []
    for i in range(1, max_sets + 1):
        cumulative_drop = drop_pct * i
        if cumulative_drop >= 100:
            break
        sets.append(
            calculate_backoff(
                top_set_weight=top_set_weight,
                drop_pct=cumulative_drop,
                exercise=exercise,
                reps=reps,
                rpe=rpe,
                notes=notes,
            )
        )
    return sets
