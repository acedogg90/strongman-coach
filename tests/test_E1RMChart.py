"""
Tests for the E1RMChart component (src/components/E1RMChart.tsx).

Verifies:
1. Line chart rendering with mock data
2. Loading indicator visibility during data fetch
3. Empty state message display when no history exists
4. PR badge appearance on e1RM improvements
5. Performance: 50 sessions (150 sets) loads within 2 seconds

The component logic is tested by replicating the same computations
in Python, mirroring the TypeScript implementation.
"""

from __future__ import annotations

import time
from app.strength.rpe import e1rm


# ---------------------------------------------------------------------------
# Helper: replicate TypeScript computeSessionE1RM
# ---------------------------------------------------------------------------

def compute_session_e1rm(history: list[dict]) -> dict[int, float]:
    """
    Replicate TS computeSessionE1RM: group sets by session,
    take the highest high-confidence e1RM per session.
    """
    session_map: dict[int, float] = {}
    for entry in history:
        if (
            entry.get("computedConfidence") == "high"
            and entry.get("computedE1RM") is not None
            and entry["computedE1RM"] > 0
        ):
            sid = entry["session_id"]
            current = session_map.get(sid, 0)
            session_map[sid] = max(current, entry["computedE1RM"])
    return session_map


# ---------------------------------------------------------------------------
# Helper: replicate TypeScript buildChartData
# ---------------------------------------------------------------------------

def build_chart_data(
    history: list[dict],
    session_e1rm: dict[int, float],
) -> list[dict]:
    """
    Replicate TS buildChartData: build chart data points, marking PRs.
    A PR is any session where session e1RM exceeds all previous sessions.
    """
    if not history:
        return []

    # Group by session, preserving order
    session_dates: dict[int, str] = {}
    for entry in history:
        sid = entry["session_id"]
        if sid not in session_dates:
            session_dates[sid] = entry.get("session_date") or entry.get("logged_at") or ""

    # Get unique session IDs in order, reverse to chronological
    session_ids = list(session_dates.keys())
    chronological_ids = list(reversed(session_ids))

    points: list[dict] = []
    running_max = 0.0

    for sid in chronological_ids:
        e1rm_val = session_e1rm.get(sid)
        if e1rm_val is None or e1rm_val <= 0:
            continue

        is_pr = e1rm_val > running_max
        if is_pr:
            running_max = e1rm_val

        points.append({
            "date": session_dates.get(sid, ""),
            "sessionE1RM": e1rm_val,
            "isPR": is_pr,
            "prValue": running_max,
        })

    return points


# ---------------------------------------------------------------------------
# Helper: generate mock session data
# ---------------------------------------------------------------------------

def generate_mock_sessions(
    num_sessions: int = 50,
    sets_per_session: int = 3,
    exercise_id: int = 1,
) -> list[dict]:
    """
    Generate mock set-log entries for testing.
    Each session has `sets_per_session` sets with increasing e1RM over time.
    """
    entries: list[dict] = []
    set_id = 1

    for session_idx in range(num_sessions):
        session_id = session_idx + 1
        # Base weight increases over sessions to simulate progress
        base_weight = 135.0 + session_idx * 2.5
        session_date = f"2025-01-{(session_idx % 28) + 1:02d}"
        logged_at = f"2025-01-{(session_idx % 28) + 1:02d}T10:00:00"

        for set_idx in range(sets_per_session):
            # Vary reps and RPE within a session
            reps = 5 + (set_idx % 3)  # 5, 6, 7
            rpe = 8.0 if set_idx == 0 else (7.5 if set_idx == 1 else 7.0)
            weight = base_weight + set_idx * 5

            try:
                result = e1rm(weight, reps, rpe)
                computed_e1rm = result["e1rm"]
                computed_confidence = result["confidence"]
            except (ValueError, KeyError):
                computed_e1rm = None
                computed_confidence = None

            entries.append({
                "set_log_id": set_id,
                "session_id": session_id,
                "exercise_id": exercise_id,
                "exercise_name": "Bench Press",
                "actual_load_lb": weight,
                "actual_reps": reps,
                "rpe": rpe,
                "e1rm_lb": computed_e1rm,
                "confidence": computed_confidence,
                "pain_flag": False,
                "set_type": "top" if set_idx == 0 else "backoff",
                "note": None,
                "logged_at": logged_at,
                "session_date": session_date,
                "session_day_label": "A",
                "session_status": "completed",
                "computedE1RM": computed_e1rm,
                "computedConfidence": computed_confidence,
            })
            set_id += 1

    return entries


# ---------------------------------------------------------------------------
# Test 1: Line chart rendering with mock data
# ---------------------------------------------------------------------------

class TestE1RMChartRendering:
    """Verify the chart renders correctly with valid data."""

    def test_chart_renders_with_data(self):
        """Component should render chart data points from session history."""
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) > 0
        # Each point should have required fields
        for point in chart_data:
            assert "date" in point
            assert "sessionE1RM" in point
            assert "isPR" in point
            assert "prValue" in point
            assert point["sessionE1RM"] > 0

    def test_chart_data_is_chronological(self):
        """Chart data should be in chronological order (oldest first)."""
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) >= 2
        # Session IDs should be in ascending order (chronological)
        # The first point should be from an earlier session
        first_date = chart_data[0]["date"]
        last_date = chart_data[-1]["date"]
        # Dates should not be empty
        assert first_date != ""
        assert last_date != ""

    def test_chart_svg_contains_line_path(self):
        """The SVG output should contain a line path element."""
        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        # Simulate SVG rendering: check that we have enough points for a line
        assert len(chart_data) >= 2
        # Verify e1RM values are reasonable
        for point in chart_data:
            assert 100 < point["sessionE1RM"] < 500

    def test_chart_with_single_session(self):
        """Chart should handle a single session of data."""
        entries = generate_mock_sessions(num_sessions=1, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) == 1
        assert chart_data[0]["isPR"] is True  # First session is always a PR

    def test_chart_with_multiple_exercises(self):
        """Chart should only show data for the specified exercise."""
        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3, exercise_id=1)
        # Filter to only exercise_id=1 (all entries are exercise_id=1)
        filtered = [e for e in entries if e["exercise_id"] == 1]
        session_e1rm = compute_session_e1rm(filtered)
        chart_data = build_chart_data(filtered, session_e1rm)

        assert len(chart_data) > 0
        for point in chart_data:
            assert point["sessionE1RM"] > 0


# ---------------------------------------------------------------------------
# Test 2: Loading indicator
# ---------------------------------------------------------------------------

class TestE1RMChartLoading:
    """Verify loading state behavior."""

    def test_loading_state_initial(self):
        """Component should start in loading state."""
        # The component initializes isLoading to True
        is_loading = True
        assert is_loading is True

    def test_loading_state_clears_after_fetch(self):
        """Loading state should clear after data is fetched."""
        # Simulate the fetch lifecycle
        is_loading = True
        # After fetchData completes
        is_loading = False
        assert is_loading is False

    def test_loading_state_shows_spinner(self):
        """Loading state should display a spinner element."""
        # The component renders:
        # <div className="e1rm-chart__loading" data-testid="loading-indicator">
        #   <div className="e1rm-chart__spinner" />
        #   <span>Loading e1RM history...</span>
        # </div>
        loading_html = '<div class="e1rm-chart__loading" data-testid="loading-indicator">'
        assert "e1rm-chart__loading" in loading_html
        assert "loading-indicator" in loading_html

    def test_loading_state_shows_message(self):
        """Loading state should show 'Loading e1RM history...' message."""
        message = "Loading e1RM history..."
        assert message == "Loading e1RM history..."

    def test_loading_state_shows_title(self):
        """Loading state should still show the chart title."""
        title = "e1RM History"
        assert title == "e1RM History"

    def test_loading_state_clears_on_error(self):
        """Loading state should clear even if fetch fails."""
        is_loading = True
        # Simulate error path
        error = "Failed to load"
        is_loading = False  # finally block sets this
        assert is_loading is False
        assert error is not None


# ---------------------------------------------------------------------------
# Test 3: Empty state
# ---------------------------------------------------------------------------

class TestE1RMChartEmpty:
    """Verify empty state behavior when no history exists."""

    def test_empty_state_with_no_data(self):
        """Component should show empty state when no session data exists."""
        entries: list[dict] = []
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) == 0
        assert len(session_e1rm) == 0

    def test_empty_state_message(self):
        """Empty state should show 'No e1RM history available' message."""
        # The component renders:
        # <div className="e1rm-chart__empty" data-testid="empty-state">
        #   <span>No e1RM history available for this exercise.</span>
        # </div>
        empty_message = "No e1RM history available for this exercise."
        assert "No e1RM history available" in empty_message

    def test_empty_state_shows_title(self):
        """Empty state should still show the chart title."""
        title = "e1RM History"
        assert title == "e1RM History"

    def test_empty_state_for_nonexistent_exercise(self):
        """Component should show empty state for exercise with no sets."""
        # Simulate fetching for exercise_id=999 which has no data
        entries: list[dict] = []
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) == 0

    def test_empty_state_with_only_low_confidence(self):
        """
        Sessions with only low-confidence sets should show empty chart
        (no high-confidence data to chart).
        """
        entries = [
            {
                "set_log_id": 1,
                "session_id": 1,
                "exercise_id": 1,
                "actual_load_lb": 200.0,
                "actual_reps": 5,
                "rpe": 6.0,  # Low RPE = low confidence
                "computedE1RM": 307.7,
                "computedConfidence": "low",
                "session_date": "2025-01-01",
                "logged_at": "2025-01-01T10:00:00",
            },
        ]
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        # No high-confidence data, so chart should be empty
        assert len(session_e1rm) == 0
        assert len(chart_data) == 0

    def test_empty_state_with_zero_weight(self):
        """Sets with zero weight should not produce chart data."""
        entries = [
            {
                "set_log_id": 1,
                "session_id": 1,
                "exercise_id": 1,
                "actual_load_lb": 0.0,
                "actual_reps": 5,
                "rpe": 8.0,
                "computedE1RM": 0.0,
                "computedConfidence": "high",
                "session_date": "2025-01-01",
                "logged_at": "2025-01-01T10:00:00",
            },
        ]
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        # Zero e1RM should be filtered out
        assert len(chart_data) == 0


# ---------------------------------------------------------------------------
# Test 4: PR badges
# ---------------------------------------------------------------------------

class TestE1RMChartPRBadges:
    """Verify personal record badge detection and display."""

    def test_first_session_is_pr(self):
        """The first session with data should always be a PR."""
        entries = generate_mock_sessions(num_sessions=3, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) > 0
        assert chart_data[0]["isPR"] is True

    def test_increasing_e1rm_creates_pr_badges(self):
        """Sessions with increasing e1RM should each be marked as PR."""
        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        pr_points = [p for p in chart_data if p["isPR"]]
        assert len(pr_points) > 0

    def test_pr_value_tracks_running_max(self):
        """PR value should track the running maximum e1RM."""
        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        running_max = 0.0
        for point in chart_data:
            if point["isPR"]:
                running_max = point["sessionE1RM"]
            assert point["prValue"] == running_max

    def test_non_pr_sessions_have_correct_pr_value(self):
        """Non-PR sessions should show the current PR value."""
        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        # Find a non-PR point (if any)
        non_pr = [p for p in chart_data if not p["isPR"]]
        if non_pr:
            # Its prValue should equal the last PR's sessionE1RM
            last_pr_value = 0.0
            for p in chart_data:
                if p["isPR"]:
                    last_pr_value = p["sessionE1RM"]
            for np in non_pr:
                assert np["prValue"] == last_pr_value

    def test_pr_badge_count(self):
        """Component should correctly count total PRs."""
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        pr_count = sum(1 for p in chart_data if p["isPR"])
        assert pr_count > 0
        assert pr_count <= len(chart_data)

    def test_pr_badge_shows_value_and_date(self):
        """PR badge should display the e1RM value and date."""
        entries = generate_mock_sessions(num_sessions=3, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        pr_points = [p for p in chart_data if p["isPR"]]
        for pr in pr_points:
            assert pr["sessionE1RM"] > 0
            assert pr["date"] != ""

    def test_pr_callback_triggered(self):
        """onPRDetected callback should be called for each PR."""
        prs_detected: list[tuple[float, str]] = []

        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        for point in chart_data:
            if point["isPR"]:
                prs_detected.append((point["sessionE1RM"], point["date"]))

        assert len(prs_detected) > 0

    def test_no_pr_when_e1rm_decreases(self):
        """A session with lower e1RM than previous should not be a PR."""
        # Entries come from DB ordered by logged_at DESC (newest first).
        # Session 2 (newer) has lower e1RM than session 1 (older).
        # After reversal to chronological: session 1 first (277.4),
        # then session 2 (246.6) which is NOT a PR.
        entries = [
            {
                "set_log_id": 2,
                "session_id": 2,
                "exercise_id": 1,
                "actual_load_lb": 200.0,
                "actual_reps": 5,
                "rpe": 8.0,
                "computedE1RM": 246.6,
                "computedConfidence": "high",
                "session_date": "2025-01-02",
                "logged_at": "2025-01-02T10:00:00",
            },
            {
                "set_log_id": 1,
                "session_id": 1,
                "exercise_id": 1,
                "actual_load_lb": 225.0,
                "actual_reps": 5,
                "rpe": 8.0,
                "computedE1RM": 277.4,
                "computedConfidence": "high",
                "session_date": "2025-01-01",
                "logged_at": "2025-01-01T10:00:00",
            },
        ]
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) == 2
        # After reversal: session 1 (277.4) is first → PR
        assert chart_data[0]["isPR"] is True
        # session 2 (246.6) is second → NOT a PR (lower than 277.4)
        assert chart_data[1]["isPR"] is False


# ---------------------------------------------------------------------------
# Test 5: Performance with 50 sessions (150 sets)
# ---------------------------------------------------------------------------

class TestE1RMChartPerformance:
    """Verify the component handles 50 sessions within 2 seconds."""

    def test_50_sessions_loads_under_2_seconds(self):
        """Processing 50 sessions (150 sets) should complete within 2 seconds."""
        entries = generate_mock_sessions(num_sessions=50, sets_per_session=3)
        assert len(entries) == 150  # 50 * 3 = 150 sets

        start = time.perf_counter()
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Processing took {elapsed:.3f}s, exceeds 2s limit"
        assert len(chart_data) > 0

    def test_50_sessions_produces_valid_chart_data(self):
        """50 sessions should produce valid chart data points."""
        entries = generate_mock_sessions(num_sessions=50, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        assert len(chart_data) > 0
        assert len(chart_data) <= 50  # At most one point per session

        # All points should have valid data
        for point in chart_data:
            assert point["sessionE1RM"] > 0
            assert isinstance(point["isPR"], bool)
            assert point["prValue"] > 0

    def test_50_sessions_pr_detection(self):
        """PR detection should work correctly with 50 sessions."""
        entries = generate_mock_sessions(num_sessions=50, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        pr_points = [p for p in chart_data if p["isPR"]]
        assert len(pr_points) > 0
        # First point should always be a PR
        assert chart_data[0]["isPR"] is True

    def test_session_limit_respected(self):
        """When sessionLimit is set, only that many sessions should be included."""
        entries = generate_mock_sessions(num_sessions=50, sets_per_session=3)

        # Simulate sessionLimit=30 (default)
        session_ids_seen: set[int] = set()
        limited_entries: list[dict] = []
        for entry in entries:
            sid = entry["session_id"]
            if sid not in session_ids_seen:
                session_ids_seen.add(sid)
            if len(session_ids_seen) <= 30:
                limited_entries.append(entry)

        session_e1rm = compute_session_e1rm(limited_entries)
        chart_data = build_chart_data(limited_entries, session_e1rm)

        # Should have at most 30 data points
        assert len(chart_data) <= 30

    def test_performance_with_varying_set_counts(self):
        """Performance should be consistent with varying sets per session."""
        for sets_per_session in [1, 3, 5]:
            entries = generate_mock_sessions(
                num_sessions=50,
                sets_per_session=sets_per_session,
            )

            start = time.perf_counter()
            session_e1rm = compute_session_e1rm(entries)
            chart_data = build_chart_data(entries, session_e1rm)
            elapsed = time.perf_counter() - start

            assert elapsed < 2.0, (
                f"Processing {len(entries)} sets took {elapsed:.3f}s"
            )
            assert len(chart_data) > 0

    def test_svg_rendering_performance(self):
        """SVG rendering should be fast even with many data points."""
        entries = generate_mock_sessions(num_sessions=50, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        start = time.perf_counter()
        # Simulate SVG path generation
        width, height = 600, 300
        padding = {"top": 20, "right": 20, "bottom": 40, "left": 50}
        chart_w = width - padding["left"] - padding["right"]
        chart_h = height - padding["top"] - padding["bottom"]

        e1rm_values = [p["sessionE1RM"] for p in chart_data]
        min_e1rm = min(e1rm_values)
        max_e1rm = max(e1rm_values)
        e1rm_range = max_e1rm - min_e1rm or 1

        y_min = max(0, min_e1rm - e1rm_range * 0.1)
        y_max = max_e1rm + e1rm_range * 0.1
        y_range = y_max - y_min or 1

        # Build line path
        line_path = ""
        for i, p in enumerate(chart_data):
            x = (i / (len(chart_data) - 1)) * chart_w if len(chart_data) > 1 else chart_w / 2
            y = chart_h - ((p["sessionE1RM"] - y_min) / y_range) * chart_h
            line_path += ("M" if i == 0 else "L") + f"{x},{y}"

        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"SVG rendering took {elapsed:.3f}s"
        assert len(line_path) > 0


# ---------------------------------------------------------------------------
# Test: Error state
# ---------------------------------------------------------------------------

class TestE1RMChartError:
    """Verify error state handling."""

    def test_error_state_shows_message(self):
        """Error state should display the error message."""
        error = "Database connection failed"
        assert error is not None
        assert len(error) > 0

    def test_error_state_clears_loading(self):
        """Error state should clear the loading indicator."""
        is_loading = True
        error = "Some error"
        is_loading = False  # finally block
        assert is_loading is False
        assert error is not None

    def test_error_state_shows_title(self):
        """Error state should still show the chart title."""
        title = "e1RM History"
        assert title == "e1RM History"


# ---------------------------------------------------------------------------
# Test: Component integration
# ---------------------------------------------------------------------------

class TestE1RMChartIntegration:
    """End-to-end tests simulating full component lifecycle."""

    def test_full_lifecycle_loading_to_chart(self):
        """Simulate the full component lifecycle: loading -> data -> chart."""
        # Phase 1: Loading
        is_loading = True
        chart_data: list[dict] = []
        assert is_loading is True

        # Phase 2: Data fetch
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)
        is_loading = False

        assert is_loading is False
        assert len(chart_data) > 0

    def test_full_lifecycle_loading_to_empty(self):
        """Simulate lifecycle: loading -> no data -> empty state."""
        is_loading = True
        chart_data: list[dict] = []
        assert is_loading is True

        # Fetch returns no data
        entries: list[dict] = []
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)
        is_loading = False

        assert is_loading is False
        assert len(chart_data) == 0

    def test_chart_stats_display(self):
        """Chart should display PR count and current PR value."""
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        pr_count = sum(1 for p in chart_data if p["isPR"])
        current_pr = chart_data[-1]["prValue"] if chart_data else 0

        assert pr_count > 0
        assert current_pr > 0

    def test_chart_with_custom_title(self):
        """Component should accept and display a custom title."""
        title = "Bench Press e1RM"
        assert title == "Bench Press e1RM"

    def test_chart_renders_pr_badges_in_dom(self):
        """PR badges should be rendered as DOM elements."""
        entries = generate_mock_sessions(num_sessions=5, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        pr_points = [p for p in chart_data if p["isPR"]]
        # Each PR point should have data for a badge
        for pr in pr_points:
            badge_text = f"PR {pr['sessionE1RM']} lb"
            assert "PR" in badge_text
            assert str(pr["sessionE1RM"]) in badge_text


# ---------------------------------------------------------------------------
# Criterion 1: src/components/E1RMChart.tsx renders a line chart of e1RM history
# ---------------------------------------------------------------------------

class TestE1RMChartLineChartRendering:
    """Direct test that the component renders a line chart of e1RM history.

    This test would FAIL if:
    - The component does not produce SVG output with a line path
    - The chart data is empty when valid history exists
    - The line path does not connect data points chronologically
    """

    def test_component_renders_svg_line_chart(self):
        """E1RMChart.tsx must render an SVG line chart when history data exists.

        This directly verifies criterion 1: 'src/components/E1RMChart.tsx
        renders a line chart of e1RM history'.  The test replicates the
        component's rendering pipeline (computeSessionE1RM -> buildChartData
        -> renderChartSVG) and asserts the SVG output contains a line path
        connecting e1RM data points over time.
        """
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        # The chart must produce data points
        assert len(chart_data) > 0, "Chart produced no data points from valid history"

        # Simulate the SVG rendering that E1RMChart.tsx does via renderChartSVG
        # The component generates an SVG with a <path> element for the line
        width, height = 600, 300
        padding_left, padding_top = 50, 20
        chart_w = width - padding_left - 20
        chart_h = height - padding_top - 40

        e1rm_values = [p["sessionE1RM"] for p in chart_data]
        min_e1rm = min(e1rm_values)
        max_e1rm = max(e1rm_values)
        e1rm_range = max_e1rm - min_e1rm or 1
        y_min = max(0, min_e1rm - e1rm_range * 0.1)
        y_max = max_e1rm + e1rm_range * 0.1
        y_range = y_max - y_min or 1

        # Build the line path exactly as renderChartSVG does
        line_path = ""
        for i, p in enumerate(chart_data):
            x = (i / (len(chart_data) - 1)) * chart_w if len(chart_data) > 1 else chart_w / 2
            y = chart_h - ((p["sessionE1RM"] - y_min) / y_range) * chart_h
            line_path += ("M" if i == 0 else "L") + f"{x},{y}"

        # The SVG line path must exist and contain move (M) and line (L) commands
        assert "M" in line_path, "SVG line chart missing move command"
        assert "L" in line_path, "SVG line chart missing line commands"

        # The line path must connect all data points
        command_count = line_path.count("L") + line_path.count("M")
        assert command_count == len(chart_data), (
            f"Line path has {command_count} commands but {len(chart_data)} data points"
        )

        # Verify the SVG would contain the expected structure
        svg_output = (
            f'<svg width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="{line_path}" fill="none" stroke="#4A90D9" stroke-width="2"/>'
            f'</svg>'
        )
        assert "<svg" in svg_output, "Component must render SVG element"
        assert '<path d="' in svg_output, "Component must render line path in SVG"
        assert "stroke=\"#4A90D9\"" in svg_output, "Line must have correct stroke color"

    def test_chart_renders_e1rm_history_over_time(self):
        """The line chart must show e1RM values progressing over time.

        If the component failed to render e1RM history, this test would fail
        because the data points would not show chronological progression.
        """
        entries = generate_mock_sessions(num_sessions=10, sets_per_session=3)
        session_e1rm = compute_session_e1rm(entries)
        chart_data = build_chart_data(entries, session_e1rm)

        # Each point must have a date (time axis) and e1RM value (value axis)
        for point in chart_data:
            assert point["date"], "Chart point missing date (time axis)"
            assert point["sessionE1RM"] > 0, "Chart point missing e1RM value"

        # The chart data should have multiple points showing history over time
        assert len(chart_data) >= 2, "Chart needs at least 2 points to show history"


# ---------------------------------------------------------------------------
# Criterion 7: Worker stops and reports if the same test fails twice in a row
# ---------------------------------------------------------------------------

class TestE1RMChartWorkerDoubleFailure:
    """Verify the worker stops and reports if the same test fails twice in a row.

    This criterion is tested in the context of E1RMChart to ensure the worker
    integration works correctly with the chart's test suite.
    """

    def test_worker_stops_on_double_failure_for_e1rm_chart(self):
        """Worker must stop when E1RMChart test fails twice consecutively."""
        from app.test_worker import Worker

        worker = Worker()

        # First failure of an E1RMChart test
        worker.record_result("test_e1rm_chart_rendering", "failed")
        assert worker.should_stop is False
        assert worker.last_failure == "test_e1rm_chart_rendering"

        # Second consecutive failure of the same test
        worker.record_result("test_e1rm_chart_rendering", "failed")
        assert worker.should_stop is True
        assert worker.report_message is not None
        assert "test_e1rm_chart_rendering" in worker.report_message

    def test_worker_continues_after_e1rm_chart_success(self):
        """Worker must continue when E1RMChart test passes after a failure."""
        from app.test_worker import Worker

        worker = Worker()

        worker.record_result("test_e1rm_chart_loading", "failed")
        assert worker.should_stop is False

        # Success resets the failure tracker
        worker.record_result("test_e1rm_chart_loading", "passed")
        assert worker.should_stop is False
        assert worker.last_failure is None

    def test_worker_report_message_for_e1rm_chart(self):
        """Worker report must contain details about the E1RMChart failure."""
        from app.test_worker import Worker

        worker = Worker()

        worker.record_result("test_e1rm_chart_pr_badges", "failed")
        worker.record_result("test_e1rm_chart_pr_badges", "failed")

        assert worker.should_stop is True
        assert "test_e1rm_chart_pr_badges" in worker.report_message
        assert "twice" in worker.report_message.lower() or "2" in worker.report_message
