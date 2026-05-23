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
  /** True when the backend's GUI adapter can auto-load this track
   *  (title+artist uniquely identifies one library row). UI then
   *  shows a 1.5s countdown + Cancel button and auto-fires /execute.
   *  False → fall back to the manual-drag hint. See D-019. */
  auto_loadable: boolean;
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

// ── SSE streaming helpers (used by parseStream) ──────────────────────────

/** One decoded event from a Server-Sent Events stream. */
type SSEBlock = { event: string; data: string };

/** Parse a single SSE block (everything between two blank lines).
 *  Format per RFC: each line is `event: <name>` or `data: <payload>`. */
function decodeSSEBlock(block: string): SSEBlock | null {
  let event = '';
  let data = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim();
    else if (line.startsWith('data: ')) data = line.slice(6);
  }
  return event ? { event, data } : null;
}

/** Discriminated union for events the /parse/stream endpoint emits. */
export type ParseStreamEvent =
  | { type: 'started' }
  | { type: 'step'; index: number; step: PlanStepPayload }
  | { type: 'complete'; response: ParseResponse }
  | { type: 'error'; message: string };

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

  /**
   * Stream-parse the text via the LLM. Yields events as Haiku
   * generates them: `started` immediately, one `step` per completed
   * plan-step JSON object, then a final `complete` with the full
   * structured ParseResponse (matching what /parse would return).
   *
   * Why: regex parses are instant; LLM parses take 2-7s. Streaming
   * lets the UI populate plan steps as they arrive instead of waiting
   * for the whole response. See DECISIONS § D-020 for the why.
   *
   * Errors are yielded as `{type: 'error'}` events, NOT thrown — keeps
   * the consumer's logic in one place. Network failures DO throw.
   */
  async *parseStream(
    text: string,
    signal?: AbortSignal,
  ): AsyncIterableIterator<ParseStreamEvent> {
    const res = await fetch(`${BASE}/parse/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, mode: 'llm' }),
      signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(
        `/parse/stream ${res.status}: ${res.statusText || 'no body'}`,
      );
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE events are separated by a blank line — two consecutive
        // newlines. Each event has `event: <name>` + `data: <json>`.
        let idx;
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const decoded = decodeSSEBlock(block);
          if (!decoded) continue;

          try {
            const payload = decoded.data ? JSON.parse(decoded.data) : {};
            yield { type: decoded.event, ...payload } as ParseStreamEvent;
          } catch {
            // Malformed JSON — skip silently. The final `complete`
            // event is the source of truth for the structured plan;
            // missing one `step` is purely cosmetic.
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
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
