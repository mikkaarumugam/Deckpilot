/**
 * Shared types lifted from design/pilot.jsx + extended for the real backend.
 *
 * The phase machine and step state stay identical to the design's vocabulary
 * so the visual logic ports straight across. Backend payload shapes
 * (PlanStep, Track, DeckState) are aligned with what the FastAPI server
 * will return in Phase 3 — close to but not identical to the design's mock
 * shape, since the real parser carries an `at_seconds` float and not a
 * pre-formatted "t" string.
 */

/** Five-state machine that drives the hero card UI. */
export type Phase = 'typing' | 'parsing' | 'ready' | 'running' | 'done';

/** Per-plan-step render state. Hidden = not yet streamed in by the parser. */
export type PlanStepState = 'hidden' | 'pending' | 'running' | 'done';

/** Deck transport state. Sourced from MixxxFeedback once Phase 4 lands. */
export type DeckStatus = 'playing' | 'paused' | 'cued';

/**
 * One step in an ActionPlan, as the UI consumes it.
 *
 * - `fn` and `detail` are the display strings (signature + human description).
 * - `t` is a pre-formatted duration label (e.g. "4.0s") or "—" for instant
 *   actions. The backend builds this from `at_seconds` + the action's known
 *   duration; we don't recompute on the client.
 * - `dMs` is execution-window milliseconds — used during the running phase to
 *   drive the per-step progress bar. The backend supplies a default; for
 *   regex-fast-path single steps this is small.
 */
export interface PlanStepData {
  fn: string;
  detail: string;
  t: string;
  dMs: number;
}

/** A single library track loaded on (or available for) a deck. */
export interface Track {
  id: number;
  artist: string;
  title: string;
  bpm: number;
  key: string;
  genre: string;
  location: string;
}

/** Live state of one deck, polled from GET /state. */
export interface DeckState {
  n: 1 | 2;
  status: DeckStatus;
  bpm: number;
  /** Loaded track, if known. Sourced from library lookup against live BPM. */
  track: Track | null;
  /** Progress within the loaded track. May be unknown without playhead read-back. */
  progress: { t: string; total: string; pct: number };
}

/** A parsed command waiting to be (or already) executed. */
export interface ParseResult {
  text: string;
  parsed: string;
  conf: number;
  affects: string;
  plan: PlanStepData[];
}

/** History entry — one completed command + its outcome. */
export interface HistoryEntry {
  when: string;
  prompt: string;
  parsed: string;
  summary: string;
  diff?: { from: string; to: string };
  isNew?: boolean;
}
