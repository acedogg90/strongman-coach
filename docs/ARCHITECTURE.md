# Strongman Coach — Architecture

## 1. Overview

Strongman Coach transforms the existing Training Tracker into a phone-first, installable, offline-capable PWA that plans and adjusts strongman training by RPE. It computes estimated 1RM (e1RM) from every logged set, auto-adjusts upcoming session loads based on actual performance, and preserves all historical lift data via migration. The backend remains FastAPI + SQLite; the frontend is a vanilla-JS PWA with no build step.

---

## 2. Stack

| Layer | Choice | Justification |
|-------|--------|---------------|
| Language | Python 3.12 | All strength calculations in Python; existing backend is Python. |
| Framework | FastAPI | Already in use; async, auto-OpenAPI docs, lightweight. |
| Storage | SQLite (via `aiosqlite`) | Single-file DB, no external services, runs on any OS. |
| ORM | SQLAlchemy 2.0 (async) | Declarative models, migrations via Alembic, well-known. |
| Frontend | Vanilla JS + HTML + CSS | No build step, PWA-compatible, phone-first. |
| Offline storage | IndexedDB (via `idb` wrapper) | Browser-native, structured, sufficient for session queue. |
| Test tooling | `pytest` + `httpx` (async client) | Existing requirement; covers unit and integration tests. |

---

## 3. Components

| Component | Responsibility | Depends on |
|-----------|---------------|------------|
| `app/strength/rpe.py` | RPE chart lookup, e1RM, target load, confidence flags | None (pure functions) |
| `app/strength/progress.py` | Session e1RM, trend e1RM, PR detection, stall detection | `rpe.py`, DB read |
| `app/strength/plan.py` | Prescription generation, warm-up, back-off sets, auto-adjustment | `rpe.py`, `progress.py`, DB |
| `app/strength/program.py` | Program template, block/cycle/session generation, deload, variation rotation | `plan.py`, DB |
| `app/api/` | FastAPI routes for CRUD, dashboard, export, settings | All strength modules, DB |
| `app/db/` | SQLAlchemy models, Alembic migrations, seed data | None |
| `frontend/` | PWA shell, logging screen, dashboard, service worker, IndexedDB sync queue | API |

---

## 4. Data Model

All tables use `INTEGER PRIMARY KEY AUTOINCREMENT`. Timestamps are `DATETIME` (UTC ISO-8601).

### 4.1 athlete

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| name | VARCHAR(100) | NOT NULL |
| height_cm | REAL | |
| age | INTEGER | |
| training_age_months | INTEGER | |
| units | VARCHAR(4) | DEFAULT 'lb', CHECK IN ('lb','kg') |
| plate_increment_lb | REAL | DEFAULT 2.5 |
| dumbbell_max_lb | INTEGER | DEFAULT 120 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### 4.2 bodyweight

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| athlete_id | INTEGER | FK → athlete.id, NOT NULL |
| weight_lb | REAL | NOT NULL |
| date | DATE | NOT NULL |
| notes | TEXT | |

### 4.3 equipment

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| athlete_id | INTEGER | FK → athlete.id, NOT NULL |
| name | VARCHAR(100) | NOT NULL |
| available | BOOLEAN | DEFAULT TRUE |
| category | VARCHAR(30) | CHECK IN ('gym','club','personal') |

*Seeded from Crunch Fitness inventory + club items (turf, sled, tires, landmines, KBs, MBs) + personal gear (sandbag, fat grips, straps, belt, chalk).*

### 4.4 exercise

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| name | VARCHAR(100) | NOT NULL, UNIQUE |
| role | VARCHAR(20) | CHECK IN ('main','secondary','accessory','event','event_substitute') |
| movement_pattern | VARCHAR(20) | CHECK IN ('hinge','squat','press','carry','load','pull','core') |
| required_equipment | TEXT | JSON array of equipment names |
| metric_type | VARCHAR(20) | DEFAULT 'load_reps', CHECK IN ('load_reps','load_distance','load_time','reps_in_time') |
| is_hidden | BOOLEAN | DEFAULT FALSE |

### 4.5 exercise_substitute

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| primary_exercise_id | INTEGER | FK → exercise.id, NOT NULL |
| substitute_exercise_id | INTEGER | FK → exercise.id, NOT NULL |
| priority | INTEGER | DEFAULT 1 (lower = preferred) |

*Seeded for log press, axle, deadlift, farmers, yoke, atlas stone, loading medley, truck pull.*

### 4.6 program

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| athlete_id | INTEGER | FK → athlete.id, NOT NULL |
| name | VARCHAR(100) | NOT NULL |
| phase | VARCHAR(20) | CHECK IN ('accumulation','intensification','realization') |
| start_date | DATE | NOT NULL |
| end_date | DATE | |
| is_active | BOOLEAN | DEFAULT FALSE |

### 4.7 block

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| program_id | INTEGER | FK → program.id, NOT NULL |
| block_number | INTEGER | NOT NULL |
| is_deload | BOOLEAN | DEFAULT FALSE |
| variation_name | VARCHAR(100) | e.g. 'conventional', 'deficit' |
| start_date | DATE | NOT NULL |
| end_date | DATE | |

### 4.8 cycle

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| block_id | INTEGER | FK → block.id, NOT NULL |
| cycle_number | INTEGER | NOT NULL (1–4; 4 = deload) |
| start_date | DATE | NOT NULL |
| end_date | DATE | |

### 4.9 session

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| cycle_id | INTEGER | FK → cycle.id, NOT NULL |
| day_label | VARCHAR(10) | CHECK IN ('A','B','C','D') |
| scheduled_date | DATE | NOT NULL |
| actual_date | DATE | |
| status | VARCHAR(20) | DEFAULT 'planned', CHECK IN ('planned','in_progress','completed','skipped') |
| readiness_sleep | INTEGER | CHECK BETWEEN 1 AND 5 |
| readiness_soreness | INTEGER | CHECK BETWEEN 1 AND 5 |
| readiness_stress | INTEGER | CHECK BETWEEN 1 AND 5 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### 4.10 prescription

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| session_id | INTEGER | FK → session.id, NOT NULL |
| exercise_id | INTEGER | FK → exercise.id, NOT NULL |
| set_number | INTEGER | NOT NULL |
| prescribed_reps | INTEGER | |
| prescribed_rpe | REAL | CHECK BETWEEN 6.0 AND 10.0 |
| prescribed_load_lb | REAL | |
| is_warmup | BOOLEAN | DEFAULT FALSE |
| is_backoff | BOOLEAN | DEFAULT FALSE |
| fatigue_drop_pct | REAL | DEFAULT 0 |
| adjustment_note | TEXT | |

### 4.11 set_log

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| prescription_id | INTEGER | FK → prescription.id, NOT NULL |
| actual_load_lb | REAL | NOT NULL |
| actual_reps | INTEGER | NOT NULL |
| rpe | REAL | CHECK BETWEEN 6.0 AND 10.0 |
| e1rm_lb | REAL | |
| confidence | VARCHAR(10) | DEFAULT 'high', CHECK IN ('high','low') |
| pain_flag | BOOLEAN | DEFAULT FALSE |
| note | TEXT | |
| logged_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### 4.12 event_log

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| prescription_id | INTEGER | FK → prescription.id, NOT NULL |
| load_lb | REAL | |
| distance_ft | REAL | |
| time_sec | REAL | |
| reps | INTEGER | |
| note | TEXT | |
| logged_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### 4.13 pr

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| athlete_id | INTEGER | FK → athlete.id, NOT NULL |
| exercise_id | INTEGER | FK → exercise.id, NOT NULL |
| category | VARCHAR(20) | CHECK IN ('true_1rm','e1rm','rep_pr') |
| value_lb | REAL | NOT NULL |
| reps | INTEGER | |
| date | DATE | NOT NULL |

### 4.14 settings

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK |
| athlete_id | INTEGER | FK → athlete.id, NOT NULL |
| key | VARCHAR(50) | NOT NULL |
| value | TEXT | NOT NULL |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

*Unique constraint on (athlete_id, key). Keys: `units`, `weight_class`, `safety_notice_seen`, `benchmarks` (JSON of ASM 2025 values).*

---

## 5. Migration Plan

### 5.1 Source: Training Tracker

Existing schema stores lifts in a `TrainingEntry` table with columns: `id`, `date` (DATE), `exercise_name` (TEXT), `weight` (REAL), `reps` (INTEGER), `sets` (INTEGER), `notes` (TEXT).

### 5.2 Strategy

1. **Seed reference tables** — `exercise` (from distinct `exercise_name` values), `equipment` (Crunch Fitness defaults), `athlete` (single row), `settings` (defaults per ADR-0002, ADR-0003).
2. **Create program skeleton** — A single "Imported History" program with one block, one cycle, and one `session` per distinct `date` in `TrainingEntry`.
3. **Map each TrainingEntry to prescriptions and set_logs**:
   - One `prescription` per set (set_number = 1..N where N = `sets` column).
   - One `set_log` per prescription: `actual_load_lb = weight`, `actual_reps = reps`, `rpe = NULL`, `confidence = 'low'` (RPE unknown).
   - `e1rm_lb` backfilled via Epley formula: `weight × (1 + reps/30)`.
   - `notes` carried through to `set_log.note`.
4. **Backfill PRs** — For each exercise, record highest `e1rm_lb` as category `e1rm`.
5. **Idempotency** — Migration checks `migration_version` in `settings`; skips if already run.

### 5.3 Data-loss safeguards

- Original `TrainingEntry` is **renamed** to `TrainingEntry_archive`, not dropped.
- Migration runs in a single transaction; rollback on any error.
- Post-migration assertion: count of `set_log` rows ≥ count of original `TrainingEntry` rows.

---

## 6. API Endpoints

All routes under `/api/v1/`. JSON request/response. No auth (local-only app).

### 6.1 Athlete & Settings

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/athlete` | — | `{name, height_cm, age, training_age_months, units, plate_increment_lb, dumbbell_max_lb}` |
| PATCH | `/athlete` | `{name?, height_cm?, age?, training_age_months?, units?, plate_increment_lb?, dumbbell_max_lb?}` | updated athlete |
| GET | `/bodyweight` | — | `[{id, weight_lb, date, notes}, ...]` |
| POST | `/bodyweight` | `{weight_lb, date, notes?}` | created entry |
| GET | `/settings` | — | `[{key, value}, ...]` |
| PATCH | `/settings` | `{key, value}` | updated setting |
| GET | `/equipment` | — | `[{id, name, available, category}, ...]` |
| PATCH | `/equipment` | `{id, available}` | updated equipment |

### 6.2 Program & Planning

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/programs` | — | `[{id, name, phase, start_date, is_active}, ...]` |
| POST | `/programs` | `{phase, start_date}` | created program with generated blocks/cycles/sessions |
| GET | `/programs/{id}/preview` | — | next 5 sessions with prescriptions |
| GET | `/sessions/{id}` | — | session with all prescriptions |
| PATCH | `/sessions/{id}/readiness` | `{sleep, soreness, stress}` | updated readiness scores |

### 6.3 Logging

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/sessions/{id}/set` | `{prescription_id, actual_load_lb, actual_reps, rpe?, pain_flag?, note?}` | created set_log with computed e1rm_lb |
| POST | `/sessions/{id}/event` | `{prescription_id, load_lb?, distance_ft?, time_sec?, reps?, note?}` | created event_log |
| PATCH | `/sessions/{id}/complete` | — | marks complete, triggers auto-adjustment on next sessions |
| GET | `/sessions/{id}/e1rm` | — | `{exercise_e1rms: [{exercise, session_e1rm, trend_e1rm}], ...}` |

### 6.4 Dashboard

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/dashboard/e1rm-trend` | — | `{exercise, trend_e1rm, bodyweight_multiple, history: [{date, e1rm}]}` |
| GET | `/dashboard/tonnage` | — | `[{week, pattern, total_tonnage_lb}, ...]` |
| GET | `/dashboard/prs` | — | `[{exercise, category, value_lb, reps, date}, ...]` |
| GET | `/dashboard/benchmarks` | — | `{exercise, athlete_value, benchmark_value, pct_of_benchmark}` |
| GET | `/dashboard/stalls` | — | `[{exercise, last_improvement_date, cycles_since}, ...]` |

### 6.5 Export

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/export/csv` | — | CSV of all set_log + event_log rows |
| GET | `/export/json` | — | JSON of all set_log + event_log rows |
| GET | `/export/block-print` | — | HTML printable view of current block |

### 6.6 Utilities

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/calc/plate` | `{load_lb, bar_weight_lb}` | `{per_side, plates: [lb, count]}` |
| POST | `/calc/warmup` | `{working_load_lb, sets}` | `[{load_lb, reps}, ...]` |

---

## 7. PWA / Offline Approach

### 7.1 Service Worker Strategy

- **App shell** (HTML, CSS, JS, icons, manifest) cached on first install via `cache-first`.
- **API responses** cached with `network-first`, falling back to cache for dashboard reads.
- **Stale-while-revalidate** for exercise library and settings (rarely change).

### 7.2 IndexedDB Schema

```
DB: strongman-coach
  Store: sync_queue
    keyPath: id (auto-increment)
    indexes: [session_id, type]
    fields: { type: 'set'|'event'|'readiness',
              payload: object,
              status: 'pending'|'synced'|'failed',
              created_at: timestamp }
  Store: cached_sessions
    keyPath: session_id
    fields: { session_id, prescriptions: [], set_logs: [] }
```

When offline, every logged set/event is written to `sync_queue`. The UI reads from IndexedDB immediately so the user never sees a blank screen.

### 7.3 Sync Mechanism

1. On page load, a sync worker checks `navigator.onLine`.
2. If online, iterates `sync_queue` where `status = 'pending'`, POSTs each to the API.
3. On success → `'synced'`; on failure → retries with exponential backoff (max 3, then `'failed'`).
4. Sync runs on `online` event and every 30 seconds via `setInterval`.
5. Conflict resolution: server is authoritative.

### 7.4 Installability

- `manifest.json` with `display: standalone`, icons 192×192 and 512×512.
- Add-to-home-screen prompt via `beforeinstallprompt` event.

---

## 8. Directory Layout

```
strongman-coach/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── db/                  # models.py, engine.py, seed.py
│   ├── api/                 # athlete.py, logging.py, dashboard.py, program.py, export.py, utils.py
│   ├── strength/            # rpe.py, progress.py, plan.py, program.py
│   └── migration/           # migrate.py (TrainingEntry → new schema)
├── tests/                   # test_rpe.py, test_progress.py, test_plan.py, test_program.py, test_api.py
├── frontend/
│   ├── index.html           # app shell
│   ├── css/                 # styles
│   ├── js/                  # app.js, logging.js, dashboard.js, sync.js, utils.js
│   ├── sw.js                # service worker
│   └── manifest.json
├── alembic/                 # env.py, versions/
├── docs/                    # ARCHITECTURE.md, adr/
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## 9. Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | `rpe.py` chart lookups, e1RM math, confidence flags | `pytest` parametrized tests with known chart values |
| Unit | `progress.py` trend calculation, PR detection, stall logic | In-memory SQLite fixtures |
| Unit | `plan.py` warm-up generation, back-off caps, adjustment rules | In-memory SQLite fixtures |
| Unit | `program.py` block/cycle generation, deload triggers | In-memory SQLite fixtures |
| Integration | Full API routes (POST set, GET dashboard, export) | `httpx.AsyncClient` against test app with temp DB |
| Integration | Migration script | Run against seeded `TrainingEntry` fixture, verify row counts |

**Run all tests:**

```bash
pytest
```

---

## 10. Security and Data Handling

- **No authentication** — app runs on a local LAN only; no external exposure.
- **No secrets** — no API keys, no cloud credentials.
- **Input validation** — Pydantic models on all API request bodies; RPE clamped 6.0–10.0, reps ≥ 1, load > 0.
- **SQL injection** — prevented by SQLAlchemy parameterized queries.
- **Safety notice** — "not medical advice" shown once on first settings view; stored in `settings.safety_notice_seen`.
- **RPE cap** — prescriptions never exceed RPE 9.5 except on user-initiated test days.
- **Pain flag** — immediately stops further prescriptions for that exercise in the current session.

---

## 11. Assumptions and Open Questions

### Assumptions

1. The existing Training Tracker uses a single `TrainingEntry` table with `date`, `exercise_name`, `weight`, `reps`, `sets` columns. If the actual schema differs, the migration script will need adjustment.
2. Only one athlete is supported (single-user app). Multi-athlete support is out of scope.
3. The FastAPI server and PWA client communicate over the same LAN; no internet required.
4. Plate increment defaults to 2.5 lb (ADR-0002: lb default).
5. Weight classes follow SMC kg classes (ADR-0003).

### Open Questions (Owner should confirm)

1. **Existing schema details** — What are the exact column names and types in the current `TrainingEntry` table? The migration plan assumes a specific shape.
2. **Bodyweight class for Masters** — Should the Masters 40+ class set (80/90/105/HW>105) apply at exactly age 40, or is there a different cutoff?
3. **Data retention** — Should old synced entries in IndexedDB be purged after N days, or kept indefinitely?
4. **Export scope** — Should CSV/JSON export include event_log rows, or only set_log rows?

---

## 12. Referenced Decisions

- [ADR-0001](adr/0001-offline-first.md) — Offline-first PWA with IndexedDB sync queue
- [ADR-0002](adr/0002-lb-default.md) — Pounds (lb) as default units
- [ADR-0003](adr/0003-smc-weight-classes.md) — SMC weight classes for amateur and masters
