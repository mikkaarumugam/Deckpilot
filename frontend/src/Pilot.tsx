/**
 * Pilot — main app shell. Phase 4 version (real backend-driven).
 *
 * Replaces the auto-cycling demo from Phase 2 with:
 *   - User-driven typing via the new usePilotFlow (debounced parse,
 *     real run, real history).
 *   - Live deck state from useDeckState (polls GET /state at 250ms).
 *   - Real history sourced from the hook.
 *   - Suggestion card rendered inline in CommandCard when /parse
 *     returns a LoadTrack suggestion.
 *
 * Try chips set the input text directly — same flow as if the user
 * typed it.
 *
 * Queue stays mocked for now (D-018 day-1 non-goal). The Reset button
 * in the footer is wired up; clear history is local-state only.
 */

import { useState } from 'react';

import { CommandCard } from './components/CommandCard';
import { DeckCard } from './components/DeckCard';
import { HistoryItem } from './components/HistoryItem';
import { Chip } from './components/Chip';
import { useDeckState } from './hooks/useDeckState';
import { usePilotFlow } from './hooks/usePilotFlow';

const PRESET_CHIPS = [
  { label: 'play deck 1', kbd: '1' },
  { label: 'kill the bass on deck 1', kbd: '2' },
  { label: 'bass swap into deck 2 over 4 seconds', kbd: '3' },
] as const;

// Queue stays mocked for day-1 (D-018 non-goal). Removed when Phase 4+ adds
// real queue execution.
const MOCK_QUEUE: { n: number; text: string; parsed: string }[] = [];

export function Pilot() {
  const flow = usePilotFlow();
  const stateSnapshot = useDeckState();
  const [historyCleared, setHistoryCleared] = useState(false);

  const decks = stateSnapshot?.decks ?? [
    { n: 1 as const, status: 'cued' as const, bpm: 0, track: null, progress: { t: '—', total: '—', pct: 0 } },
    { n: 2 as const, status: 'cued' as const, bpm: 0, track: null, progress: { t: '—', total: '—', pct: 0 } },
  ];

  const bpmDeltaLabel =
    typeof stateSnapshot?.bpm_delta === 'number'
      ? `${stateSnapshot.bpm_delta >= 0 ? '+' : ''}${stateSnapshot.bpm_delta.toFixed(1)} BPM`
      : '—';

  const history = historyCleared ? [] : flow.history;

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
      {/* Ambient accent glow */}
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
              color: stateSnapshot ? 'var(--p-muted)' : 'var(--p-muted-deep)',
              letterSpacing: '0.06em',
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 99,
                background: stateSnapshot ? 'var(--p-live)' : 'var(--p-muted)',
                boxShadow: stateSnapshot ? '0 0 8px var(--p-live)' : 'none',
                animation: stateSnapshot ? 'pilotPulse 2s ease-in-out infinite' : 'none',
              }}
            />
            <span>{stateSnapshot ? 'connected' : 'connecting…'}</span>
          </div>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, padding: '32px 28px 24px', overflow: 'auto', position: 'relative' }}>
        <CommandCard
          phase={flow.phase}
          text={flow.text}
          onTextChange={flow.setText}
          parseResult={flow.parseResult}
          executed={flow.executed}
          error={flow.error}
          suggestion={flow.suggestion}
          regexMissed={flow.regexMissed}
          autoLoadPending={flow.autoLoadPending}
          autoLoadCountdownMs={flow.autoLoadCountdownMs}
          onCancelAutoLoad={flow.onCancelAutoLoad}
          onSubmit={flow.onSubmit}
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
            {PRESET_CHIPS.map((c) => (
              <Chip key={c.kbd} kbd={c.kbd} onClick={() => flow.setText(c.label)}>
                {c.label}
              </Chip>
            ))}
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
              ∆ {bpmDeltaLabel}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 14 }}>
            {decks.map((d) => (
              <DeckCard
                key={d.n}
                n={d.n}
                track={d.track?.title ?? '(no track)'}
                artist={d.track?.artist ?? '—'}
                bpm={d.bpm > 0 ? d.bpm : 0}
                keySig={d.track?.key || '—'}
                status={d.status}
                progress={d.progress}
              />
            ))}
          </div>
        </div>

        {/* Queue — mocked for day-1 */}
        {MOCK_QUEUE.length > 0 && (
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
              Queue · {MOCK_QUEUE.length} pending
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
                  <span
                    style={{
                      font: 'italic 400 14.5px/1.2 var(--p-serif)',
                      color: 'var(--p-fg)',
                      flex: 1,
                    }}
                  >
                    {q.text}
                  </span>
                  <span style={{ font: '500 11px/1 var(--p-mono)', color: 'var(--p-muted)' }}>{q.parsed}</span>
                </div>
              ))}
            </div>
          </div>
        )}

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
              {history.length} command{history.length === 1 ? '' : 's'} ·{' '}
              <span
                onClick={() => setHistoryCleared(true)}
                style={{ cursor: 'pointer', color: 'var(--p-muted)' }}
              >
                clear
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {history.length === 0 ? (
              <div
                style={{
                  padding: '14px 16px',
                  font: '400 12.5px/1.4 var(--p-sans)',
                  color: 'var(--p-muted-deep)',
                  background: 'var(--p-surface)',
                  border: '1px dashed var(--p-border)',
                  borderRadius: 12,
                  textAlign: 'center',
                }}
              >
                Run a command to see it here.
              </div>
            ) : (
              history.map((h, i) => <HistoryItem key={`${h.when}-${i}`} {...h} />)
            )}
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
        <span>DeckPilot · v0.2.0</span>
        <div style={{ display: 'flex', gap: 18 }}>
          <span style={{ cursor: 'pointer' }} onClick={() => setHistoryCleared(true)}>
            Clear history
          </span>
          <span style={{ cursor: 'pointer', color: 'var(--p-muted)' }} onClick={flow.onReset}>
            Reset Mixxx
          </span>
        </div>
      </div>
    </div>
  );
}
