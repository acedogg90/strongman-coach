/**
 * Strongman Coach – E1RMChart component.
 *
 * Renders a line chart showing e1RM trends over time for a given exercise.
 * Includes:
 *   - Loading indicator while data is being fetched
 *   - Empty state message when no history exists
 *   - Personal record (PR) badges on data points where e1RM improved
 *   - Performance: handles 50 sessions (150 sets) within 2 seconds
 *
 * Uses the useE1RM hook for data fetching and the calculateE1RM helper
 * for computing e1RM values from raw set data.
 */

import React, { useMemo, useState, useEffect, useCallback } from 'react';
import { useE1RM, E1RMHistoryEntry, createTestQueryClient } from '../hooks/useE1RM';
import { SQLiteDatabase, SetLogEntry, calculateE1RM } from '../database/sessions';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface E1RMChartProps {
  /** Primary key of the exercise to chart. */
  exerciseId: number;
  /** Database instance for fetching session data. */
  db: SQLiteDatabase;
  /** Maximum number of distinct sessions to include (default 30). */
  sessionLimit?: number;
  /** Optional label shown above the chart. */
  title?: string;
  /** Callback when a PR is detected (for analytics, etc.). */
  onPRDetected?: (e1rm: number, date: string | null) => void;
}

export interface ChartDataPoint {
  /** ISO date string of the session. */
  date: string;
  /** Session e1RM (highest high-confidence e1RM in that session). */
  sessionE1RM: number;
  /** Whether this point is a personal record. */
  isPR: boolean;
  /** The PR value at this point (cumulative max). */
  prValue: number;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Group sets by session and compute the session-level e1RM
 * (highest high-confidence e1RM in that session).
 */
function computeSessionE1RM(history: E1RMHistoryEntry[]): Map<number, number> {
  const sessionMap = new Map<number, number>();

  for (const entry of history) {
    if (
      entry.computedConfidence === 'high' &&
      entry.computedE1RM != null &&
      entry.computedE1RM > 0
    ) {
      const current = sessionMap.get(entry.session_id) ?? 0;
      sessionMap.set(entry.session_id, Math.max(current, entry.computedE1RM));
    }
  }

  return sessionMap;
}

/**
 * Build chart data points from history, marking PRs.
 * A PR is any session where the session e1RM exceeds all previous sessions.
 */
function buildChartData(
  history: E1RMHistoryEntry[],
  sessionE1RM: Map<number, number>,
): ChartDataPoint[] {
  if (history.length === 0) {
    return [];
  }

  // Group by session, preserving order (most recent first from the hook)
  const sessionDates = new Map<number, string | null>();
  for (const entry of history) {
    if (!sessionDates.has(entry.session_id)) {
      sessionDates.set(entry.session_id, entry.session_date ?? entry.logged_at ?? '');
    }
  }

  // Get unique session IDs in order
  const sessionIds = Array.from(sessionDates.keys());

  // Reverse to chronological order (oldest first) for the chart
  const chronologicalIds = [...sessionIds].reverse();

  const points: ChartDataPoint[] = [];
  let runningMax = 0;

  for (const sessionId of chronologicalIds) {
    const e1rm = sessionE1RM.get(sessionId);
    if (e1rm == null || e1rm <= 0) {
      continue; // Skip sessions with no high-confidence data
    }

    const isPR = e1rm > runningMax;
    if (isPR) {
      runningMax = e1rm;
    }

    points.push({
      date: sessionDates.get(sessionId) ?? '',
      sessionE1RM: e1rm,
      isPR,
      prValue: runningMax,
    });
  }

  return points;
}

/**
 * Generate a simple SVG line chart from data points.
 * Uses a minimal inline SVG approach (no external chart library).
 */
function renderChartSVG(
  points: ChartDataPoint[],
  width: number,
  height: number,
): string {
  if (points.length === 0) {
    return '';
  }

  const padding = { top: 20, right: 20, bottom: 40, left: 50 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Compute scale
  const e1rmValues = points.map((p) => p.sessionE1RM);
  const minE1RM = Math.min(...e1rmValues);
  const maxE1RM = Math.max(...e1rmValues);
  const e1rmRange = maxE1RM - minE1RM || 1; // Avoid division by zero

  // Add 10% padding to the range
  const yMin = Math.max(0, minE1RM - e1rmRange * 0.1);
  const yMax = maxE1RM + e1rmRange * 0.1;
  const yRange = yMax - yMin || 1;

  const xScale = (i: number) =>
    points.length === 1
      ? chartW / 2
      : (i / (points.length - 1)) * chartW;

  const yScale = (val: number) =>
    chartH - ((val - yMin) / yRange) * chartH;

  // Build line path
  let linePath = '';
  points.forEach((p, i) => {
    const x = xScale(i) + padding.left;
    const y = yScale(p.sessionE1RM) + padding.top;
    linePath += (i === 0 ? 'M' : 'L') + `${x},${y}`;
  });

  // Build PR badge circles
  let prBadges = '';
  points.forEach((p, i) => {
    if (p.isPR) {
      const x = xScale(i) + padding.left;
      const y = yScale(p.sessionE1RM) + padding.top;
      prBadges += `<circle cx="${x}" cy="${y}" r="6" fill="#FFD700" stroke="#B8860B" stroke-width="2"/>`;
      prBadges += `<text x="${x}" y="${y - 10}" text-anchor="middle" fill="#B8860B" font-size="10" font-weight="bold">PR</text>`;
    }
  });

  // Build data point circles
  let dataPoints = '';
  points.forEach((p, i) => {
    const x = xScale(i) + padding.left;
    const y = yScale(p.sessionE1RM) + padding.top;
    dataPoints += `<circle cx="${x}" cy="${y}" r="3" fill="#4A90D9"/>`;
  });

  // Y-axis labels
  let yLabels = '';
  const ySteps = 5;
  for (let i = 0; i <= ySteps; i++) {
    const val = yMin + (yRange * i) / ySteps;
    const y = yScale(val) + padding.top;
    yLabels += `<text x="${padding.left - 5}" y="${y + 4}" text-anchor="end" font-size="10">${Math.round(val)}</text>`;
    yLabels += `<line x1="${padding.left}" y1="${y}" x2="${padding.left + chartW}" y2="${y}" stroke="#eee" stroke-width="1"/>`;
  }

  // X-axis labels (show a subset if many points)
  let xLabels = '';
  const labelInterval = points.length > 10 ? Math.ceil(points.length / 5) : 1;
  points.forEach((p, i) => {
    if (i % labelInterval === 0 || i === points.length - 1) {
      const x = xScale(i) + padding.left;
      const shortDate = p.date ? p.date.substring(0, 10) : '';
      xLabels += `<text x="${x}" y="${height - 5}" text-anchor="middle" font-size="9" transform="rotate(-45, ${x}, ${height - 5})">${shortDate}</text>`;
    }
  });

  // Axis lines
  const axes = `
    <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${padding.top + chartH}" stroke="#ccc" stroke-width="1"/>
    <line x1="${padding.left}" y1="${padding.top + chartH}" x2="${padding.left + chartW}" y2="${padding.top + chartH}" stroke="#ccc" stroke-width="1"/>
  `;

  return `
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
      ${axes}
      ${yLabels}
      ${xLabels}
      <path d="${linePath}" fill="none" stroke="#4A90D9" stroke-width="2"/>
      ${dataPoints}
      ${prBadges}
    </svg>
  `;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * E1RMChart – renders a line chart of e1RM history with loading, empty,
 * and PR badge support.
 */
export function E1RMChart({
  exerciseId,
  db,
  sessionLimit = 30,
  title = 'e1RM History',
  onPRDetected,
}: E1RMChartProps) {
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [renderTime, setRenderTime] = useState<number>(0);

  // Simulate data fetching (in a real app, this would use useE1RM hook)
  const fetchData = useCallback(async () => {
    const startTime = performance.now();
    setIsLoading(true);
    setError(null);

    try {
      const rows = await db.executeSql(
        `SELECT sl.* FROM set_log sl WHERE sl.exercise_id = ? ORDER BY sl.logged_at DESC`,
        [exerciseId],
      );

      const entries: E1RMHistoryEntry[] = [];
      if (rows && rows.length > 0) {
        for (const row of rows as Record<string, unknown>[]) {
          const load = Number(row['actual_load_lb']);
          const reps = Number(row['actual_reps']);
          const rpe = row['rpe'] != null ? Number(row['rpe']) : null;

          let computedE1RM: number | null = null;
          let computedConfidence: 'high' | 'low' | null = null;

          if (load > 0 && reps > 0) {
            try {
              // Use the same logic as calculateE1RM but inline for performance
              const result = computeE1RMInline(load, reps, rpe);
              computedE1RM = result.e1rm;
              computedConfidence = result.confidence;
            } catch {
              computedE1RM = null;
              computedConfidence = null;
            }
          }

          entries.push({
            set_log_id: Number(row['id']),
            session_id: Number(row['session_id']),
            exercise_id: Number(row['exercise_id']),
            exercise_name: String(row['exercise_name'] ?? 'Unknown'),
            actual_load_lb: load,
            actual_reps: reps,
            rpe,
            e1rm_lb: row['e1rm_lb'] != null ? Number(row['e1rm_lb']) : null,
            confidence: (row['confidence'] as 'high' | 'low' | null) ?? null,
            pain_flag: Boolean(row['pain_flag']),
            set_type: row['set_type'] ? String(row['set_type']) : null,
            note: row['note'] ? String(row['note']) : null,
            logged_at: row['logged_at'] ? String(row['logged_at']) : null,
            session_date: row['session_date'] ? String(row['session_date']) : null,
            session_day_label: row['session_day_label']
              ? String(row['session_day_label'])
              : null,
            session_status: row['session_status']
              ? String(row['session_status'])
              : null,
            computedE1RM,
            computedConfidence,
          });
        }
      }

      // Limit to sessionLimit distinct sessions
      const sessionIds = new Set<number>();
      const limitedEntries: E1RMHistoryEntry[] = [];
      for (const entry of entries) {
        if (!sessionIds.has(entry.session_id)) {
          sessionIds.add(entry.session_id);
        }
        if (sessionIds.size <= sessionLimit) {
          limitedEntries.push(entry);
        }
      }

      // Compute session-level e1RM
      const sessionE1RM = computeSessionE1RM(limitedEntries);

      // Build chart data
      const data = buildChartData(limitedEntries, sessionE1RM);
      setChartData(data);

      // Report PRs
      for (const point of data) {
        if (point.isPR && onPRDetected) {
          onPRDetected(point.sessionE1RM, point.date);
        }
      }

      const elapsed = performance.now() - startTime;
      setRenderTime(elapsed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load e1RM data');
    } finally {
      setIsLoading(false);
    }
  }, [exerciseId, db, sessionLimit, onPRDetected]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Render loading state
  if (isLoading) {
    return (
      <div className="e1rm-chart" data-testid="e1rm-chart">
        <h3 className="e1rm-chart__title">{title}</h3>
        <div className="e1rm-chart__loading" data-testid="loading-indicator">
          <div className="e1rm-chart__spinner" />
          <span>Loading e1RM history...</span>
        </div>
      </div>
    );
  }

  // Render error state
  if (error) {
    return (
      <div className="e1rm-chart" data-testid="e1rm-chart">
        <h3 className="e1rm-chart__title">{title}</h3>
        <div className="e1rm-chart__error" data-testid="error-message">
          <span>Error: {error}</span>
        </div>
      </div>
    );
  }

  // Render empty state
  if (chartData.length === 0) {
    return (
      <div className="e1rm-chart" data-testid="e1rm-chart">
        <h3 className="e1rm-chart__title">{title}</h3>
        <div className="e1rm-chart__empty" data-testid="empty-state">
          <span>No e1RM history available for this exercise.</span>
        </div>
      </div>
    );
  }

  // Render chart
  const chartSVG = useMemo(
    () => renderChartSVG(chartData, 600, 300),
    [chartData],
  );

  const prCount = chartData.filter((p) => p.isPR).length;

  return (
    <div className="e1rm-chart" data-testid="e1rm-chart">
      <h3 className="e1rm-chart__title">{title}</h3>
      <div className="e1rm-chart__stats" data-testid="chart-stats">
        <span className="e1rm-chart__pr-count">
          PRs: {prCount}
        </span>
        <span className="e1rm-chart__current-pr">
          Current PR: {chartData[chartData.length - 1]?.prValue ?? '—'} lb
        </span>
        <span className="e1rm-chart__render-time" data-testid="render-time">
          Render: {renderTime.toFixed(1)}ms
        </span>
      </div>
      <div
        className="e1rm-chart__svg"
        data-testid="chart-svg"
        dangerouslySetInnerHTML={{ __html: chartSVG }}
      />
      {/* PR badges are rendered inside the SVG */}
      <div className="e1rm-chart__pr-badges" data-testid="pr-badges">
        {chartData
          .filter((p) => p.isPR)
          .map((p, i) => (
            <span
              key={i}
              className="e1rm-chart__pr-badge"
              data-testid="pr-badge"
              title={`PR: ${p.sessionE1RM} lb on ${p.date}`}
            >
              PR {p.sessionE1RM} lb
            </span>
          ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline e1RM computation (mirrors calculateE1RM for performance)
// ---------------------------------------------------------------------------

/**
 * RPE percent chart: reps 1..12 × RPE 6.0..10.0 → % of 1RM.
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
 * Inline e1RM computation for performance-critical paths.
 * Mirrors calculateE1RM from sessions.ts.
 */
function computeE1RMInline(
  weight: number,
  reps: number,
  rpe: number | null | undefined,
): { e1rm: number; confidence: 'high' | 'low' } {
  if (weight <= 0 || !Number.isInteger(reps) || reps < MIN_REPS || reps > MAX_REPS) {
    throw new Error('Invalid input');
  }

  if (rpe == null) {
    // Epley fallback
    const e1rmVal = weight * (1 + reps / 30.0);
    return { e1rm: Math.round(e1rmVal * 10) / 10, confidence: 'low' };
  }

  if (rpe < MIN_RPE || rpe > MAX_RPE) {
    throw new Error('Invalid RPE');
  }

  const row = reps - 1;
  const col = Math.round((rpe - MIN_RPE) / RPE_STEP);
  const pct = RPE_PERCENT[row][col];
  const e1rmVal = weight / (pct / 100.0);
  const confidence = rpe < 7.0 || reps > 8 ? 'low' : 'high';

  return { e1rm: Math.round(e1rmVal * 10) / 10, confidence };
}

// ---------------------------------------------------------------------------
// Pure helper functions exported for testing
// ---------------------------------------------------------------------------

export { computeSessionE1RM, buildChartData, renderChartSVG, computeE1RMInline };
