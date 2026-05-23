/**
 * usePilotFlow — Pattern C state machine (regex eager, LLM on Enter).
 *
 * Flow:
 *
 *   typing  ← user edits the input. setText fires `api.parse(text, "regex")`
 *             debounced ~150ms. Regex is in-process + free + instant, so we
 *             can call it on nearly every keystroke without cost.
 *
 *   ready   ← regex matched. Plan is renderable. User can hit Run.
 *
 *   parsing ← user pressed Enter on text that regex didn't match. We
 *             fire `api.parse(text, "auto")` which goes through the LLM.
 *             3-12s wait while Haiku thinks.
 *
 *   running ← user pressed Run on a ready plan. POST /execute fires;
 *             client-side step timer advances the visual progress.
 *
 *   done    ← execute returned success.
 *
 * Key design points (different from Phase 4 v1):
 *
 * 1. **No eager LLM.** Typing never triggers Haiku. The user has to press
 *    Enter on a paraphrase to opt in. Eliminates wasted LLM calls on
 *    intermediate drafts.
 *
 * 2. **Regex-only mode** returns `error="no_regex_match"` as a sentinel —
 *    not a real failure. We expose it via `regexMissed` so the UI can
 *    show a "press ⏎ to ask Haiku" hint instead of a red error toast.
 *
 * 3. **Enter is overloaded.**
 *    - If parseResult has a runnable plan → run it.
 *    - If parseResult is null + text non-empty → fire LLM parse.
 *    - If text is empty → no-op.
 *
 *    Pattern shared with Cursor compose / many AI editors.
 *
 * 4. **Stale results clear cleanly.** Whenever the regex parse comes
 *    back as no-match, we null out parseResult. No ghost-state from
 *    the previous command lingers.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api,
  type ParseResponse,
  type SuggestionPayload,
} from '../api/client';
import { type HistoryEntry, type Phase } from '../types';

const REGEX_DEBOUNCE_MS = 150;
/** How long the suggestion card stays visible before the auto-load
 *  fires. Long enough to read the reasoning + hit Cancel, short
 *  enough not to feel sluggish. See D-019. */
const AUTO_LOAD_COUNTDOWN_MS = 1500;

export interface PilotFlowApi {
  phase: Phase;
  text: string;
  setText: (text: string) => void;
  parseResult: ParseResponse | null;
  executed: number;
  history: HistoryEntry[];
  error: string | null;
  suggestion: SuggestionPayload | null;
  /** True when the most recent regex parse returned no_regex_match.
   *  UI uses this to show the "press ⏎ to ask Haiku" hint. */
  regexMissed: boolean;
  /** Triggered by Enter or the Run button.
   *  - If a plan is ready → run it.
   *  - If no plan + text has content → fire LLM parse. */
  onSubmit: () => void;
  /** Cancel the in-flight auto-load countdown. Clears the suggestion
   *  + plan so the user can re-type. No-op if no countdown is active. */
  onCancelAutoLoad: () => void;
  /** True while an auto-load countdown is in flight (suggestion shown,
   *  /execute will fire after AUTO_LOAD_COUNTDOWN_MS). UI uses this
   *  to drive the countdown bar + show the Cancel button. */
  autoLoadPending: boolean;
  /** Countdown total in ms — exposed so the UI can size animations
   *  without hard-coding the constant. */
  autoLoadCountdownMs: number;
  onUndoEntry: (idx: number) => void;
  onReset: () => void;
}

export function usePilotFlow(): PilotFlowApi {
  const [text, setText_] = useState('');
  const [phase, setPhase] = useState<Phase>('typing');
  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [executed, setExecuted] = useState(-1);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<SuggestionPayload | null>(null);
  const [regexMissed, setRegexMissed] = useState(false);

  const parseAbortRef = useRef<AbortController | null>(null);
  const executeAbortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stepTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoLoadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [autoLoadPending, setAutoLoadPending] = useState(false);

  const cancelAutoLoadTimer = () => {
    if (autoLoadTimerRef.current) {
      clearTimeout(autoLoadTimerRef.current);
      autoLoadTimerRef.current = null;
    }
    setAutoLoadPending(false);
  };

  // ── Eager regex parse ─────────────────────────────────────────────────

  const setText = useCallback((next: string) => {
    setText_(next);
    setError(null);
    setSuggestion(null);
    // Any keystroke cancels a pending auto-load — user is re-typing,
    // they probably don't want the previous suggestion to fire.
    cancelAutoLoadTimer();

    // Empty input → full reset.
    if (!next.trim()) {
      setPhase('typing');
      setParseResult(null);
      setExecuted(-1);
      setRegexMissed(false);
      parseAbortRef.current?.abort();
      if (debounceRef.current) clearTimeout(debounceRef.current);
      return;
    }

    // Abort any in-flight regex parse + restart the debounce.
    parseAbortRef.current?.abort();
    if (debounceRef.current) clearTimeout(debounceRef.current);

    // Clear the previous parse result eagerly so a stale plan from the
    // previous command doesn't ghost during the 150ms debounce window.
    // Pulled out separately from the empty-input branch so the user
    // gets clean state on every edit, not just on full clear.
    setParseResult(null);
    setExecuted(-1);
    setRegexMissed(false);
    setPhase('typing');

    debounceRef.current = setTimeout(() => {
      void runRegexParse(next);
    }, REGEX_DEBOUNCE_MS);
  }, []);

  const runRegexParse = async (textToParse: string) => {
    const controller = new AbortController();
    parseAbortRef.current = controller;

    try {
      const res = await api.parse(textToParse, 'regex', controller.signal);
      if (controller.signal.aborted) return;

      if (res.error === 'no_regex_match') {
        // No regex pattern matched — user can press Enter to ask the LLM.
        setParseResult(null);
        setPhase('typing');
        setRegexMissed(true);
        return;
      }

      if (res.error) {
        setError(res.error);
        setParseResult(null);
        setPhase('typing');
        setRegexMissed(false);
        return;
      }

      // Regex matched — full plan is ready.
      setParseResult(res);
      setPhase('ready');
      setRegexMissed(false);
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setError((err as Error).message);
      setPhase('typing');
    }
  };

  // ── LLM parse via streaming (only fired by Enter / submit) ────────────
  //
  // Uses POST /parse/stream so plan steps populate progressively as
  // Haiku generates them. The hook maintains a growing parseResult
  // whose .plan array gets a new entry per `step` event. CommandCard
  // re-renders the plan area on every change so the user sees steps
  // pop in one-by-one.

  const runLlmParse = async () => {
    if (!text.trim()) return;
    setPhase('parsing');
    setError(null);
    setSuggestion(null);
    setRegexMissed(false);

    // Seed an empty ParseResponse so the plan area has something to
    // grow into. The display strings stay placeholder-ish until the
    // 'complete' event delivers the real summary.
    setParseResult({
      text,
      parsed: '(streaming…)',
      conf: 95,
      affects: '—',
      source: 'llm',
      plan: [],
      suggestion: null,
      schedule: null,
      error: null,
    });
    setExecuted(-1);

    const controller = new AbortController();
    parseAbortRef.current?.abort();
    parseAbortRef.current = controller;

    try {
      for await (const event of api.parseStream(text, controller.signal)) {
        if (controller.signal.aborted) return;

        if (event.type === 'started') continue;

        if (event.type === 'step') {
          // Append the streamed step to the growing plan. React's
          // immutable update pattern — new array, same other fields.
          setParseResult((prev) =>
            prev ? { ...prev, plan: [...prev.plan, event.step] } : prev,
          );
          continue;
        }

        if (event.type === 'complete') {
          // Replace the partial result with the fully-formed response.
          // The plan should be identical to what we accumulated, but
          // the summary fields (parsed, affects, conf) now have real
          // values + any suggestion is attached.
          setParseResult(event.response);
          if (event.response.suggestion) {
            setSuggestion(event.response.suggestion);
          }
          setPhase('ready');
          return;
        }

        if (event.type === 'error') {
          setError(event.message);
          setPhase('typing');
          setParseResult(null);
          return;
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setError((err as Error).message);
      setPhase('typing');
      setParseResult(null);
    }
  };

  // ── Execute ──────────────────────────────────────────────────────────

  const clearStepTimer = () => {
    if (stepTimerRef.current) {
      clearTimeout(stepTimerRef.current);
      stepTimerRef.current = null;
    }
  };

  const runPlan = (toRun: ParseResponse) => {
    if (toRun.plan.length === 0) return;

    setExecuted(0);
    setPhase('running');
    setError(null);

    let i = 0;
    const advance = () => {
      i += 1;
      if (i < toRun.plan.length) {
        setExecuted(i);
        stepTimerRef.current = setTimeout(advance, toRun.plan[i].dMs);
      }
    };
    stepTimerRef.current = setTimeout(advance, toRun.plan[0].dMs);

    const controller = new AbortController();
    executeAbortRef.current = controller;

    void api
      .execute(toRun.plan, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        clearStepTimer();

        if (!res.success) {
          setError(res.error ?? 'Execute failed.');
          setPhase('ready');
          return;
        }

        if (res.suggestion) {
          setSuggestion(res.suggestion);
          setPhase('ready');
          return;
        }

        setExecuted(toRun.plan.length);
        setPhase('done');

        setHistory((h) => [
          {
            when: 'just now',
            prompt: toRun.text,
            parsed: toRun.parsed,
            summary: `Ran ${toRun.plan.length}-step plan via ${toRun.source}.`,
            isNew: true,
          },
          ...h.slice(0, 9),
        ]);
      })
      .catch((err) => {
        if ((err as Error).name === 'AbortError') return;
        clearStepTimer();
        setError((err as Error).message);
        setPhase('ready');
      });
  };

  // ── Auto-load countdown ──────────────────────────────────────────────
  //
  // When a parse returns a suggestion marked auto_loadable (D-019:
  // backend's GUI adapter is wired AND the title+artist is unique in
  // the library), kick off a 1.5s countdown then auto-fire /execute.
  // The card stays visible during the countdown so the user can see
  // the AI's pick + reasoning + cancel if they want a different one.

  useEffect(() => {
    if (!suggestion?.auto_loadable) return;
    if (!parseResult || parseResult.plan.length === 0) return;

    const planToRun = parseResult;
    setAutoLoadPending(true);

    autoLoadTimerRef.current = setTimeout(() => {
      autoLoadTimerRef.current = null;
      setAutoLoadPending(false);
      // Hide the preview as we hand off to the running phase — the
      // plan timeline takes over the visual focus from here.
      setSuggestion(null);
      runPlan(planToRun);
    }, AUTO_LOAD_COUNTDOWN_MS);

    return () => {
      if (autoLoadTimerRef.current) {
        clearTimeout(autoLoadTimerRef.current);
        autoLoadTimerRef.current = null;
      }
      setAutoLoadPending(false);
    };
    // runPlan is intentionally not in the dep array — it's recreated
    // every render and would cause the effect to re-run constantly,
    // racing the timeout. The closure captures the right runPlan for
    // the render where the suggestion first arrived, which is what
    // we want.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestion, parseResult]);

  const onCancelAutoLoad = useCallback(() => {
    cancelAutoLoadTimer();
    setSuggestion(null);
    setParseResult(null);
    setExecuted(-1);
    setPhase('typing');
  }, []);

  // ── Agent: dispatch a schedule to /agent/start (D-021) ────────────────
  //
  // Goal-style prompts (with "then" / "when X ends" / etc.) come back
  // from /parse as schedule responses. They run autonomously via the
  // backend's AgentRuntime — the frontend just kicks them off, then
  // useAgentState polling drives the AgentQueue UI.

  const runSchedule = (toRun: ParseResponse) => {
    if (!toRun.schedule || toRun.schedule.length === 0) return;

    setPhase('running');
    setError(null);
    setExecuted(-1);

    const controller = new AbortController();
    executeAbortRef.current = controller;

    void api
      .agentStart(toRun.schedule, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        if (!res.success) {
          setError(res.error ?? 'Agent start failed.');
          setPhase('ready');
          return;
        }
        // Schedule is running on the backend. Phase stays at 'running'
        // to dim the input area; useAgentState polling updates the
        // AgentQueue UI. The user sees "done" when they cancel or all
        // steps complete (polling reflects active=false).
        setHistory((h) => [
          {
            when: 'just now',
            prompt: toRun.text,
            parsed: toRun.parsed,
            summary: `Started ${toRun.schedule!.length}-step agent schedule.`,
            isNew: true,
          },
          ...h.slice(0, 9),
        ]);
        setPhase('done');
      })
      .catch((err) => {
        if ((err as Error).name === 'AbortError') return;
        setError((err as Error).message);
        setPhase('ready');
      });
  };

  // ── onSubmit (Enter / Run button) ─────────────────────────────────────

  const onSubmit = useCallback(() => {
    if (phase === 'running' || phase === 'parsing') return;
    if (suggestion) return; // can't run suggestions

    // Schedule trumps plan — goal-style prompts go to the agent
    // runtime, not the synchronous executor.
    if (parseResult && parseResult.schedule && parseResult.schedule.length > 0) {
      runSchedule(parseResult);
      return;
    }

    if (parseResult && parseResult.plan.length > 0) {
      runPlan(parseResult);
      return;
    }

    // No plan yet — user wants the LLM to take a swing.
    if (text.trim()) {
      void runLlmParse();
    }
  }, [phase, parseResult, suggestion, text]);

  // ── Reset Mixxx ──────────────────────────────────────────────────────

  const onReset = useCallback(() => {
    void api.reset().then((res) => {
      if (!res.success) setError(res.error ?? 'Reset failed.');
      else {
        setHistory((h) => [
          {
            when: 'just now',
            prompt: 'reset mixxx',
            parsed: 'system.reset()',
            summary: 'All decks paused, crossfader centred, EQs neutral.',
            isNew: true,
          },
          ...h.slice(0, 9),
        ]);
      }
    });
  }, []);

  // ── Undo a history entry ─────────────────────────────────────────────

  const onUndoEntry = useCallback((idx: number) => {
    setHistory((h) => h.map((entry, i) => (i === idx ? { ...entry, isNew: false } : entry)));
  }, []);

  // ── Cleanup ──────────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      parseAbortRef.current?.abort();
      executeAbortRef.current?.abort();
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (autoLoadTimerRef.current) clearTimeout(autoLoadTimerRef.current);
      clearStepTimer();
    };
  }, []);

  return {
    phase,
    text,
    setText,
    parseResult,
    executed,
    history,
    error,
    suggestion,
    regexMissed,
    autoLoadPending,
    autoLoadCountdownMs: AUTO_LOAD_COUNTDOWN_MS,
    onSubmit,
    onCancelAutoLoad,
    onUndoEntry,
    onReset,
  };
}
