/**
 * usePilotFlow — drives the phase machine + the demoable examples.
 *
 * **PHASE 2 IMPLEMENTATION** — the auto-cycling demo state machine, ported
 * straight from design/pilot.jsx (lines 122-210). This is intentionally a
 * fake flow that cycles through 4 hardcoded examples so the component
 * visuals can be verified without a backend.
 *
 * **PHASE 4 WILL REPLACE THIS** with real wiring:
 *
 *   typing  ← user input (debounced)
 *   parsing ← POST /parse  (FastAPI, wraps deckpilot.core.parser.parse)
 *   ready   ← parse response received
 *   running ← POST /execute (executor walks the plan, MIDI fires)
 *   done    ← all steps completed (polled via GET /state)
 *
 * Keep the same {phase, typed, revealed, executed, elapsed, example, exampleIdx}
 * shape so CommandCard + Pilot don't change between phases. Only this hook's
 * body is rewritten in Phase 4.
 */

import { useEffect, useRef, useState } from 'react';
import { type Phase, type PlanStepData } from '../types';

export interface PilotExample {
  text: string;
  parsed: string;
  conf: number;
  affects: string;
  plan: PlanStepData[];
}

// Hardcoded examples lifted verbatim from design/pilot.jsx lines 76-118 so the
// visuals match the design canvas exactly. Phase 4 will source these via the
// real parser; this list disappears entirely at that point.
const PILOT_EXAMPLES: PilotExample[] = [
  {
    text: 'bass swap into deck 2 over 4 seconds',
    parsed: 'swap.bass(deck:1 → deck:2, t:4s)',
    conf: 96,
    affects: 'deck 1 · deck 2',
    plan: [
      { fn: 'eq.low(deck:1)', detail: 'ramp  0.0 dB  →  −∞', t: '4.0s', dMs: 780 },
      { fn: 'eq.low(deck:2)', detail: 'ramp  −∞  →  0.0 dB', t: '4.0s', dMs: 780 },
      { fn: 'crossfade', detail: 'target  −100  →  +100', t: '4.0s', dMs: 780 },
    ],
  },
  {
    text: 'match deck 2 tempo to deck 1',
    parsed: 'tempo.sync(deck:2 → deck:1)',
    conf: 94,
    affects: 'deck 2',
    plan: [
      { fn: 'tempo.read(deck:1)', detail: 'target  =  116.2 BPM', t: '—', dMs: 600 },
      { fn: 'tempo.set(deck:2)', detail: '124.0  →  116.2  ( −6.3 % )', t: '—', dMs: 800 },
      { fn: 'phase.align(deck:2)', detail: 'nudge to nearest downbeat', t: '~1s', dMs: 700 },
    ],
  },
  {
    text: 'kill the bass on deck 1',
    parsed: 'eq.low(deck:1) = -inf',
    conf: 99,
    affects: 'deck 1',
    plan: [{ fn: 'eq.low(deck:1)', detail: 'set  0.0 dB  →  −∞', t: '—', dMs: 1100 }],
  },
  {
    text: 'loop deck 1 for 8 beats',
    parsed: 'loop(deck:1, beats:8)',
    conf: 98,
    affects: 'deck 1',
    plan: [
      { fn: 'loop.set(deck:1)', detail: 'length  8 beats  @ next bar', t: '—', dMs: 850 },
      { fn: 'loop.enable(deck:1)', detail: 'engage on downbeat', t: '—', dMs: 850 },
    ],
  },
];

export interface PilotFlowState {
  phase: Phase;
  typed: number;
  revealed: number;
  executed: number;
  elapsed: number;
  example: PilotExample;
  exampleIdx: number;
}

export function usePilotFlow(): PilotFlowState {
  const [exampleIdx, setExampleIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>('typing');
  const [typed, setTyped] = useState(0);
  const [revealed, setRevealed] = useState(0);
  const [executed, setExecuted] = useState(-1);
  const startedAt = useRef(0);
  const [elapsed, setElapsed] = useState(0);

  const example = PILOT_EXAMPLES[exampleIdx];
  const totalSteps = example.plan.length;

  // Typing: char-by-char with slight jitter so it feels natural, not robotic.
  useEffect(() => {
    if (phase !== 'typing') return;
    if (typed < example.text.length) {
      const t = setTimeout(() => setTyped((c) => c + 1), 38 + Math.random() * 28);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => {
      setRevealed(0);
      setPhase('parsing');
    }, 650);
    return () => clearTimeout(t);
  }, [phase, typed, example.text.length]);

  // Parsing: stream plan steps in one at a time.
  useEffect(() => {
    if (phase !== 'parsing') return;
    if (revealed < totalSteps) {
      const t = setTimeout(() => setRevealed((r) => r + 1), 320);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setPhase('ready'), 260);
    return () => clearTimeout(t);
  }, [phase, revealed, totalSteps]);

  // Ready: hold so the viewer can read the plan, then auto-run.
  useEffect(() => {
    if (phase !== 'ready') return;
    const t = setTimeout(() => {
      setExecuted(0);
      setPhase('running');
      startedAt.current = performance.now();
    }, 2100);
    return () => clearTimeout(t);
  }, [phase]);

  // Running: drive elapsed on the active step; advance when its dMs elapses.
  useEffect(() => {
    if (phase !== 'running') return;
    if (executed < 0 || executed >= totalSteps) return;
    startedAt.current = performance.now();
    setElapsed(0);
    let raf = 0;
    let gap: ReturnType<typeof setTimeout> | undefined;
    const tick = () => {
      const dt = performance.now() - startedAt.current;
      setElapsed(dt);
      if (dt < example.plan[executed].dMs) {
        raf = requestAnimationFrame(tick);
      } else {
        gap = setTimeout(() => {
          if (executed + 1 < totalSteps) setExecuted(executed + 1);
          else setPhase('done');
        }, 160);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      if (gap) clearTimeout(gap);
    };
  }, [phase, executed, totalSteps, example.plan]);

  // Done: hold, then cycle to the next example.
  useEffect(() => {
    if (phase !== 'done') return;
    const t = setTimeout(() => {
      setExampleIdx((i) => (i + 1) % PILOT_EXAMPLES.length);
      setTyped(0);
      setRevealed(0);
      setExecuted(-1);
      setElapsed(0);
      setPhase('typing');
    }, 2600);
    return () => clearTimeout(t);
  }, [phase]);

  return { phase, typed, revealed, executed, elapsed, example, exampleIdx };
}
