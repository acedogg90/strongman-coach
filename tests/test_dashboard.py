"""
Tests for the dashboard screen and /api/dashboard endpoint.

Covers:
- Dashboard API returns correct structure with all sections
- Current cycle number and block phase are returned
- Next scheduled workout with day type and date
- e1RM trend data for deadlift, overhead press, squat
- Recent completed sessions (last 5)
- Pain flags from recent sessions
- Deload warning when adjustment rules trigger
- Dashboard HTML is served at /
- Static files (CSS, JS) are accessible
- Dashboard refreshes after a new session is completed
"""

import datetime
import pytest
from fastapi.testclient import TestClient

from tests.conftest import authenticate_client
from app.routes import app, _get_session
from app.database import (
    Base,
    Session as DBSession,
    Program,
    Block,
    Cycle,
    Exercise,
    Prescription,
    SetLog,
    get_engine,
    reset_db,
)


@pytest.fixture()
def db_url(tmp_path):
    """Provide a file-based SQLite database URL for each test."""
    db_file = tmp_path / "test_dashboard.db"
    return f"sqlite:///{db_file}"


@pytest.fixture()
def client(db_url):
    """Create a TestClient with a fresh database for each test."""
    import app.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    get_engine(db_url)
    reset_db(db_url)
    c = TestClient(app)
    authenticate_client(c)
    return c


# ---------------------------------------------------------------------------
# Helper: seed a complete program with sessions and set logs
# ---------------------------------------------------------------------------

def _seed_program(client):
    """Create a minimal active program, block, cycle, and exercises."""
    db = _get_session()
    try:
        prog = Program(
            athlete_id=1,
            name="Test Program",
            phase="accumulation",
            start_date=datetime.date.today(),
            is_active=True,
        )
        db.add(prog)
        db.flush()

        blk = Block(
            program_id=prog.id,
            block_number=1,
            start_date=datetime.date.today(),
        )
        db.add(blk)
        db.flush()

        cyc = Cycle(
            block_id=blk.id,
            cycle_number=2,
            start_date=datetime.date.today(),
        )
        db.add(cyc)
        db.flush()

        # Seed main lifts
        for name in ["Deadlift", "Overhead Press", "Squat"]:
            ex = Exercise(name=name, role="main", metric_type="load_reps")
            db.add(ex)
        db.commit()

        # Return IDs only (avoid detached instance issues)
        return prog.id, blk.id, cyc.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _create_completed_session(client, cycle_id, day_label, scheduled_date,
                              exercises_with_sets=None):
    """Create a completed session with optional set logs."""
    db = _get_session()
    try:
        sess = DBSession(
            cycle_id=cycle_id,
            day_label=day_label,
            scheduled_date=scheduled_date,
            status="completed",
        )
        db.add(sess)
        db.flush()

        if exercises_with_sets:
            for ex_name, sets in exercises_with_sets.items():
                ex = db.query(Exercise).filter_by(name=ex_name).first()
                if not ex:
                    ex = Exercise(name=ex_name, role="main", metric_type="load_reps")
                    db.add(ex)
                    db.flush()

                for set_data in sets:
                    pres = Prescription(
                        session_id=sess.id,
                        exercise_id=ex.id,
                        set_number=set_data.get("set_number", 1),
                        prescribed_reps=set_data.get("reps", 5),
                        prescribed_rpe=set_data.get("rpe", 8.0),
                        prescribed_load_lb=set_data.get("load", 200),
                    )
                    db.add(pres)
                    db.flush()

                    log = SetLog(
                        exercise_id=ex.id,
                        session_id=sess.id,
                        prescription_id=pres.id,
                        actual_load_lb=set_data.get("load", 200),
                        actual_reps=set_data.get("reps", 5),
                        rpe=set_data.get("rpe", 8.0),
                        e1rm_lb=set_data.get("e1rm", 250),
                        confidence="high",
                        pain_flag=set_data.get("pain_flag", False),
                        set_type="top",
                        note=set_data.get("note"),
                    )
                    db.add(log)
        db.commit()
        return sess.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _create_planned_session(client, cycle_id, day_label, scheduled_date):
    """Create a planned (non-completed) session."""
    db = _get_session()
    try:
        sess = DBSession(
            cycle_id=cycle_id,
            day_label=day_label,
            scheduled_date=scheduled_date,
            status="planned",
        )
        db.add(sess)
        db.commit()
        return sess.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET / — Dashboard HTML
# ---------------------------------------------------------------------------

class TestDashboardHTML:
    def test_serves_index_html(self, client):
        """Root path returns HTML with dashboard content."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Strongman Coach" in resp.text
        assert "dashboard" in resp.text.lower()

    def test_html_has_all_sections(self, client):
        """Dashboard HTML contains all required section IDs."""
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="cycle-info"' in html
        assert 'id="next-workout"' in html
        assert 'id="e1rm-trends"' in html
        assert 'id="recent-sessions"' in html
        assert 'id="pain-flags"' in html
        assert 'id="deload-warning"' in html

    def test_html_includes_chart_js(self, client):
        """Dashboard HTML references Chart.js."""
        resp = client.get("/")
        assert "chart.js" in resp.text.lower()

    def test_html_includes_dashboard_js(self, client):
        """Dashboard HTML references the dashboard JS file."""
        resp = client.get("/")
        assert "dashboard.js" in resp.text

    def test_html_includes_dashboard_css(self, client):
        """Dashboard HTML references the dashboard CSS file."""
        resp = client.get("/")
        assert "dashboard.css" in resp.text


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

class TestStaticFiles:
    def test_css_accessible(self, client):
        """Dashboard CSS is served."""
        resp = client.get("/static/css/dashboard.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers.get("content-type", "")

    def test_js_accessible(self, client):
        """Dashboard JS is served."""
        resp = client.get("/static/js/dashboard.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("content-type", "").lower()


# ---------------------------------------------------------------------------
# GET /api/dashboard — Data structure
# ---------------------------------------------------------------------------

class TestDashboardAPI:
    def test_returns_200(self, client):
        """Dashboard endpoint returns 200."""
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client):
        """Response contains all top-level fields."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert "current_cycle" in data
        assert "block_phase" in data
        assert "next_workout" in data
        assert "e1rm_trends" in data
        assert "recent_sessions" in data
        assert "pain_flags" in data
        assert "deload_warning" in data

    def test_current_cycle_is_integer(self, client):
        """current_cycle is an integer."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["current_cycle"], int)

    def test_block_phase_is_string(self, client):
        """block_phase is a string."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["block_phase"], str)

    def test_e1rm_trends_is_list(self, client):
        """e1rm_trends is a list."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["e1rm_trends"], list)

    def test_recent_sessions_is_list(self, client):
        """recent_sessions is a list."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["recent_sessions"], list)

    def test_pain_flags_is_list(self, client):
        """pain_flags is a list."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert isinstance(data["pain_flags"], list)

    def test_deload_warning_is_object_or_null(self, client):
        """deload_warning is an object or null."""
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["deload_warning"] is None or isinstance(data["deload_warning"], dict)


# ---------------------------------------------------------------------------
# Cycle and block phase
# ---------------------------------------------------------------------------

class TestCycleAndBlock:
    def test_shows_cycle_number(self, client):
        """Dashboard shows the current cycle number."""
        _seed_program(client)
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["current_cycle"] == 2

    def test_shows_block_phase(self, client):
        """Dashboard shows the block phase."""
        _seed_program(client)
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["block_phase"] == "accumulation"

    def test_shows_intensification_phase(self, client):
        """Dashboard reflects intensification phase."""
        db = _get_session()
        try:
            prog = Program(
                athlete_id=1,
                name="Test Program",
                phase="intensification",
                start_date=datetime.date.today(),
                is_active=True,
            )
            db.add(prog)
            db.flush()
            blk = Block(program_id=prog.id, block_number=1, start_date=datetime.date.today())
            db.add(blk)
            db.flush()
            cyc = Cycle(block_id=blk.id, cycle_number=3, start_date=datetime.date.today())
            db.add(cyc)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["block_phase"] == "intensification"
        assert data["current_cycle"] == 3

    def test_shows_deload_phase(self, client):
        """Dashboard reflects deload phase."""
        db = _get_session()
        try:
            prog = Program(
                athlete_id=1,
                name="Test Program",
                phase="realization",
                start_date=datetime.date.today(),
                is_active=True,
            )
            db.add(prog)
            db.flush()
            blk = Block(
                program_id=prog.id,
                block_number=1,
                start_date=datetime.date.today(),
                is_deload=True,
            )
            db.add(blk)
            db.flush()
            cyc = Cycle(block_id=blk.id, cycle_number=4, start_date=datetime.date.today())
            db.add(cyc)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["current_cycle"] == 4


# ---------------------------------------------------------------------------
# Next workout
# ---------------------------------------------------------------------------

class TestNextWorkout:
    def test_shows_next_planned_session(self, client):
        """Dashboard shows the next planned workout."""
        _, _, cycle_id = _seed_program(client)
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        _create_planned_session(client, cycle_id, "A", tomorrow)

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["next_workout"] is not None
        assert data["next_workout"]["day_label"] == "A"
        assert data["next_workout"]["scheduled_date"] == str(tomorrow)

    def test_next_workout_day_b(self, client):
        """Dashboard shows Day B as next workout."""
        _, _, cycle_id = _seed_program(client)
        tomorrow = datetime.date.today() + datetime.timedelta(days=2)
        _create_planned_session(client, cycle_id, "B", tomorrow)

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["next_workout"]["day_label"] == "B"

    def test_next_workout_day_c(self, client):
        """Dashboard shows Day C as next workout."""
        _, _, cycle_id = _seed_program(client)
        tomorrow = datetime.date.today() + datetime.timedelta(days=3)
        _create_planned_session(client, cycle_id, "C", tomorrow)

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["next_workout"]["day_label"] == "C"

    def test_next_workout_day_d(self, client):
        """Dashboard shows Day D as next workout."""
        _, _, cycle_id = _seed_program(client)
        tomorrow = datetime.date.today() + datetime.timedelta(days=4)
        _create_planned_session(client, cycle_id, "D", tomorrow)

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["next_workout"]["day_label"] == "D"

    def test_no_next_workout_when_none_planned(self, client):
        """Dashboard shows null next_workout when no planned sessions."""
        _seed_program(client)
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["next_workout"] is None

    def test_skips_completed_sessions(self, client):
        """Dashboard skips completed sessions for next workout."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        _create_completed_session(client, cycle_id, "A", today, {})
        _create_planned_session(client, cycle_id, "B", tomorrow)

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["next_workout"]["day_label"] == "B"


# ---------------------------------------------------------------------------
# e1RM trends
# ---------------------------------------------------------------------------

class TestE1RMTrends:
    def test_includes_three_main_lifts(self, client):
        """Dashboard includes e1RM trends for deadlift, OHP, squat."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        exercises = [t["exercise"] for t in data["e1rm_trends"]]
        assert "Deadlift" in exercises
        assert "Overhead Press" in exercises
        assert "Squat" in exercises

    def test_trend_has_history(self, client):
        """e1RM trend includes history entries."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        dl_trend = [t for t in data["e1rm_trends"] if t["exercise"] == "Deadlift"][0]
        assert len(dl_trend["history"]) >= 1
        assert dl_trend["history"][0]["e1rm"] == 350

    def test_trend_e1rm_calculated(self, client):
        """Trend e1RM is calculated from session history."""
        _, _, cycle_id = _seed_program(client)
        d1 = datetime.date.today() - datetime.timedelta(days=14)
        d2 = datetime.date.today() - datetime.timedelta(days=7)
        _create_completed_session(client, cycle_id, "A", d1, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })
        _create_completed_session(client, cycle_id, "A", d2, {
            "Deadlift": [{"load": 310, "reps": 5, "rpe": 8.0, "e1rm": 360}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        dl_trend = [t for t in data["e1rm_trends"] if t["exercise"] == "Deadlift"][0]
        assert dl_trend["trend_e1rm"] is not None
        # Mean of best 2 of last 3: mean(360, 350) = 355
        assert dl_trend["trend_e1rm"] == 355.0

    def test_squat_trend(self, client):
        """Squat e1RM trend is tracked."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "C", today, {
            "Squat": [{"load": 275, "reps": 5, "rpe": 8.0, "e1rm": 320}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        sq_trend = [t for t in data["e1rm_trends"] if t["exercise"] == "Squat"][0]
        assert sq_trend["trend_e1rm"] == 320

    def test_ohp_trend(self, client):
        """Overhead Press e1RM trend is tracked."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "B", today, {
            "Overhead Press": [{"load": 135, "reps": 5, "rpe": 8.0, "e1rm": 160}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        ohp_trend = [t for t in data["e1rm_trends"] if t["exercise"] == "Overhead Press"][0]
        assert ohp_trend["trend_e1rm"] == 160

    def test_empty_history_when_no_sessions(self, client):
        """e1RM trends have empty history when no completed sessions."""
        _seed_program(client)
        resp = client.get("/api/dashboard")
        data = resp.json()
        for trend in data["e1rm_trends"]:
            assert len(trend["history"]) == 0
            assert trend["trend_e1rm"] is None


# ---------------------------------------------------------------------------
# Recent sessions
# ---------------------------------------------------------------------------

class TestRecentSessions:
    def test_shows_last_5_sessions(self, client):
        """Dashboard shows up to 5 recent completed sessions."""
        _, _, cycle_id = _seed_program(client)
        for i in range(5):
            d = datetime.date.today() - datetime.timedelta(days=i * 3)
            _create_completed_session(client, cycle_id, "A", d, {})

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["recent_sessions"]) == 5

    def test_fewer_than_5_sessions(self, client):
        """Dashboard shows fewer sessions when less than 5 exist."""
        _, _, cycle_id = _seed_program(client)
        for i in range(2):
            d = datetime.date.today() - datetime.timedelta(days=i * 3)
            _create_completed_session(client, cycle_id, "A", d, {})

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["recent_sessions"]) == 2

    def test_session_has_date_and_day_label(self, client):
        """Each recent session has date and day_label."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "B", today, {})

        resp = client.get("/api/dashboard")
        data = resp.json()
        sess = data["recent_sessions"][0]
        assert "date" in sess
        assert "day_label" in sess
        assert sess["day_label"] == "B"

    def test_session_has_summary(self, client):
        """Each recent session has a summary of exercises."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        sess = data["recent_sessions"][0]
        assert "Deadlift" in sess["summary"]

    def test_sessions_ordered_desc(self, client):
        """Recent sessions are ordered by date descending (newest first)."""
        _, _, cycle_id = _seed_program(client)
        d1 = datetime.date.today() - datetime.timedelta(days=7)
        d2 = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", d1, {})
        _create_completed_session(client, cycle_id, "A", d2, {})

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["recent_sessions"][0]["date"] == str(d2)
        assert data["recent_sessions"][1]["date"] == str(d1)

    def test_no_completed_sessions(self, client):
        """Dashboard shows empty recent sessions when none completed."""
        _seed_program(client)
        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["recent_sessions"]) == 0


# ---------------------------------------------------------------------------
# Pain flags
# ---------------------------------------------------------------------------

class TestPainFlags:
    def test_shows_pain_flags(self, client):
        """Dashboard displays pain flags from recent sessions."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350,
                         "pain_flag": True, "note": "Lower back tight"}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["pain_flags"]) >= 1
        flag = data["pain_flags"][0]
        assert flag["exercise"] == "Deadlift"
        assert flag["note"] == "Lower back tight"

    def test_no_pain_flags(self, client):
        """Dashboard shows no pain flags when none exist."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["pain_flags"]) == 0

    def test_pain_flag_without_note(self, client):
        """Pain flag works without a note."""
        _, _, cycle_id = _seed_program(client)
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Squat": [{"load": 275, "reps": 5, "rpe": 8.0, "e1rm": 320,
                      "pain_flag": True}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["pain_flags"]) >= 1
        flag = data["pain_flags"][0]
        assert flag["exercise"] == "Squat"
        assert flag["note"] is None

    def test_multiple_pain_flags(self, client):
        """Dashboard shows multiple pain flags from different sessions."""
        _, _, cycle_id = _seed_program(client)
        d1 = datetime.date.today() - datetime.timedelta(days=7)
        d2 = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", d1, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350,
                         "pain_flag": True, "note": "Knee pain"}],
        })
        _create_completed_session(client, cycle_id, "B", d2, {
            "Overhead Press": [{"load": 135, "reps": 5, "rpe": 8.0, "e1rm": 160,
                               "pain_flag": True, "note": "Shoulder"}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert len(data["pain_flags"]) >= 2


# ---------------------------------------------------------------------------
# Deload warning
# ---------------------------------------------------------------------------

class TestDeloadWarning:
    def test_no_warning_when_improving(self, client):
        """No deload warning when e1RM is improving."""
        _, _, cycle_id = _seed_program(client)
        d1 = datetime.date.today() - datetime.timedelta(days=21)
        d2 = datetime.date.today() - datetime.timedelta(days=14)
        d3 = datetime.date.today() - datetime.timedelta(days=7)
        _create_completed_session(client, cycle_id, "A", d1, {
            "Deadlift": [{"load": 280, "reps": 5, "rpe": 8.0, "e1rm": 330}],
        })
        _create_completed_session(client, cycle_id, "A", d2, {
            "Deadlift": [{"load": 290, "reps": 5, "rpe": 8.0, "e1rm": 340}],
        })
        _create_completed_session(client, cycle_id, "A", d3, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["deload_warning"]["triggered"] is False

    def test_warning_when_stalled(self, client):
        """Deload warning triggers when e1RM stalls for 3 cycles."""
        _, _, cycle_id = _seed_program(client)
        d1 = datetime.date.today() - datetime.timedelta(days=21)
        d2 = datetime.date.today() - datetime.timedelta(days=14)
        d3 = datetime.date.today() - datetime.timedelta(days=7)
        _create_completed_session(client, cycle_id, "A", d1, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })
        _create_completed_session(client, cycle_id, "A", d2, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })
        _create_completed_session(client, cycle_id, "A", d3, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["deload_warning"]["triggered"] is True
        assert "Deadlift" in data["deload_warning"]["message"]
        assert data["deload_warning"]["cycles_stalled"] == 3

    def test_warning_when_declining(self, client):
        """Deload warning triggers when e1RM declines."""
        _, _, cycle_id = _seed_program(client)
        d1 = datetime.date.today() - datetime.timedelta(days=21)
        d2 = datetime.date.today() - datetime.timedelta(days=14)
        d3 = datetime.date.today() - datetime.timedelta(days=7)
        _create_completed_session(client, cycle_id, "A", d1, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })
        _create_completed_session(client, cycle_id, "A", d2, {
            "Deadlift": [{"load": 290, "reps": 5, "rpe": 8.0, "e1rm": 340}],
        })
        _create_completed_session(client, cycle_id, "A", d3, {
            "Deadlift": [{"load": 280, "reps": 5, "rpe": 8.0, "e1rm": 330}],
        })

        resp = client.get("/api/dashboard")
        data = resp.json()
        assert data["deload_warning"]["triggered"] is True


# ---------------------------------------------------------------------------
# Dashboard refresh after session completion
# ---------------------------------------------------------------------------

class TestDashboardRefresh:
    def test_dashboard_updates_after_session(self, client):
        """Dashboard reflects new completed session after it's added."""
        _, _, cycle_id = _seed_program(client)

        # Initially no sessions
        resp1 = client.get("/api/dashboard")
        data1 = resp1.json()
        assert len(data1["recent_sessions"]) == 0

        # Add a completed session
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        # Dashboard should now show the session
        resp2 = client.get("/api/dashboard")
        data2 = resp2.json()
        assert len(data2["recent_sessions"]) == 1
        assert data2["recent_sessions"][0]["day_label"] == "A"

    def test_e1rm_trend_updates_after_session(self, client):
        """e1RM trends update after a new session is completed."""
        _, _, cycle_id = _seed_program(client)

        # Initially no trends
        resp1 = client.get("/api/dashboard")
        data1 = resp1.json()
        dl_trend1 = [t for t in data1["e1rm_trends"] if t["exercise"] == "Deadlift"][0]
        assert len(dl_trend1["history"]) == 0

        # Add a session with deadlift
        today = datetime.date.today()
        _create_completed_session(client, cycle_id, "A", today, {
            "Deadlift": [{"load": 300, "reps": 5, "rpe": 8.0, "e1rm": 350}],
        })

        # Dashboard should show the trend
        resp2 = client.get("/api/dashboard")
        data2 = resp2.json()
        dl_trend2 = [t for t in data2["e1rm_trends"] if t["exercise"] == "Deadlift"][0]
        assert len(dl_trend2["history"]) == 1
        assert dl_trend2["history"][0]["e1rm"] == 350
