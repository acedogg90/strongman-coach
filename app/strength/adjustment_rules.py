"""Adjustment rules engine for Strongman Coach.

Pure functions — no DB, no framework dependencies.

Rules implemented:
1. Top-set RPE too high (≥ target + 1.0): skip back-offs, lower next e1RM
2. Top-set under target (< target - 1.0): allow one extra working set (max 2 attempts)
3. e1RM flat/down for 3 consecutive cycles: trigger early deload + variation swap
4. Pain flag on any set: ends that lift for the day, shows on dashboard
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class AdjustmentType(str, Enum):
    """Types of adjustment rules that can fire."""
    SKIP_BACKOFFS = "skip_backoffs"
    EXTRA_SET = "extra_set"
    EARLY_DELOAD = "early_deload"
    PAIN_FLAG = "pain_flag"


@dataclass
class AdjustmentResult:
    """Result of evaluating a single adjustment rule."""
    rule_type: AdjustmentType
    triggered: bool
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class SessionAdjustment:
    """Complete adjustment evaluation for a session."""
    adjustments: list[AdjustmentResult] = field(default_factory=list)
    skip_backoffs: bool = False
    allow_extra_set: bool = False
    early_deload: bool = False
    pain_flags: list[str] = field(default_factory=list)
    next_e1rm_adjustment: float = 0.0  # lb adjustment for next session
    suggested_variation_swap: Optional[str] = None


# ---------------------------------------------------------------------------
# Rule 1: Top-set RPE too high → skip back-offs, lower next e1RM
# ---------------------------------------------------------------------------

def check_top_set_rpe_too_high(
    actual_rpe: float,
    target_rpe: float,
    threshold: float = 1.0,
) -> AdjustmentResult:
    """If top-set RPE >= target + threshold, skip back-offs and flag session.

    Parameters
    ----------
    actual_rpe : float
        The RPE logged for the top set.
    target_rpe : float
        The prescribed RPE for the top set.
    threshold : float
        How much above target triggers the rule (default 1.0).

    Returns
    -------
    AdjustmentResult
        With triggered=True if the rule fires.
    """
    triggered = actual_rpe >= target_rpe + threshold
    if triggered:
        return AdjustmentResult(
            rule_type=AdjustmentType.SKIP_BACKOFFS,
            triggered=True,
            message=f"Top-set RPE {actual_rpe} >= target {target_rpe} + {threshold}: skip back-offs, lower next e1RM",
            details={
                "actual_rpe": actual_rpe,
                "target_rpe": target_rpe,
                "skip_backoffs": True,
            },
        )
    return AdjustmentResult(
        rule_type=AdjustmentType.SKIP_BACKOFFS,
        triggered=False,
        message="",
        details={},
    )


# ---------------------------------------------------------------------------
# Rule 2: Top-set RPE under target → allow extra working set
# ---------------------------------------------------------------------------

def check_top_set_under_target(
    actual_rpe: float,
    target_rpe: float,
    threshold: float = 1.0,
    extra_set_attempts: int = 0,
    max_attempts: int = 2,
) -> AdjustmentResult:
    """If top-set RPE < target - threshold, allow one extra working set.

    Max 2 attempts total (original + extras).

    Parameters
    ----------
    actual_rpe : float
        The RPE logged for the top set.
    target_rpe : float
        The prescribed RPE for the top set.
    threshold : float
        How much below target triggers the rule (default 1.0).
    extra_set_attempts : int
        How many extra sets have already been attempted.
    max_attempts : int
        Maximum extra set attempts allowed (default 2).

    Returns
    -------
    AdjustmentResult
        With triggered=True if the rule fires and attempts remain.
    """
    triggered = actual_rpe < target_rpe - threshold and extra_set_attempts < max_attempts
    if triggered:
        return AdjustmentResult(
            rule_type=AdjustmentType.EXTRA_SET,
            triggered=True,
            message=f"Top-set RPE {actual_rpe} < target {target_rpe} - {threshold}: allow extra working set",
            details={
                "actual_rpe": actual_rpe,
                "target_rpe": target_rpe,
                "extra_set_allowed": True,
                "attempts_remaining": max_attempts - extra_set_attempts,
            },
        )
    return AdjustmentResult(
        rule_type=AdjustmentType.EXTRA_SET,
        triggered=False,
        message="",
        details={},
    )


# ---------------------------------------------------------------------------
# Rule 3: e1RM flat/down for 3 consecutive cycles → early deload
# ---------------------------------------------------------------------------

def check_e1rm_stall(
    e1rm_history: list[float],
    cycles_since_improvement: int,
    stall_threshold: int = 3,
) -> AdjustmentResult:
    """If e1RM is flat or down for 3 consecutive cycles, trigger early deload.

    Parameters
    ----------
    e1rm_history : list[float]
        List of e1RM values per cycle, most recent last.
    cycles_since_improvement : int
        Number of cycles since e1RM last improved.
    stall_threshold : int
        Number of cycles without improvement to trigger deload (default 3).

    Returns
    -------
    AdjustmentResult
        With triggered=True if the rule fires.
    """
    triggered = cycles_since_improvement >= stall_threshold
    if triggered:
        return AdjustmentResult(
            rule_type=AdjustmentType.EARLY_DELOAD,
            triggered=True,
            message=f"e1RM flat/down for {cycles_since_improvement} cycles (≥ {stall_threshold}): trigger early deload, suggest variation swap",
            details={
                "cycles_stalled": cycles_since_improvement,
                "e1rm_history": e1rm_history,
                "early_deload": True,
            },
        )
    return AdjustmentResult(
        rule_type=AdjustmentType.EARLY_DELOAD,
        triggered=False,
        message="",
        details={},
    )


# ---------------------------------------------------------------------------
# Rule 4: Pain flag on any set → end lift for the day
# ---------------------------------------------------------------------------

def check_pain_flag(
    pain_flag: bool,
    exercise_name: str = "",
) -> AdjustmentResult:
    """If pain flag is set on any set, end that lift for the day.

    Parameters
    ----------
    pain_flag : bool
        Whether the set was flagged for pain.
    exercise_name : str
        Name of the exercise (for reporting).

    Returns
    -------
    AdjustmentResult
        With triggered=True if pain flag is set.
    """
    triggered = pain_flag
    if triggered:
        return AdjustmentResult(
            rule_type=AdjustmentType.PAIN_FLAG,
            triggered=True,
            message=f"Pain flag on {exercise_name}: end lift for the day",
            details={
                "exercise": exercise_name,
                "pain_flag": True,
                "end_lift": True,
            },
        )
    return AdjustmentResult(
        rule_type=AdjustmentType.PAIN_FLAG,
        triggered=False,
        message="",
        details={},
    )


# ---------------------------------------------------------------------------
# Aggregate evaluator
# ---------------------------------------------------------------------------

def evaluate_adjustments(
    top_set_rpe: Optional[float],
    target_rpe: Optional[float],
    extra_set_attempts: int = 0,
    e1rm_history: Optional[list[float]] = None,
    cycles_since_improvement: int = 0,
    pain_flags: Optional[list[dict]] = None,
) -> SessionAdjustment:
    """Evaluate all adjustment rules for a session.

    Parameters
    ----------
    top_set_rpe : float or None
        Actual RPE of the top set.
    target_rpe : float or None
        Prescribed RPE for the top set.
    extra_set_attempts : int
        How many extra sets have already been attempted.
    e1rm_history : list[float] or None
        e1RM values per cycle, most recent last.
    cycles_since_improvement : int
        Number of cycles since e1RM last improved.
    pain_flags : list[dict] or None
        List of dicts with 'exercise' and 'pain_flag' keys.

    Returns
    -------
    SessionAdjustment
        Aggregated results from all rules.
    """
    result = SessionAdjustment()

    # Rule 1: Top-set RPE too high
    if top_set_rpe is not None and target_rpe is not None:
        adj = check_top_set_rpe_too_high(top_set_rpe, target_rpe)
        result.adjustments.append(adj)
        if adj.triggered:
            result.skip_backoffs = True
            result.next_e1rm_adjustment = -5.0  # lower next e1RM by 5 lb

    # Rule 2: Top-set under target
    if top_set_rpe is not None and target_rpe is not None:
        adj = check_top_set_under_target(
            top_set_rpe, target_rpe, extra_set_attempts=extra_set_attempts
        )
        result.adjustments.append(adj)
        if adj.triggered:
            result.allow_extra_set = True

    # Rule 3: e1RM stall
    if e1rm_history is not None:
        adj = check_e1rm_stall(e1rm_history, cycles_since_improvement)
        result.adjustments.append(adj)
        if adj.triggered:
            result.early_deload = True
            result.suggested_variation_swap = "swap to deficit variation"

    # Rule 4: Pain flags
    if pain_flags:
        for pf in pain_flags:
            exercise = pf.get("exercise", "unknown")
            flag = pf.get("pain_flag", False)
            adj = check_pain_flag(flag, exercise)
            result.adjustments.append(adj)
            if adj.triggered:
                result.pain_flags.append(exercise)

    return result
