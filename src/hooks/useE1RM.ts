/**
 * Strongman Coach – useE1RM React hook.
 *
 * Fetches session history for an exercise via the database layer,
 * computes per-set e1RM values, and exposes the history together
 * with the current (highest high-confidence) e1RM.
 *
 * Designed to work inside a React Query (TanStack Query) provider
 * so that data is cached and persisted across renders.
 */

import { useMemo } from 'react';
import { useQuery, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { getForExercise, calculateE1RM, SetLogEntry } from '../database/sessions';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface E1RMHistoryEntry extends SetLogEntry {
  /** Computed e1RM for this set (may differ from stored e1rm_lb). */
  computedE1RM: number | null;
  /** Confidence of the computed e1RM. */
  computedConfidence: 'high' | 'low' | null;
}

export interface UseE1RMResult {
  /** Full history of sets with computed e1RM values. */
  e1rmHistory: E1RMHistoryEntry[];
  /** Highest high-confidence e1RM across all sets (current best). */
  currentE1RM: number | null;
  /** Whether the query is still loading. */
  isLoading: boolean;
  /** Error if the query failed. */
  error: Error | null;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Enrich a raw SetLogEntry with computed e1RM values.
 * Returns null for the computed fields if the set has invalid data.
 */
function enrichWithE1RM(entry: SetLogEntry): E1RMHistoryEntry {
  let computedE1RM: number | null = null;
  let computedConfidence: 'high' | 'low' | null = null;

  try {
    // Only compute if we have valid weight and reps
    if (
      entry.actual_load_lb != null &&
      entry.actual_load_lb > 0 &&
      entry.actual_reps != null &&
      entry.actual_reps > 0
    ) {
      const result = calculateE1RM(
        entry.actual_load_lb,
        entry.actual_reps,
        entry.rpe ?? undefined,
      );
      computedE1RM = result.e1rm;
      computedConfidence = result.confidence;
    }
  } catch {
    // Guard against invalid RPE/rep inputs – return null rather than crash
    computedE1RM = null;
    computedConfidence = null;
  }

  return {
    ...entry,
    computedE1RM,
    computedConfidence,
  };
}

/**
 * Derive the current best e1RM from a list of enriched entries.
 * Only considers high-confidence entries.
 */
function deriveCurrentE1RM(history: E1RMHistoryEntry[]): number | null {
  if (!history || history.length === 0) {
    return null;
  }

  const highConfidence = history.filter(
    (e) => e.computedConfidence === 'high' && e.computedE1RM != null,
  );

  if (highConfidence.length === 0) {
    return null;
  }

  return Math.max(...highConfidence.map((e) => e.computedE1RM as number));
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * React hook that fetches and computes e1RM history for an exercise.
 *
 * @param exerciseId – primary key in the exercise table
 * @param db – expo-sqlite database instance (or mock in tests)
 * @param limit – max distinct sessions to fetch (default 30)
 * @returns e1rmHistory, currentE1RM, isLoading, error
 */
export function useE1RM(
  exerciseId: number,
  db: import('../database/sessions').SQLiteDatabase,
  limit: number = 30,
): UseE1RMResult {
  const queryKey = ['e1rm-history', exerciseId, limit];

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async () => {
      const rows = await getForExercise(db, exerciseId, limit);
      return rows.map(enrichWithE1RM);
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
    retry: 1,
  });

  const e1rmHistory = useMemo(() => {
    if (!data || data.length === 0) {
      return [];
    }
    return data;
  }, [data]);

  const currentE1RM = useMemo(() => {
    return deriveCurrentE1RM(e1rmHistory);
  }, [e1rmHistory]);

  return {
    e1rmHistory,
    currentE1RM,
    isLoading,
    error: error instanceof Error ? error : null,
  };
}

// ---------------------------------------------------------------------------
// Test helpers – exported so tests can wrap components in QueryClientProvider
// ---------------------------------------------------------------------------

/**
 * Create a fresh QueryClient for testing.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
      },
    },
  });
}

/**
 * Render a component inside a QueryClientProvider for testing.
 * Returns the QueryClient so tests can call `queryClient.clear()` etc.
 */
export function wrapWithQueryClient(
  component: unknown,
  queryClient?: QueryClient,
): { rendered: unknown; client: QueryClient } {
  const client = queryClient ?? createTestQueryClient();
  // In a real React app this would be <QueryClientProvider client={client}>{component}</QueryClientProvider>
  // For testing we just return the client so the test can prefetch
  return { rendered: component, client };
}
