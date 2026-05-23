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

  // ── Eager regex parse ─────────────────────────────────────────────────

  const setText = useCallback((next: string) => {
    setText_(next);
    setError(null);
    setSuggestion(null);

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

    // Stay in 'typing' until regex confirms a match.
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

  // ── LLM parse (only fired by Enter / submit) ──────────────────────────

  const runLlmParse = async () => {
    if (!text.trim()) return;
    setPhase('parsing');
    setError(null);
    setSuggestion(null);
    setRegexMissed(false);

    const controller = new AbortController();
    parseAbortRef.current?.abort();
    parseAbortRef.current = controller;

    try {
      const res = await api.parse(text, 'auto', controller.signal);
      if (controller.signal.aborted) return;

      if (res.error && res.error !== 'no_regex_match') {
        setError(res.error);
        setPhase('typing');
        setParseResult(null);
        return;
      }

      if (res.suggestion) {
        setSuggestion(res.suggestion);
        setParseResult(res);
        setPhase('ready');
        return;
      }

      setParseResult(res);
      setPhase('ready');
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setError((err as Error).message);
      setPhase('typing');
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

  // ── onSubmit (Enter / Run button) ─────────────────────────────────────

  const onSubmit = useCallback(() => {
    if (phase === 'running' || phase === 'parsing') return;
    if (suggestion) return; // can't run suggestions

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
    onSubmit,
    onUndoEntry,
    onReset,
  };
}
