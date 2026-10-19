/**
 * Strongman Coach – Session history database layer (TypeScript).
 *
 * Uses async expo-sqlite with an EXISTS subquery to fetch the last 30
 * distinct sessions that contain sets for a given exercise.
 *
 * This module is the frontend counterpart to app/repositories/sessions.py
 * and works in the offline-first PWA context.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SetLogEntry {
  set_log_id: number;
  session_id: number;
  exercise_id: number;
  exercise_name: string;
  actual_load_lb: number;
  actual_reps: number;
  rpe: number | null;
  e1rm_lb: number | null;
  confidence: 'high' | 'low' | null;
  pain_flag: boolean;
  set_type: string | null;
  note: string | null;
  logged_at: string | null;
  session_date: string | null;
  session_day_label: string | null;
  session_status: string | null;
}

// ---------------------------------------------------------------------------
// Database helpers
// ---------------------------------------------------------------------------

/**
 * Open (or create) the expo-sqlite database.
 * In a real Expo app this would be `import * as SQLite from 'expo-sqlite'`.
 * Here we expose a typed interface so the hook can be tested without the
 * native module.
 */
export interface SQLiteDatabase {
  executeSql<T>(sql: string, params?: unknown[]): Promise<T[]>;
}

/**
 * Build the EXISTS-subquery that selects the last *limit* distinct sessions
 * containing sets for *exerciseId*.
 *
 * The key difference from a naive LIMIT on rows is that we limit *sessions*,
 * not *rows*.  A session can have many sets; we want the most recent N
 * sessions, then all sets within those sessions.
 */
function buildExistsQuery(limit: number): string {
  return `
    SELECT sl.*
    FROM set_log sl
    WHERE sl.exercise_id = ?
      AND sl.session_id IS NOT NULL
      AND EXISTS (
        SELECT 1
        FROM (
          SELECT DISTINCT sl2.session_id
          FROM set_log sl2
          WHERE sl2.exercise_id = ?
            AND sl2.session_id IS NOT NULL
          ORDER BY sl2.logged_at DESC
          LIMIT ?
        ) recent
        WHERE recent.session_id = sl.session_id
      )
    ORDER BY sl.logged_at DESC
  `;
}

/**
 * Fetch session history for a given exercise using the EXISTS subquery.
 *
 * @param db – expo-sqlite database instance
 * @param exerciseId – primary key in the exercise table
 * @param limit – maximum number of distinct sessions (default 30)
 * @returns list of set-log entries, empty array when no data
 */
export async function getForExercise(
  db: SQLiteDatabase,
  exerciseId: number,
  limit: number = 30,
): Promise<SetLogEntry[]> {
  const sql = buildExistsQuery(limit);
  const rows = await db.executeSql(sql, [exerciseId, exerciseId, limit]);

  if (!rows || rows.length === 0) {
    return [];
  }

  return rows.map((row: Record<string, unknown>) => ({
    set_log_id: Number(row['id']),
    session_id: Number(row['session_id']),
    exercise_id: Number(row['exercise_id']),
    exercise_name: String(row['exercise_name'] ?? 'Unknown'),
    actual_load_lb: Number(row['actual_load_lb']),
    actual_reps: Number(row['actual_reps']),
    rpe: row['rpe'] != null ? Number(row['rpe']) : null,
    e1rm_lb: row['e1rm_lb'] != null ? Number(row['e1rm_lb']) : null,
    confidence: (row['confidence'] as 'high' | 'low' | null) ?? null,
    pain_flag: Boolean(row['pain_flag']),
    set_type: row['set_type'] ? String(row['set_type']) : null,
    note: row['note'] ? String(row['note']) : null,
    logged_at: row['logged_at'] ? String(row['logged_at']) : null,
    session_date: row['session_date'] ? String(row['session_date']) : null,
    session_day_label: row['session_day_label'] ? String(row['session_day_label']) : null,
    session_status: row['session_status'] ? String(row['session_status']) : null,
  }));
}

// ---------------------------------------------------------------------------
// e1RM calculation helpers (mirrors app/strength/rpe.py)
// ---------------------------------------------------------------------------

/**
 * RPE percent chart: reps 1..12 × RPE 6.0..10.0 → % of 1RM.
 * Mirrors the Python _RPE_PERCENT table in app/strength/rpe.py.
 */
const RPE_PERCENT: number[][] = [
  [65.0, 70.0, 75.0, 80.0, 85.0, 88.0, 91.0, 95.0, 100.0], // 1 rep
  [71.0, 75.0, 78.0, 81.0, 84.0, 87.0, 89.0, 92.0, 95.0], // 2 reps
  [75.0, 78.0, 81.0, 84.0, 86.0, 88.0, 89.2, 92.0, 94.0], // 3 reps
  [78.0, 80.0, 83.0, 85.0, 87.0, 89.0, 91.0, 93.0, 95.0], // 4 reps
  [80.0, 82.0, 84.0, 86.0, 81.1, 89.0, 91.0, 93.0, 95.0], // 5 reps
  [82.0, 84.0, 86.0, 88.0, 89.0, 91.0, 93.0, 94.0, 96.0], // 6 reps
  [84.0, 86.0, 87.0, 89.0, 90.0, 92.0, 93.0, 95.0, 96.0], // 7 reps
  [85.0, 87.0, 88.0, 90.0, 91.0, 92.0, 94.0, 95.0, 96.0], // 8 reps
  [86.0, 87.0, 89.0, 90.0, 91.0, 93.0, 94.0, 95.0, 96.0], // 9 reps
  [87.0, 88.0, 89.0, 91.0, 92.0, 93.0, 94.0, 95.0, 96.0], // 10 reps
  [88.0, 89.0, 90.0, 91.0, 92.0, 93.0, 95.0, 96.0, 97.0], // 11 reps
  [89.0, 90.0, 91.0, 92.0, 93.0, 94.0, 95.0, 96.0, 96.0], // 12 reps
];

const MIN_REPS = 1;
const MAX_REPS = 12;
const MIN_RPE = 6.0;
const MAX_RPE = 10.0;
const RPE_STEP = 0.5;

/**
 * Validate reps (1–12).
 */
function validateReps(reps: number): void {
  if (!Number.isInteger(reps) || reps < MIN_REPS || reps > MAX_REPS) {
    throw new Error(`reps must be an integer between ${MIN_REPS} and ${MAX_REPS}, got ${reps}`);
  }
}

/**
 * Validate RPE (6.0–10.0 in 0.5 steps).
 */
function validateRpe(rpe: number): void {
  if (typeof rpe !== 'number' || isNaN(rpe)) {
    throw new Error(`rpe must be a number, got ${rpe}`);
  }
  if (rpe < MIN_RPE || rpe > MAX_RPE) {
    throw new Error(`rpe must be between ${MIN_RPE} and ${MAX_RPE}, got ${rpe}`);
  }
  if (Math.abs(rpe * 2 - Math.round(rpe * 2)) > 1e-9) {
    throw new Error(`rpe must be on a 0.5 step (e.g. 7.0, 7.5), got ${rpe}`);
  }
}

/**
 * Calculate the estimated 1RM from a set.
 *
 * Mirrors app/strength/rpe.py::e1rm().
 *
 * @param weight – load lifted (lb)
 * @param reps – reps completed (1–12)
 * @param rpe – optional RPE; if omitted, Epley fallback is used
 * @returns { e1rm: number, confidence: 'high' | 'low' }
 * @throws Error if reps or rpe are invalid
 */
export function calculateE1RM(
  weight: number,
  reps: number,
  rpe?: number | null,
): { e1rm: number; confidence: 'high' | 'low' } {
  // Guard against invalid weight
  if (typeof weight !== 'number' || isNaN(weight) || weight <= 0) {
    throw new Error(`weight must be a positive number, got ${weight}`);
  }

  validateReps(reps);

  if (rpe == null) {
    // Epley fallback
    const e1rmVal = weight * (1 + reps / 30.0);
    return { e1rm: Math.round(e1rmVal * 10) / 10, confidence: 'low' };
  }

  validateRpe(rpe);

  const row = reps - 1; // 0-indexed
  const col = Math.round((rpe - MIN_RPE) / RPE_STEP); // 0-indexed
  const pct = RPE_PERCENT[row][col];
  const e1rmVal = weight / (pct / 100.0);

  // Confidence: low if RPE < 7 or reps > 8
  const confidence = rpe < 7.0 || reps > 8 ? 'low' : 'high';

  return { e1rm: Math.round(e1rmVal * 10) / 10, confidence };
}
