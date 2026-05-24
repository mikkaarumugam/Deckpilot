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

import { useEffect, useState } from 'react';

import { CommandCard } from './components/CommandCard';
import { DeckCard } from './components/DeckCard';
import { HistoryItem } from './components/HistoryItem';
import { Chip } from './components/Chip';
import { TweaksPanel } from './components/TweaksPanel';
import { useAgentState } from './hooks/useAgentState';
import { useBpmSync } from './hooks/useBpmSync';
import { useDeckState } from './hooks/useDeckState';
import { usePilotFlow } from './hooks/usePilotFlow';
import { useTweaks } from './hooks/useTweaks';

const PRESET_CHIPS = [
  { label: 'play deck 1', kbd: '1' },
  { label: 'kill the bass on deck 1', kbd: '2' },
  { label: 'bass swap into deck 2 over 4 seconds', kbd: '3' },
] as const;

export function Pilot() {
  const tweaksApi = useTweaks();
  // Pass the user-selected model into the flow hook so LLM parses
  // route to whatever they picked in the Tweaks panel (haiku / sonnet
  // / opus). The hook reads `model` on every render — flipping the
  // dropdown applies on the next parse, no reload needed.
  const flow = usePilotFlow({ model: tweaksApi.tweaks.model });
  const stateSnapshot = useDeckState();
  const agentState = useAgentState();
  useBpmSync(stateSnapshot);
  const [historyCleared, setHistoryCleared] = useState(false);
  const [tweaksOpen, setTweaksOpen] = useState(false);

  // Push agent-active into the flow hook so its queue effect knows
  // when to defer the next queued command. The hook can't pull this
  // itself without dragging in useAgentState (and the polling lifecycle
  // gets noisy across re-renders); cleaner to wire it in here.
  useEffect(() => {
    flow.setAgentActive(agentState?.active ?? false);
  }, [agentState?.active, flow]);

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
          <span style={{ font: '500 18px/1 var(--p-sans)', letterSpacing: '-0.01em' }}>DeckPilot</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {(() => {
            // Three states for the connection indicator:
            //   no stateSnapshot      → backend itself unreachable → "connecting…"
            //   snapshot + !alive     → backend up, Mixxx down or
            //                            controller disabled → "no Mixxx"
            //   snapshot + alive      → both alive → "connected"
            // mixxx_alive is server-computed from MixxxFeedback's
            // heartbeat — see deckpilot/adapters/midi_feedback.py.
            const status: 'connecting' | 'no-mixxx' | 'connected' = !stateSnapshot
              ? 'connecting'
              : stateSnapshot.mixxx_alive
                ? 'connected'
                : 'no-mixxx';
            const label =
              status === 'connecting' ? 'connecting…'
              : status === 'connected' ? 'connected'
              : 'not connected';
            const dotColor =
              status === 'connected' ? 'var(--p-live)'
              : status === 'no-mixxx' ? '#f59e0b'  // amber: backend ok, adapter not getting feedback
              : 'var(--p-muted)';
            const glow = status === 'connected' ? `0 0 8px ${dotColor}` : 'none';
            const animation = status === 'connected'
              ? 'pilotPulse var(--p-beat-4-ms) ease-in-out infinite'
              : 'none';
            return (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 7,
                  font: '500 12px/1 var(--p-mono)',
                  color: status === 'connected' ? 'var(--p-muted)' : 'var(--p-muted-deep)',
                  letterSpacing: '0.06em',
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 99,
                    background: dotColor,
                    boxShadow: glow,
                    animation,
                  }}
                />
                <span>{label}</span>
              </div>
            );
          })()}
        </div>
      </div>

      {/* Scrollable content. Inner div clamps width + centers — keeps
          the app from sprawling on wide screens (boiler-room intimate
          framing instead of dashboard sprawl). */}
      <div style={{ flex: 1, padding: '32px 28px 24px', overflow: 'auto', position: 'relative' }}>
       <div style={{ maxWidth: 880, margin: '0 auto' }}>
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
          onQueue={flow.onQueue}
          agentState={agentState}
        />

        {/* Try chips */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              font: '500 11px/1 var(--p-mono)',
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
                font: '500 11px/1 var(--p-mono)',
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
                trackId={d.track?.id}
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

        {/* Queue — pending commands waiting for the current run to
            finish. The hook auto-pops the front when the system goes
            idle. Click × to cancel an entry without firing it. */}
        {flow.queue.length > 0 && (
          <div style={{ marginBottom: 28 }}>
            <div
              style={{
                font: '500 11px/1 var(--p-mono)',
                color: 'var(--p-muted)',
                letterSpacing: '0.18em',
                marginBottom: 12,
                textTransform: 'uppercase',
              }}
            >
              Queue · {flow.queue.length} pending
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {flow.queue.map((q, i) => (
                <div
                  key={q.id}
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
                  <span style={{ font: '500 11px/1 var(--p-mono)', color: 'var(--p-muted-deep)', width: 14 }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span
                    style={{
                      font: '500 13.5px/1.2 var(--p-mono)',
                      color: 'var(--p-fg)',
                      flex: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    › {q.prompt}
                  </span>
                  <span style={{ font: '500 11px/1 var(--p-mono)', color: 'var(--p-muted)' }}>{q.parsed}</span>
                  <button
                    type="button"
                    onClick={() => flow.onCancelQueueEntry(q.id)}
                    title="Remove from queue"
                    style={{
                      all: 'unset',
                      cursor: 'pointer',
                      padding: '4px 8px',
                      font: '500 14px/1 var(--p-mono)',
                      color: 'var(--p-muted)',
                      borderRadius: 4,
                    }}
                  >
                    ×
                  </button>
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
                font: '500 11px/1 var(--p-mono)',
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
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '14px 28px',
          borderTop: '1px solid var(--p-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          font: '400 12.5px/1 var(--p-mono)',
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
          <span
            style={{
              cursor: 'pointer',
              color: tweaksOpen ? 'var(--p-accent)' : 'var(--p-muted)',
            }}
            onClick={() => setTweaksOpen((o) => !o)}
          >
            ✱ Tweaks
          </span>
        </div>
      </div>

      {tweaksOpen && (
        <TweaksPanel api={tweaksApi} onClose={() => setTweaksOpen(false)} />
      )}
    </div>
  );
}
