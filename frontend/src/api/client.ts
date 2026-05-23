/**
 * Typed fetch wrappers for the FastAPI backend.
 *
 * One file, no client library. Native `fetch` is enough at this scale and
 * adding TanStack Query / SWR would be premature.
 *
 * Base URL is read from `VITE_API_BASE` if set, otherwise falls back to
 * `http://localhost:8000`. For prod (which isn't on the roadmap) the
 * frontend would be served from the same origin as the API and this could
 * become a relative path.
 */

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000';

// ── Wire types — mirror backend/models.py one-to-one ─────────────────────

export interface TrackPayload {
  id: number;
  artist: string;
  title: string;
  bpm: number;
  key: string;
  genre: string;
}

export interface ProgressPayload {
  t: string;
  total: string;
  pct: number;
}

export interface DeckStatePayload {
  n: 1 | 2;
  status: 'playing' | 'paused' | 'cued';
  bpm: number;
  track: TrackPayload | null;
  progress: ProgressPayload;
}

export interface StateResponse {
  decks: DeckStatePayload[];
  crossfade: number | null;
  bpm_delta: number | null;
}

export interface PlanStepPayload {
  action: Record<string, unknown>;
  at_seconds: number;
  fn: string;
  detail: string;
  t: string;
  dMs: number;
}

export interface SuggestionPayload {
  track: TrackPayload;
  deck: number;
  reasoning: string;
}

export interface ParseResponse {
  text: string;
  parsed: string;
  conf: number;
  affects: string;
  source: 'regex' | 'llm';
  plan: PlanStepPayload[];
  suggestion: SuggestionPayload | null;
  error: string | null;
}

export interface ExecuteResponse {
  success: boolean;
  elapsed_ms: number;
  error: string | null;
  suggestion: SuggestionPayload | null;
}

export interface UndoResponse {
  success: boolean;
  inverted_plan: PlanStepPayload[] | null;
  error: string | null;
}

// ── HTTP helpers ─────────────────────────────────────────────────────────

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path} ${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { signal });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${path} ${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

// ── Public API ───────────────────────────────────────────────────────────

export const api = {
  /**
   * Parse text into a plan. `mode="regex"` skips the LLM (used by the
   * eager-on-keystroke flow); `mode="auto"` (default) runs regex first
   * then falls back to LLM. Errors with `error="no_regex_match"` aren't
   * real failures — they're the regex-only "you'd need the LLM to handle
   * this" signal.
   */
  parse(
    text: string,
    mode: 'auto' | 'regex' | 'llm' = 'auto',
    signal?: AbortSignal,
  ): Promise<ParseResponse> {
    return postJson<ParseResponse>('/parse', { text, mode }, signal);
  },

  execute(plan: PlanStepPayload[], signal?: AbortSignal): Promise<ExecuteResponse> {
    return postJson<ExecuteResponse>('/execute', { plan }, signal);
  },

  state(signal?: AbortSignal): Promise<StateResponse> {
    return getJson<StateResponse>('/state', signal);
  },

  undo(plan: PlanStepPayload[], signal?: AbortSignal): Promise<UndoResponse> {
    return postJson<UndoResponse>('/undo', { plan }, signal);
  },

  reset(signal?: AbortSignal): Promise<UndoResponse> {
    return postJson<UndoResponse>('/reset', {}, signal);
  },
};
