// pilot.jsx — Direction A: AI-native companion.
// State machine: typing → parsing → ready → running → done → next.
// Theme tokens are CSS variables on the wrapper so Tweaks can swap them live.

const { useState, useEffect, useRef } = React;

// ── Theme tokens (resolve to CSS vars on the wrapper) ───────────────────────
const pilotTheme = {
  bg: 'var(--p-bg)',
  surface: 'var(--p-surface)',
  surfaceHi: 'var(--p-surface-hi)',
  border: 'var(--p-border)',
  borderStrong: 'var(--p-border-strong)',
  fg: 'var(--p-fg)',
  fgDim: 'var(--p-fg-dim)',
  muted: 'var(--p-muted)',
  mutedDeep: 'var(--p-muted-deep)',
  accent: 'var(--p-accent)',
  accentDim: 'var(--p-accent-dim)',
  accentEdge: 'var(--p-accent-edge)',
  accentInk: 'var(--p-accent-ink)',
  live: 'var(--p-live)',
  liveDim: 'var(--p-live-dim)',
  sans: 'var(--p-sans)',
  serif: 'var(--p-serif)',
  mono: 'var(--p-mono)',
};

const PILOT_DARK = {
  '--p-bg': '#0c0b09',
  '--p-surface': '#16140f',
  '--p-surface-hi': '#1d1a14',
  '--p-border': 'rgba(255,236,200,0.07)',
  '--p-border-strong': 'rgba(255,236,200,0.14)',
  '--p-fg': '#f1ebe0',
  '--p-fg-dim': '#bdb6a8',
  '--p-muted': '#7a7468',
  '--p-muted-deep': '#534e44',
  '--p-live': '#9ec98a',
  '--p-live-dim': 'rgba(158,201,138,0.18)',
};

const PILOT_LIGHT = {
  '--p-bg': '#f4efe2',
  '--p-surface': '#fbf7eb',
  '--p-surface-hi': '#ffffff',
  '--p-border': 'rgba(36,28,14,0.10)',
  '--p-border-strong': 'rgba(36,28,14,0.20)',
  '--p-fg': '#1c1812',
  '--p-fg-dim': '#4a4337',
  '--p-muted': '#8a8170',
  '--p-muted-deep': '#b6ad99',
  '--p-live': '#4d8a39',
  '--p-live-dim': 'rgba(77,138,57,0.16)',
};

// Build the full CSS vars object given a tweak state. Accent / serif overlay.
function buildPilotVars({ accent, serif, theme }) {
  const base = theme === 'light' ? PILOT_LIGHT : PILOT_DARK;
  return {
    ...base,
    '--p-accent': accent,
    '--p-accent-dim': `color-mix(in srgb, ${accent} 16%, transparent)`,
    '--p-accent-edge': `color-mix(in srgb, ${accent} 38%, transparent)`,
    // ink = a deeply tinted version of accent that reads on top of accent bg
    '--p-accent-ink': `color-mix(in srgb, ${accent} 22%, #0a0805 86%)`,
    '--p-sans': "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
    '--p-mono': "'Geist Mono', ui-monospace, monospace",
    '--p-serif': `'${serif}', 'Times New Roman', serif`,
  };
}

// ── Example commands + their execution plans ─────────────────────────────────
// Each plan step has fn (function call), detail (human description), t (real
// Mixxx duration). dMs is the demo-loop duration for visualising execution.
const pilotExamples = [
  {
    text: "bass swap into deck 2 over 4 seconds",
    parsed: "swap.bass(deck:1 → deck:2, t:4s)",
    conf: 96,
    affects: "deck 1 · deck 2",
    plan: [
      { fn: "eq.low(deck:1)",  detail: "ramp  0.0 dB  →  −∞",     t: "4.0s", dMs: 780 },
      { fn: "eq.low(deck:2)",  detail: "ramp  −∞  →  0.0 dB",    t: "4.0s", dMs: 780 },
      { fn: "crossfade",       detail: "target  −100  →  +100",  t: "4.0s", dMs: 780 },
    ],
  },
  {
    text: "match deck 2 tempo to deck 1",
    parsed: "tempo.sync(deck:2 → deck:1)",
    conf: 94,
    affects: "deck 2",
    plan: [
      { fn: "tempo.read(deck:1)",  detail: "target  =  116.2 BPM",         t: "—",   dMs: 600 },
      { fn: "tempo.set(deck:2)",   detail: "124.0  →  116.2  ( −6.3 % )",  t: "—",   dMs: 800 },
      { fn: "phase.align(deck:2)", detail: "nudge to nearest downbeat",    t: "~1s", dMs: 700 },
    ],
  },
  {
    text: "kill the bass on deck 1",
    parsed: "eq.low(deck:1) = -inf",
    conf: 99,
    affects: "deck 1",
    plan: [
      { fn: "eq.low(deck:1)", detail: "set  0.0 dB  →  −∞",     t: "—", dMs: 1100 },
    ],
  },
  {
    text: "loop deck 1 for 8 beats",
    parsed: "loop(deck:1, beats:8)",
    conf: 98,
    affects: "deck 1",
    plan: [
      { fn: "loop.set(deck:1)",    detail: "length  8 beats  @ next bar", t: "—", dMs: 850 },
      { fn: "loop.enable(deck:1)", detail: "engage on downbeat",          t: "—", dMs: 850 },
    ],
  },
];

// ── State machine ────────────────────────────────────────────────────────────
// Cycles through examples to demonstrate every state for portfolio video.
function usePilotFlow() {
  const [exampleIdx, setExampleIdx] = useState(0);
  const [phase, setPhase] = useState('typing'); // typing | parsing | ready | running | done
  const [typed, setTyped] = useState(0);        // chars typed (during 'typing')
  const [revealed, setRevealed] = useState(0);  // # plan steps revealed (during 'parsing')
  const [executed, setExecuted] = useState(-1); // index of currently-running step
  const startedAt = useRef(0);
  const [elapsed, setElapsed] = useState(0);    // ms since current 'running' started

  const example = pilotExamples[exampleIdx];
  const totalSteps = example.plan.length;

  // Typing: drive char-by-char
  useEffect(() => {
    if (phase !== 'typing') return;
    if (typed < example.text.length) {
      const t = setTimeout(() => setTyped((c) => c + 1), 38 + Math.random() * 28);
      return () => clearTimeout(t);
    }
    // fully typed → small hold, then parse
    const t = setTimeout(() => { setRevealed(0); setPhase('parsing'); }, 650);
    return () => clearTimeout(t);
  }, [phase, typed, example.text.length]);

  // Parsing: stream plan steps in
  useEffect(() => {
    if (phase !== 'parsing') return;
    if (revealed < totalSteps) {
      const t = setTimeout(() => setRevealed((r) => r + 1), 320);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setPhase('ready'), 260);
    return () => clearTimeout(t);
  }, [phase, revealed, totalSteps]);

  // Ready: pause so viewer can read, then auto-run
  useEffect(() => {
    if (phase !== 'ready') return;
    const t = setTimeout(() => { setExecuted(0); setPhase('running'); startedAt.current = performance.now(); }, 2100);
    return () => clearTimeout(t);
  }, [phase]);

  // Running: drive elapsed for the active step; advance when its dMs is up
  useEffect(() => {
    if (phase !== 'running') return;
    if (executed < 0 || executed >= totalSteps) return;
    startedAt.current = performance.now();
    setElapsed(0);
    let raf;
    const tick = () => {
      const dt = performance.now() - startedAt.current;
      setElapsed(dt);
      if (dt < example.plan[executed].dMs) {
        raf = requestAnimationFrame(tick);
      } else {
        // step done — advance after a short gap
        const gap = setTimeout(() => {
          if (executed + 1 < totalSteps) setExecuted(executed + 1);
          else setPhase('done');
        }, 160);
        raf = -1;
        // store gap so cleanup can clear it
        tick._gap = gap;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => {
      if (raf > 0) cancelAnimationFrame(raf);
      if (tick._gap) clearTimeout(tick._gap);
    };
  }, [phase, executed, totalSteps]);

  // Done: hold, then loop to next example
  useEffect(() => {
    if (phase !== 'done') return;
    const t = setTimeout(() => {
      setExampleIdx((i) => (i + 1) % pilotExamples.length);
      setTyped(0);
      setRevealed(0);
      setExecuted(-1);
      setElapsed(0);
      setPhase('typing');
    }, 2600);
    return () => clearTimeout(t);
  }, [phase]);

  // Live state diffs to display in History pre/post execution
  return { phase, typed, revealed, executed, elapsed, example, exampleIdx };
}

// ── BPM pulse dot ────────────────────────────────────────────────────────────
function BPMPulse({ bpm, color, size = 6 }) {
  const period = 60 / bpm;
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: 99,
        background: color,
        boxShadow: `0 0 12px ${color}`,
        animation: `pilotPulse ${period}s ease-in-out infinite`,
      }}
    />
  );
}

// ── Compact deck card ────────────────────────────────────────────────────────
function PilotDeckCard({ n, track, artist, bpm, keySig, status, progress }) {
  const isPlaying = status === 'playing';
  return (
    <div
      style={{
        flex: 1,
        background: pilotTheme.surface,
        border: `1px solid ${pilotTheme.border}`,
        borderRadius: 12,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              font: `500 9.5px/1 ${pilotTheme.mono}`,
              letterSpacing: '0.18em',
              color: pilotTheme.muted,
              textTransform: 'uppercase',
            }}
          >
            Deck {n}
          </span>
          {isPlaying ? (
            <>
              <BPMPulse bpm={bpm} color="var(--p-live)" size={4} />
              <span style={{ font: `500 9.5px/1 ${pilotTheme.mono}`, color: pilotTheme.live, letterSpacing: '0.14em' }}>
                LIVE
              </span>
            </>
          ) : (
            <span style={{ font: `500 9.5px/1 ${pilotTheme.mono}`, color: pilotTheme.muted, letterSpacing: '0.14em' }}>
              · CUED
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
          <span
            style={{
              font: `400 28px/1 ${pilotTheme.serif}`,
              color: pilotTheme.fg,
              letterSpacing: '-0.02em',
              fontFeatureSettings: '"tnum" 1',
            }}
          >
            {bpm.toFixed(1)}
          </span>
          <span style={{ font: `500 9.5px/1 ${pilotTheme.mono}`, color: pilotTheme.muted, letterSpacing: '0.14em' }}>
            BPM
          </span>
        </div>
      </div>

      <div style={{ minWidth: 0 }}>
        <div
          style={{
            font: `italic 400 15px/1.2 ${pilotTheme.serif}`,
            color: pilotTheme.fg,
            letterSpacing: '-0.005em',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {track}
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            font: `400 11px/1.2 ${pilotTheme.sans}`,
            color: pilotTheme.muted,
            marginTop: 2,
          }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{artist}</span>
          <span style={{ color: pilotTheme.mutedDeep }}>·</span>
          <span style={{ font: `500 10.5px/1.2 ${pilotTheme.mono}` }}>{keySig}</span>
          <span style={{ color: pilotTheme.mutedDeep }}>·</span>
          <span style={{ font: `500 10.5px/1.2 ${pilotTheme.mono}` }}>{progress.t} / {progress.total}</span>
        </div>
      </div>

      <div
        style={{
          marginTop: 2,
          height: 2,
          width: '100%',
          background: 'var(--p-border)',
          borderRadius: 99,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${progress.pct}%`,
            background: pilotTheme.accent,
            opacity: 0.7,
            borderRadius: 99,
          }}
        />
      </div>
    </div>
  );
}

// ── Plan step with execution state ──────────────────────────────────────────
// state: 'hidden' | 'pending' | 'running' | 'done'
function PilotPlanStep({ n, step, last, state, dMs }) {
  const isRunning = state === 'running';
  const isDone = state === 'done';
  const isPending = state === 'pending';

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        position: 'relative',
        opacity: state === 'hidden' ? 0 : 1,
        transform: state === 'hidden' ? 'translateY(4px)' : 'translateY(0)',
        transition: 'opacity .35s, transform .35s',
      }}
    >
      {/* rail + node */}
      <div style={{ position: 'relative', width: 18, flex: '0 0 18px' }}>
        <span
          style={{
            position: 'absolute',
            top: 3,
            left: 4,
            width: 10,
            height: 10,
            borderRadius: 99,
            background: isDone ? pilotTheme.accent : pilotTheme.bg,
            border: `1.5px solid ${isPending ? pilotTheme.mutedDeep : pilotTheme.accent}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background .25s, border-color .25s, box-shadow .25s',
            boxShadow: isRunning ? `0 0 0 4px var(--p-accent-dim)` : 'none',
            animation: isRunning ? 'pilotNodePulse 1.1s ease-in-out infinite' : 'none',
          }}
        >
          {isDone && (
            <svg width="7" height="7" viewBox="0 0 10 10" fill="none">
              <path d="M2 5 L4 7 L8 3" stroke="var(--p-accent-ink)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </span>
        {!last && (
          <span
            style={{
              position: 'absolute',
              top: 14,
              left: 8.25,
              bottom: -8,
              width: 1.5,
              background: isDone ? pilotTheme.accent : pilotTheme.borderStrong,
              opacity: isDone ? 0.55 : 0.6,
              transition: 'background .25s',
            }}
          />
        )}
      </div>

      <div style={{ flex: 1, paddingBottom: last ? 0 : 10, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ font: `500 10px/1 ${pilotTheme.mono}`, color: pilotTheme.mutedDeep }}>
            {String(n).padStart(2, '0')}
          </span>
          <span
            style={{
              font: `500 12px/1.2 ${pilotTheme.mono}`,
              color: isPending ? pilotTheme.fgDim : pilotTheme.fg,
              transition: 'color .25s',
            }}
          >
            {step.fn}
          </span>
          <span style={{ flex: 1 }} />
          {step.t && step.t !== '—' && (
            <span style={{ font: `500 10.5px/1 ${pilotTheme.mono}`, color: pilotTheme.muted }}>
              {step.t}
            </span>
          )}
          {isDone && (
            <span
              style={{
                font: `500 10px/1 ${pilotTheme.mono}`,
                color: pilotTheme.live,
                letterSpacing: '0.08em',
              }}
            >
              ✓ {(step.dMs / 1000).toFixed(1)}s
            </span>
          )}
        </div>
        <div
          style={{
            marginTop: 4,
            marginLeft: 22,
            font: `400 11.5px/1.4 ${pilotTheme.mono}`,
            color: isPending ? pilotTheme.muted : pilotTheme.fgDim,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            transition: 'color .25s',
          }}
        >
          {step.detail}
        </div>
        {/* progress bar — only during running */}
        {isRunning && (
          <div
            style={{
              marginTop: 6,
              marginLeft: 22,
              height: 2,
              width: '100%',
              maxWidth: 320,
              background: 'var(--p-border)',
              borderRadius: 99,
              overflow: 'hidden',
            }}
          >
            <div
              key={`bar-${n}-${dMs}`}
              style={{
                height: '100%',
                width: '100%',
                background: pilotTheme.accent,
                transformOrigin: 'left center',
                animation: `pilotStepBar ${dMs}ms linear forwards`,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ── History item ─────────────────────────────────────────────────────────────
function PilotHistoryItem({ when, prompt, parsed, summary, diff, isNew }) {
  return (
    <div
      style={{
        position: 'relative',
        background: pilotTheme.surface,
        border: `1px solid ${pilotTheme.border}`,
        borderRadius: 12,
        padding: '14px 16px 14px 18px',
        animation: isNew ? 'pilotFadeIn 0.5s ease-out' : 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
        <div
          style={{
            font: `italic 400 16px/1.3 ${pilotTheme.serif}`,
            color: pilotTheme.fg,
            letterSpacing: '-0.005em',
          }}
        >
          &ldquo;{prompt}&rdquo;
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: '0 0 auto', marginLeft: 14 }}>
          <span style={{ font: `400 11px/1 ${pilotTheme.mono}`, color: pilotTheme.mutedDeep }}>{when}</span>
          <button className="pilot-icon-btn" title="Undo">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
              <path d="M3 8 L 6 5 M3 8 L 6 11 M3 8 H 11 A 3 3 0 0 1 11 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '3px 8px',
          background: 'var(--p-border)',
          border: `1px solid ${pilotTheme.border}`,
          borderRadius: 6,
          marginBottom: 8,
          font: `500 11.5px/1 ${pilotTheme.mono}`,
          color: pilotTheme.fgDim,
        }}
      >
        <span style={{ color: pilotTheme.accent }}>→</span>
        <span>{parsed}</span>
      </div>
      <div style={{ font: `400 12.5px/1.4 ${pilotTheme.sans}`, color: pilotTheme.muted }}>
        {summary}
        {diff && (
          <span style={{ marginLeft: 8, font: `500 11.5px/1 ${pilotTheme.mono}`, color: pilotTheme.fgDim }}>
            <span style={{ color: pilotTheme.mutedDeep }}>{diff.from}</span>
            <span style={{ margin: '0 6px', color: pilotTheme.accent }}>→</span>
            <span style={{ color: pilotTheme.fg }}>{diff.to}</span>
          </span>
        )}
      </div>
    </div>
  );
}

// ── Chip ─────────────────────────────────────────────────────────────────────
function PilotChip({ children, kbd }) {
  return (
    <button className="pilot-chip">
      <span>{children}</span>
      {kbd && <span className="pilot-chip-kbd">{kbd}</span>}
    </button>
  );
}

// ── Phase badge (header of plan card) ───────────────────────────────────────
function PilotPhaseBadge({ phase, totalSteps, currentStep, doneCount }) {
  const PHASE_LABELS = {
    typing:  { text: 'Listening',           tone: 'neutral' },
    parsing: { text: 'Streaming plan',      tone: 'accent'  },
    ready:   { text: `Ready · ${totalSteps} step${totalSteps === 1 ? '' : 's'}`, tone: 'ready' },
    running: { text: `Executing · ${currentStep}/${totalSteps}`, tone: 'accent' },
    done:    { text: 'Applied',             tone: 'live'    },
  };
  const cfg = PHASE_LABELS[phase];
  const colors = {
    neutral: { dot: pilotTheme.muted,     fg: pilotTheme.muted },
    accent:  { dot: pilotTheme.accent,    fg: pilotTheme.accent, pulse: true },
    ready:   { dot: pilotTheme.accent,    fg: pilotTheme.accent },
    live:    { dot: pilotTheme.live,      fg: pilotTheme.live },
  };
  const c = colors[cfg.tone];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        font: `500 10px/1 ${pilotTheme.mono}`,
        color: c.fg,
        letterSpacing: '0.18em',
        textTransform: 'uppercase',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 99,
          background: c.dot,
          boxShadow: cfg.tone === 'live' ? `0 0 8px ${c.dot}` : 'none',
          animation: c.pulse ? 'pilotPulse 1.4s ease-in-out infinite' : 'none',
        }}
      />
      <span>{cfg.text}</span>
      {phase === 'done' && (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path d="M2 5.2 L4 7.2 L8 3" stroke={c.fg} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </span>
  );
}

// ── Run button — morphs with phase ──────────────────────────────────────────
function PilotRunButton({ phase, currentStep, totalSteps }) {
  const isReady = phase === 'ready';
  const isRunning = phase === 'running';
  const isDone = phase === 'done';
  const isParsing = phase === 'parsing';
  const isIdle = phase === 'typing';

  let label = 'Run';
  let kbd = '⏎';
  let disabled = false;
  let extraClass = '';

  if (isIdle)    { label = 'Run';        disabled = true; }
  if (isParsing) { label = 'Drafting…';  disabled = true; }
  if (isReady)   { label = 'Run';        extraClass = 'pilot-btn-glow'; }
  if (isRunning) { label = `Running ${currentStep}/${totalSteps}`; disabled = true; kbd = ''; }
  if (isDone)    { label = 'Applied';    disabled = true; kbd = ''; }

  return (
    <button className={`pilot-btn-primary ${extraClass}`} disabled={disabled}>
      <span>{label}</span>
      {kbd && <span className="pilot-btn-kbd">{kbd}</span>}
    </button>
  );
}

// ── Main Pilot ──────────────────────────────────────────────────────────────
function Pilot({ tweaks }) {
  const flow = usePilotFlow();
  const { phase, typed, revealed, executed, elapsed, example, exampleIdx } = flow;
  const totalSteps = example.plan.length;

  // step state per index
  const stepState = (i) => {
    if (phase === 'typing') return 'hidden';
    if (phase === 'parsing') return i < revealed ? 'pending' : 'hidden';
    if (phase === 'ready') return 'pending';
    if (phase === 'running') {
      if (i < executed) return 'done';
      if (i === executed) return 'running';
      return 'pending';
    }
    if (phase === 'done') return 'done';
    return 'hidden';
  };

  const doneCount = phase === 'done'
    ? totalSteps
    : phase === 'running' ? Math.max(0, executed) : 0;

  // 1-indexed "current step in progress" for status counters
  const currentStep = phase === 'running' ? executed + 1 : phase === 'done' ? totalSteps : 0;

  // typed text shown — full text once we leave typing phase
  const typedShown = phase === 'typing' ? example.text.slice(0, typed) : example.text;
  const showCursor = phase === 'typing';

  // sub-label under typed command
  const subLabel = {
    typing: 'awaiting completion…',
    parsing: 'parsing intent · streaming plan',
    ready: 'plan ready · click run or wait',
    running: 'firing into Mixxx · live',
    done: `plan applied · ${totalSteps} action${totalSteps === 1 ? '' : 's'} committed`,
  }[phase];

  // CSS vars for theming
  const cssVars = buildPilotVars(tweaks);

  // Light vs dark surface tweak — top glow is more subtle on light
  const isLight = tweaks.theme === 'light';

  return (
    <div
      style={{
        ...cssVars,
        width: '100%',
        height: '100%',
        background: pilotTheme.bg,
        color: pilotTheme.fg,
        font: `400 14px/1.5 ${pilotTheme.sans}`,
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <style>{`
        @keyframes pilotPulse {
          0%, 100% { opacity: 0.45; transform: scale(0.85); }
          15% { opacity: 1; transform: scale(1.15); }
          40%, 60% { opacity: 0.6; transform: scale(0.95); }
        }
        @keyframes pilotBlink {
          0%, 49% { opacity: 1; }
          50%, 100% { opacity: 0; }
        }
        @keyframes pilotFadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pilotGlow {
          0%, 100% { box-shadow: 0 0 0 1px var(--p-border-strong), 0 0 40px -10px var(--p-accent-dim); }
          50% { box-shadow: 0 0 0 1px var(--p-accent-edge), 0 0 60px -10px var(--p-accent-dim); }
        }
        @keyframes pilotStepBar {
          from { transform: scaleX(0); }
          to { transform: scaleX(1); }
        }
        @keyframes pilotNodePulse {
          0%, 100% { box-shadow: 0 0 0 4px var(--p-accent-dim); }
          50% { box-shadow: 0 0 0 7px var(--p-accent-dim); }
        }
        @keyframes pilotBtnGlow {
          0%, 100% { box-shadow: 0 0 0 0 var(--p-accent-edge); }
          50% { box-shadow: 0 0 0 4px var(--p-accent-edge); }
        }

        /* Chips */
        .pilot-chip {
          all: unset;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 7px 12px;
          background: var(--p-surface);
          border: 1px solid var(--p-border);
          border-radius: 99px;
          font: 400 12.5px/1 var(--p-sans);
          color: var(--p-fg-dim);
          transition: background .15s, color .15s, border-color .15s, transform .15s;
        }
        .pilot-chip:hover {
          background: var(--p-surface-hi);
          color: var(--p-fg);
          border-color: var(--p-border-strong);
        }
        .pilot-chip:active {
          transform: scale(0.97);
          background: var(--p-accent-dim);
          border-color: var(--p-accent-edge);
          color: var(--p-fg);
        }
        .pilot-chip-kbd {
          font: 500 10px/1 var(--p-mono);
          color: var(--p-muted-deep);
          border: 1px solid var(--p-border);
          border-radius: 4px;
          padding: 2px 4px;
        }

        /* Primary button */
        .pilot-btn-primary {
          all: unset;
          cursor: pointer;
          padding: 8px 16px;
          background: var(--p-accent);
          color: var(--p-accent-ink);
          border-radius: 8px;
          font: 500 13px/1 var(--p-sans);
          display: inline-flex;
          align-items: center;
          gap: 8px;
          transition: filter .15s, transform .1s, box-shadow .2s;
        }
        .pilot-btn-primary:hover:not(:disabled) {
          filter: brightness(1.08);
        }
        .pilot-btn-primary:active:not(:disabled) {
          transform: scale(0.97);
          filter: brightness(0.95);
        }
        .pilot-btn-primary:disabled {
          cursor: default;
          opacity: 0.55;
        }
        .pilot-btn-glow {
          animation: pilotBtnGlow 1.6s ease-in-out infinite;
        }
        .pilot-btn-kbd {
          font: 500 10px/1 var(--p-mono);
          opacity: 0.6;
        }

        /* Secondary button */
        .pilot-btn-secondary {
          all: unset;
          cursor: pointer;
          padding: 8px 16px;
          border: 1px solid var(--p-border-strong);
          color: var(--p-fg);
          border-radius: 8px;
          font: 500 13px/1 var(--p-sans);
          display: inline-flex;
          align-items: center;
          gap: 8px;
          transition: background .15s, transform .1s, border-color .15s;
        }
        .pilot-btn-secondary:hover {
          background: var(--p-surface-hi);
          border-color: var(--p-accent-edge);
        }
        .pilot-btn-secondary:active {
          transform: scale(0.97);
        }

        /* Icon button (undo) */
        .pilot-icon-btn {
          all: unset;
          cursor: pointer;
          width: 22px;
          height: 22px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--p-muted);
          border: 1px solid var(--p-border);
          transition: color .15s, background .15s, border-color .15s;
        }
        .pilot-icon-btn:hover {
          color: var(--p-fg);
          background: var(--p-surface-hi);
          border-color: var(--p-border-strong);
        }
        .pilot-icon-btn:active {
          background: var(--p-accent-dim);
          color: var(--p-accent);
        }

        /* Header deploy */
        .pilot-deploy {
          all: unset;
          cursor: pointer;
          padding: 7px 14px;
          border: 1px solid var(--p-border-strong);
          border-radius: 8px;
          font: 500 12px/1 var(--p-sans);
          color: var(--p-fg);
          transition: background .15s, border-color .15s;
        }
        .pilot-deploy:hover {
          background: var(--p-surface-hi);
          border-color: var(--p-accent-edge);
        }
      `}</style>

      {/* ambient glow */}
      <div
        style={{
          position: 'absolute',
          top: -180,
          left: '50%',
          transform: 'translateX(-50%)',
          width: 700,
          height: 360,
          background: `radial-gradient(ellipse, var(--p-accent-dim), transparent 70%)`,
          filter: 'blur(40px)',
          pointerEvents: 'none',
          opacity: isLight ? 0.65 : 1,
        }}
      />

      {/* ── Top bar ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '18px 28px',
          borderBottom: `1px solid ${pilotTheme.border}`,
          position: 'relative',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <rect x="3" y="3" width="3" height="16" rx="1" fill="var(--p-fg)" />
            <rect x="9.5" y="6" width="3" height="13" rx="1" fill="var(--p-accent)" />
            <rect x="16" y="3" width="3" height="16" rx="1" fill="var(--p-fg)" opacity="0.4" />
          </svg>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ font: `500 15px/1 ${pilotTheme.sans}`, letterSpacing: '-0.01em' }}>DeckPilot</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              font: `500 11px/1 ${pilotTheme.mono}`,
              color: pilotTheme.muted,
              letterSpacing: '0.06em',
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 99,
                background: pilotTheme.live,
                boxShadow: `0 0 8px var(--p-live)`,
                animation: 'pilotPulse 2s ease-in-out infinite',
              }}
            />
            <span>connected</span>
            <span style={{ color: pilotTheme.mutedDeep }}>·</span>
            <span>32ms</span>
          </div>
          <button className="pilot-deploy">Deploy</button>
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div style={{ flex: 1, padding: '32px 28px 24px', overflow: 'auto', position: 'relative' }}>

        {/* Hero command card */}
        <div
          style={{
            marginBottom: 28,
            background: pilotTheme.surface,
            border: `1px solid ${pilotTheme.borderStrong}`,
            borderRadius: 18,
            padding: '20px 24px 20px',
            animation: 'pilotGlow 4s ease-in-out infinite',
          }}
        >
          {/* Top row: label + phase badge */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 14,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                font: `500 10px/1 ${pilotTheme.mono}`,
                color: pilotTheme.muted,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              <span style={{ color: pilotTheme.accent }}>✱</span>
              <span>Command</span>
            </div>
            <PilotPhaseBadge phase={phase} totalSteps={totalSteps} currentStep={currentStep} doneCount={doneCount} />
          </div>

          {/* Typed command */}
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 8,
              font: `italic 400 28px/1.2 ${pilotTheme.serif}`,
              color: pilotTheme.fg,
              minHeight: 36,
              letterSpacing: '-0.01em',
            }}
          >
            <span style={{ color: pilotTheme.accent, fontStyle: 'normal' }}>›</span>
            <span>
              {typedShown}
              {showCursor && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 2,
                    height: 24,
                    background: pilotTheme.accent,
                    marginLeft: 2,
                    transform: 'translateY(4px)',
                    animation: 'pilotBlink 1.1s steps(2) infinite',
                  }}
                />
              )}
            </span>
          </div>

          {/* Parsed action row — only after typing complete */}
          <div
            style={{
              marginTop: 18,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              opacity: phase === 'typing' ? 0.3 : 1,
              transition: 'opacity .3s',
            }}
          >
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 10px',
                background: pilotTheme.accentDim,
                border: `1px solid ${pilotTheme.accentEdge}`,
                borderRadius: 8,
                font: `500 12px/1 ${pilotTheme.mono}`,
                color: pilotTheme.fg,
              }}
            >
              <span style={{ color: pilotTheme.accent }}>fn</span>
              <span>{example.parsed}</span>
            </div>
            <span style={{ font: `400 11.5px/1 ${pilotTheme.mono}`, color: pilotTheme.muted }}>
              {example.conf}% confident
            </span>
            <span style={{ flex: 1 }} />
            <PilotRunButton phase={phase} currentStep={currentStep} totalSteps={totalSteps} />
            <button className="pilot-btn-secondary">
              <span>Queue</span>
              <span style={{ font: `500 10px/1 ${pilotTheme.mono}`, color: pilotTheme.muted }}>⌘⏎</span>
            </button>
          </div>

          {/* Plan */}
          <div
            style={{
              marginTop: 18,
              paddingTop: 16,
              borderTop: `1px dashed ${pilotTheme.border}`,
              opacity: phase === 'typing' ? 0.25 : 1,
              transition: 'opacity .3s',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 14,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  font: `500 10px/1 ${pilotTheme.mono}`,
                  color: pilotTheme.muted,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                }}
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                  <circle cx="5" cy="5" r="4" stroke="var(--p-accent)" strokeWidth="1.2" fill="none" />
                  <circle cx="5" cy="5" r="1.5" fill="var(--p-accent)" />
                </svg>
                <span>Plan · {totalSteps} step{totalSteps === 1 ? '' : 's'}</span>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {example.plan.map((step, i) => (
                <PilotPlanStep
                  key={`${exampleIdx}-${i}`}
                  n={i + 1}
                  step={step}
                  last={i === totalSteps - 1}
                  state={stepState(i)}
                  dMs={step.dMs}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Try chips */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              font: `500 10px/1 ${pilotTheme.mono}`,
              color: pilotTheme.muted,
              letterSpacing: '0.18em',
              marginBottom: 12,
              textTransform: 'uppercase',
            }}
          >
            Try
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <PilotChip kbd="1">kill the bass on deck 1</PilotChip>
            <PilotChip kbd="2">bass swap into deck 2 over 4s</PilotChip>
            <PilotChip kbd="3">match tempo</PilotChip>
          </div>
        </div>

        {/* Live state */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              marginBottom: 14,
            }}
          >
            <div
              style={{
                font: `500 10px/1 ${pilotTheme.mono}`,
                color: pilotTheme.muted,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              Live state
            </div>
            <div style={{ font: `400 11.5px/1 ${pilotTheme.mono}`, color: pilotTheme.mutedDeep }}>
              crossfade · centre   ∆ −5.5 bpm
            </div>
          </div>
          <div style={{ display: 'flex', gap: 14 }}>
            <PilotDeckCard
              n={1}
              track="La Danse"
              artist="Berlioz"
              bpm={116.2}
              keySig="Am"
              status="paused"
              progress={{ t: '1:42', total: '4:18', pct: 39 }}
            />
            <PilotDeckCard
              n={2}
              track="Around The World"
              artist="Daft Punk"
              bpm={121.7}
              keySig="Dm"
              status="paused"
              progress={{ t: '0:00', total: '7:09', pct: 0 }}
            />
          </div>
        </div>

        {/* Queue — above history */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              marginBottom: 14,
            }}
          >
            <div
              style={{
                font: `500 10px/1 ${pilotTheme.mono}`,
                color: pilotTheme.muted,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              Queue · 3 pending
            </div>
            <div style={{ font: `400 11.5px/1 ${pilotTheme.mono}`, color: pilotTheme.accent, cursor: 'pointer' }}>
              run all ▸
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {[
              { n: 1, text: 'bass swap into deck 2 over 4 seconds', parsed: 'swap.bass(deck:2, t:4s)' },
              { n: 2, text: 'loop deck 1 for 8 beats',              parsed: 'loop(deck:1, beats:8)' },
              { n: 3, text: 'ease crossfader to center over 8 beats', parsed: 'crossfade(target:0, beats:8)' },
            ].map((q) => (
              <div
                key={q.n}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  padding: '10px 14px',
                  background: pilotTheme.surface,
                  border: `1px solid ${pilotTheme.border}`,
                  borderRadius: 10,
                }}
              >
                <span style={{ font: `500 10px/1 ${pilotTheme.mono}`, color: pilotTheme.mutedDeep, width: 14 }}>{q.n}</span>
                <span style={{ font: `italic 400 14.5px/1.2 ${pilotTheme.serif}`, color: pilotTheme.fg, flex: 1 }}>
                  {q.text}
                </span>
                <span style={{ font: `500 11px/1 ${pilotTheme.mono}`, color: pilotTheme.muted }}>{q.parsed}</span>
              </div>
            ))}
          </div>
        </div>

        {/* History */}
        <div style={{ marginBottom: 24 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              marginBottom: 14,
            }}
          >
            <div
              style={{
                font: `500 10px/1 ${pilotTheme.mono}`,
                color: pilotTheme.muted,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              History · click ↶ to undo
            </div>
            <div style={{ font: `400 11.5px/1 ${pilotTheme.mono}`, color: pilotTheme.mutedDeep }}>
              4 commands · clear
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <PilotHistoryItem
              when="2s ago"
              prompt="kill the bass on deck 1"
              parsed="eq.low(deck:1) = -inf"
              summary="Deck 1 low-band cut."
              diff={{ from: '0.0 dB', to: '−∞' }}
              isNew
            />
            <PilotHistoryItem
              when="14s ago"
              prompt="match deck 2 tempo to deck 1"
              parsed="tempo.sync(deck:2 → deck:1)"
              summary="Deck 2 tempo nudged to match Deck 1."
              diff={{ from: '124.0 BPM', to: '116.2 BPM' }}
            />
            <PilotHistoryItem
              when="48s ago"
              prompt="play deck 1"
              parsed="transport.play(deck:1)"
              summary="Started playback on Deck 1 at cue 0:00."
            />
            <PilotHistoryItem
              when="2m ago"
              prompt="load berlioz la danse on deck 1"
              parsed="library.load(deck:1, q:'berlioz la danse')"
              summary="Loaded 1 of 3 matches — Berlioz, La Danse · 4:18."
            />
          </div>
        </div>
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '14px 28px',
          borderTop: `1px solid ${pilotTheme.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          font: `400 11px/1 ${pilotTheme.mono}`,
          color: pilotTheme.mutedDeep,
        }}
      >
        <span>DeckPilot · v0.1.0</span>
        <div style={{ display: 'flex', gap: 18 }}>
          <span>Clear history</span>
          <span style={{ color: pilotTheme.muted }}>Reset Mixxx</span>
          <span>⌘ K · search</span>
        </div>
      </div>
    </div>
  );
}

window.Pilot = Pilot;
