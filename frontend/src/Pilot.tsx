/**
 * Pilot — the main app shell. Composes everything.
 *
 * Layout (top to bottom):
 *
 *   Topbar: logo + connected status pulse + Deploy
 *   Scrollable content:
 *     • CommandCard (hero — typing → parsing → ready → running → done)
 *     • Try chips (preset commands the user can fire with one click)
 *     • Live state (two DeckCards side by side)
 *     • Queue (pending commands waiting to be run)
 *     • History (completed commands with undo)
 *   Footer: version + history-clear + reset Mixxx + cmd-K search
 *
 * For Phase 2 the queue and history are static mocks pulled from the design.
 * Phase 4 will wire them to real state coming from the backend.
 *
 * The phase machine is driven by usePilotFlow (currently the auto-cycling
 * demo cycle ported from the design; Phase 4 rewrites it to be real).
 */

import { CommandCard } from './components/CommandCard';
import { DeckCard } from './components/DeckCard';
import { HistoryItem } from './components/HistoryItem';
import { Chip } from './components/Chip';
import { usePilotFlow } from './hooks/usePilotFlow';

// Hardcoded queue + history for Phase 2 visual parity. Replaced in Phase 4.
const MOCK_QUEUE = [
  { n: 1, text: 'bass swap into deck 2 over 4 seconds', parsed: 'swap.bass(deck:2, t:4s)' },
  { n: 2, text: 'loop deck 1 for 8 beats', parsed: 'loop(deck:1, beats:8)' },
  { n: 3, text: 'ease crossfader to center over 8 beats', parsed: 'crossfade(target:0, beats:8)' },
];

const MOCK_HISTORY = [
  {
    when: '2s ago',
    prompt: 'kill the bass on deck 1',
    parsed: 'eq.low(deck:1) = -inf',
    summary: 'Deck 1 low-band cut.',
    diff: { from: '0.0 dB', to: '−∞' },
    isNew: true,
  },
  {
    when: '14s ago',
    prompt: 'match deck 2 tempo to deck 1',
    parsed: 'tempo.sync(deck:2 → deck:1)',
    summary: 'Deck 2 tempo nudged to match Deck 1.',
    diff: { from: '124.0 BPM', to: '116.2 BPM' },
  },
  {
    when: '48s ago',
    prompt: 'play deck 1',
    parsed: 'transport.play(deck:1)',
    summary: 'Started playback on Deck 1 at cue 0:00.',
  },
  {
    when: '2m ago',
    prompt: 'load berlioz la danse on deck 1',
    parsed: "library.load(deck:1, q:'berlioz la danse')",
    summary: 'Loaded 1 of 3 matches — Berlioz, La Danse · 4:18.',
  },
];

export function Pilot() {
  const flow = usePilotFlow();
  const { phase, typed, example, exampleIdx, revealed, executed } = flow;

  // Once we leave the typing phase, show the full text immediately.
  const typedShown = phase === 'typing' ? example.text.slice(0, typed) : example.text;
  const showCursor = phase === 'typing';

  return (
    <div
      style={{
        width: '100%',
        minHeight: '100vh',
        background: 'var(--p-bg)',
        color: 'var(--p-fg)',
        font: '400 14px/1.5 var(--p-sans)',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Ambient accent glow at the top */}
      <div
        style={{
          position: 'absolute',
          top: -180,
          left: '50%',
          transform: 'translateX(-50%)',
          width: 700,
          height: 360,
          background: 'radial-gradient(ellipse, var(--p-accent-dim), transparent 70%)',
          filter: 'blur(40px)',
          pointerEvents: 'none',
        }}
      />

      {/* Topbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '18px 28px',
          borderBottom: '1px solid var(--p-border)',
          position: 'relative',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <rect x="3" y="3" width="3" height="16" rx="1" fill="var(--p-fg)" />
            <rect x="9.5" y="6" width="3" height="13" rx="1" fill="var(--p-accent)" />
            <rect x="16" y="3" width="3" height="16" rx="1" fill="var(--p-fg)" opacity="0.4" />
          </svg>
          <span style={{ font: '500 15px/1 var(--p-sans)', letterSpacing: '-0.01em' }}>DeckPilot</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              font: '500 11px/1 var(--p-mono)',
              color: 'var(--p-muted)',
              letterSpacing: '0.06em',
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 99,
                background: 'var(--p-live)',
                boxShadow: '0 0 8px var(--p-live)',
                animation: 'pilotPulse 2s ease-in-out infinite',
              }}
            />
            <span>connected</span>
            <span style={{ color: 'var(--p-muted-deep)' }}>·</span>
            <span>32ms</span>
          </div>
          <button className="pilot-deploy" type="button">Deploy</button>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, padding: '32px 28px 24px', overflow: 'auto', position: 'relative' }}>
        <CommandCard
          phase={phase}
          typedText={typedShown}
          showCursor={showCursor}
          parsed={example.parsed}
          conf={example.conf}
          plan={example.plan}
          revealed={revealed}
          executed={executed}
          exampleIdx={exampleIdx}
        />

        {/* Try chips */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              font: '500 10px/1 var(--p-mono)',
              color: 'var(--p-muted)',
              letterSpacing: '0.18em',
              marginBottom: 12,
              textTransform: 'uppercase',
            }}
          >
            Try
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Chip kbd="1">kill the bass on deck 1</Chip>
            <Chip kbd="2">bass swap into deck 2 over 4s</Chip>
            <Chip kbd="3">match tempo</Chip>
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
                font: '500 10px/1 var(--p-mono)',
                color: 'var(--p-muted)',
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              Live state
            </div>
            <div style={{ font: '400 11.5px/1 var(--p-mono)', color: 'var(--p-muted-deep)' }}>
              crossfade · centre   ∆ −5.5 bpm
            </div>
          </div>
          <div style={{ display: 'flex', gap: 14 }}>
            <DeckCard
              n={1}
              track="La Danse"
              artist="Berlioz"
              bpm={116.2}
              keySig="Am"
              status="paused"
              progress={{ t: '1:42', total: '4:18', pct: 39 }}
            />
            <DeckCard
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

        {/* Queue */}
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
                font: '500 10px/1 var(--p-mono)',
                color: 'var(--p-muted)',
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              Queue · {MOCK_QUEUE.length} pending
            </div>
            <div style={{ font: '400 11.5px/1 var(--p-mono)', color: 'var(--p-accent)', cursor: 'pointer' }}>
              run all ▸
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {MOCK_QUEUE.map((q) => (
              <div
                key={q.n}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  padding: '10px 14px',
                  background: 'var(--p-surface)',
                  border: '1px solid var(--p-border)',
                  borderRadius: 10,
                }}
              >
                <span style={{ font: '500 10px/1 var(--p-mono)', color: 'var(--p-muted-deep)', width: 14 }}>
                  {q.n}
                </span>
                <span style={{ font: 'italic 400 14.5px/1.2 var(--p-serif)', color: 'var(--p-fg)', flex: 1 }}>
                  {q.text}
                </span>
                <span style={{ font: '500 11px/1 var(--p-mono)', color: 'var(--p-muted)' }}>{q.parsed}</span>
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
                font: '500 10px/1 var(--p-mono)',
                color: 'var(--p-muted)',
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
              }}
            >
              History · click ↶ to undo
            </div>
            <div style={{ font: '400 11.5px/1 var(--p-mono)', color: 'var(--p-muted-deep)' }}>
              {MOCK_HISTORY.length} commands · clear
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_HISTORY.map((h, i) => (
              <HistoryItem key={i} {...h} />
            ))}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '14px 28px',
          borderTop: '1px solid var(--p-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          font: '400 11px/1 var(--p-mono)',
          color: 'var(--p-muted-deep)',
        }}
      >
        <span>DeckPilot · v0.1.0</span>
        <div style={{ display: 'flex', gap: 18 }}>
          <span>Clear history</span>
          <span style={{ color: 'var(--p-muted)' }}>Reset Mixxx</span>
          <span>⌘ K · search</span>
        </div>
      </div>
    </div>
  );
}
