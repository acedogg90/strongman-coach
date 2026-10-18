"""
Tests for the adjustment rules engine (app/strength/adjustment_rules.py).

Covers all four adjustment rules:
1. Top-set RPE too high (>= target + 1.0): skip back-offs, lower next e1RM
2. Top-set under target (< target - 1.0): allow extra working set (max 2 attempts)
3. e1RM flat/down for 3 consecutive cycles: trigger early deload + variation swap
4. Pain flag on any set: ends that lift for the day
"""

import pytest

from app.strength.adjustment_rules import (
    AdjustmentResult,
    AdjustmentType,
    SessionAdjustment,
    check_e1rm_stall,
    check_pain_flag,
    check_top_set_rpe_too_high,
    check_top_set_under_target,
    evaluate_adjustments,
)


# ---------------------------------------------------------------------------
# Rule 1: Top-set RPE too high
# ---------------------------------------------------------------------------

class TestTopSetRpeTooHigh:
    def test_triggers_when_rpe_at_threshold(self):
        """RPE exactly at target + 1.0 should trigger."""
        result = check_top_set_rpe_too_high(actual_rpe=9.0, target_rpe=8.0)
        assert result.triggered is True
        assert result.rule_type == AdjustmentType.SKIP_BACKOFFS
        assert "skip back-offs" in result.message.lower()

    def test_triggers_when_rpe_above_threshold(self):
        """RPE above target + 1.0 should trigger."""
        result = check_top_set_rpe_too_high(actual_rpe=9.5, target_rpe=8.0)
        assert result.triggered is True

    def test_does_not_trigger_when_rpe_below_threshold(self):
        """RPE below target + 1.0 should not trigger."""
        result = check_top_set_rpe_too_high(actual_rpe=8.5, target_rpe=8.0)
        assert result.triggered is False

    def test_does_not_trigger_when_rpe_at_target(self):
        """RPE equal to target should not trigger."""
        result = check_top_set_rpe_too_high(actual_rpe=8.0, target_rpe=8.0)
        assert result.triggered is False

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        result = check_top_set_rpe_too_high(actual_rpe=8.5, target_rpe=8.0, threshold=0.5)
        assert result.triggered is True

    def test_details_contain_rpe_values(self):
        """Triggered result should include actual and target RPE in details."""
        result = check_top_set_rpe_too_high(actual_rpe=9.0, target_rpe=8.0)
        assert result.triggered
        assert result.details["actual_rpe"] == 9.0
        assert result.details["target_rpe"] == 8.0
        assert result.details["skip_backoffs"] is True


# ---------------------------------------------------------------------------
# Rule 2: Top-set RPE under target
# ---------------------------------------------------------------------------

class TestTopSetUnderTarget:
    def test_triggers_when_rpe_below_threshold(self):
        """RPE below target - 1.0 should trigger."""
        result = check_top_set_under_target(actual_rpe=6.0, target_rpe=8.0)
        assert result.triggered is True
        assert result.rule_type == AdjustmentType.EXTRA_SET

    def test_triggers_when_rpe_at_threshold(self):
        """RPE exactly at target - 1.0 should NOT trigger (strict less than)."""
        result = check_top_set_under_target(actual_rpe=7.0, target_rpe=8.0)
        assert result.triggered is False

    def test_does_not_trigger_when_rpe_at_target(self):
        """RPE equal to target should not trigger."""
        result = check_top_set_under_target(actual_rpe=8.0, target_rpe=8.0)
        assert result.triggered is False

    def test_does_not_trigger_when_max_attempts_reached(self):
        """Should not trigger if max extra set attempts already used."""
        result = check_top_set_under_target(
            actual_rpe=6.0, target_rpe=8.0, extra_set_attempts=2, max_attempts=2
        )
        assert result.triggered is False

    def test_allows_extra_set_when_attempts_remaining(self):
        """Should trigger if attempts remain."""
        result = check_top_set_under_target(
            actual_rpe=6.0, target_rpe=8.0, extra_set_attempts=1, max_attempts=2
        )
        assert result.triggered is True
        assert result.details["attempts_remaining"] == 1

    def test_details_contain_rpe_values(self):
        """Triggered result should include actual and target RPE in details."""
        result = check_top_set_under_target(actual_rpe=6.0, target_rpe=8.0)
        assert result.triggered
        assert result.details["actual_rpe"] == 6.0
        assert result.details["target_rpe"] == 8.0
        assert result.details["extra_set_allowed"] is True


# ---------------------------------------------------------------------------
# Rule 3: e1RM flat/down for 3 consecutive cycles
# ---------------------------------------------------------------------------

class TestE1rmStall:
    def test_triggers_at_3_cycles(self):
        """Should trigger when cycles_since_improvement >= 3."""
        result = check_e1rm_stall(
            e1rm_history=[225.0, 225.0, 225.0],
            cycles_since_improvement=3,
        )
        assert result.triggered is True
        assert result.rule_type == AdjustmentType.EARLY_DELOAD

    def test_triggers_above_3_cycles(self):
        """Should trigger when cycles_since_improvement > 3."""
        result = check_e1rm_stall(
            e1rm_history=[225.0, 220.0, 215.0, 210.0],
            cycles_since_improvement=5,
        )
        assert result.triggered is True

    def test_does_not_trigger_below_threshold(self):
        """Should not trigger when cycles_since_improvement < 3."""
        result = check_e1rm_stall(
            e1rm_history=[225.0, 225.0],
            cycles_since_improvement=2,
        )
        assert result.triggered is False

    def test_does_not_trigger_when_improving(self):
        """Should not trigger when e1RM is improving."""
        result = check_e1rm_stall(
            e1rm_history=[225.0, 230.0, 235.0],
            cycles_since_improvement=0,
        )
        assert result.triggered is False

    def test_details_contain_stall_info(self):
        """Triggered result should include stall details."""
        result = check_e1rm_stall(
            e1rm_history=[225.0, 225.0, 225.0],
            cycles_since_improvement=3,
        )
        assert result.triggered
        assert result.details["cycles_stalled"] == 3
        assert result.details["early_deload"] is True


# ---------------------------------------------------------------------------
# Rule 4: Pain flag
# ---------------------------------------------------------------------------

class TestPainFlag:
    def test_triggers_when_pain_flag_set(self):
        """Should trigger when pain_flag is True."""
        result = check_pain_flag(pain_flag=True, exercise_name="Deadlift")
        assert result.triggered is True
        assert result.rule_type == AdjustmentType.PAIN_FLAG

    def test_does_not_trigger_when_no_pain(self):
        """Should not trigger when pain_flag is False."""
        result = check_pain_flag(pain_flag=False, exercise_name="Deadlift")
        assert result.triggered is False

    def test_message_includes_exercise(self):
        """Message should include the exercise name."""
        result = check_pain_flag(pain_flag=True, exercise_name="Squat")
        assert result.triggered
        assert "Squat" in result.message

    def test_details_contain_exercise(self):
        """Details should include exercise name."""
        result = check_pain_flag(pain_flag=True, exercise_name="Bench Press")
        assert result.triggered
        assert result.details["exercise"] == "Bench Press"
        assert result.details["end_lift"] is True


# ---------------------------------------------------------------------------
# Aggregate evaluator: evaluate_adjustments
# ---------------------------------------------------------------------------

class TestEvaluateAdjustments:
    def test_empty_evaluation(self):
        """No inputs should produce no adjustments."""
        result = evaluate_adjustments(
            top_set_rpe=None,
            target_rpe=None,
        )
        assert isinstance(result, SessionAdjustment)
        assert len(result.adjustments) == 0

    def test_skip_backoffs_sets_flags(self):
        """When top-set RPE too high, skip_backoffs flag should be set."""
        result = evaluate_adjustments(
            top_set_rpe=9.5,
            target_rpe=8.0,
        )
        assert result.skip_backoffs is True
        assert result.next_e1rm_adjustment < 0

    def test_extra_set_sets_flags(self):
        """When top-set under target, allow_extra_set flag should be set."""
        result = evaluate_adjustments(
            top_set_rpe=6.0,
            target_rpe=8.0,
        )
        assert result.allow_extra_set is True

    def test_early_deload_sets_flags(self):
        """When e1RM stalled, early_deload flag should be set."""
        result = evaluate_adjustments(
            top_set_rpe=8.0,
            target_rpe=8.0,
            e1rm_history=[225.0, 225.0, 225.0],
            cycles_since_improvement=3,
        )
        assert result.early_deload is True
        assert result.suggested_variation_swap is not None

    def test_pain_flags_collected(self):
        """Pain flags should be collected in the result."""
        result = evaluate_adjustments(
            top_set_rpe=8.0,
            target_rpe=8.0,
            pain_flags=[
                {"exercise": "Deadlift", "pain_flag": True},
                {"exercise": "Squat", "pain_flag": False},
            ],
        )
        assert "Deadlift" in result.pain_flags
        assert "Squat" not in result.pain_flags

    def test_multiple_rules_fire(self):
        """Multiple rules can fire simultaneously."""
        result = evaluate_adjustments(
            top_set_rpe=9.5,
            target_rpe=8.0,
            e1rm_history=[225.0, 225.0, 225.0],
            cycles_since_improvement=3,
            pain_flags=[{"exercise": "Deadlift", "pain_flag": True}],
        )
        assert result.skip_backoffs is True
        assert result.early_deload is True
        assert "Deadlift" in result.pain_flags
        assert len(result.adjustments) >= 3

    def test_no_adjustment_when_rpe_at_target(self):
        """When RPE is exactly at target, no skip or extra set."""
        result = evaluate_adjustments(
            top_set_rpe=8.0,
            target_rpe=8.0,
        )
        assert result.skip_backoffs is False
        assert result.allow_extra_set is False

    def test_extra_set_blocked_after_max_attempts(self):
        """Extra set should not be allowed after max attempts."""
        result = evaluate_adjustments(
            top_set_rpe=6.0,
            target_rpe=8.0,
            extra_set_attempts=2,
        )
        assert result.allow_extra_set is False
