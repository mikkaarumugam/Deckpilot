/**
 * AgentQueue — renders the active AgentSchedule's pending steps as
 * a queue, with status indicators (done / running / pending) and a
 * countdown hint for triggers that watch deck position.
 *
 * Mounted from Pilot.tsx. Hides itself when no schedule is active
 * (the backend returns active=false in that case). Cancel button
 * fires POST /agent/cancel and the panel collapses on the next poll.
 *
 * Design language matches the rest of the app — small uppercase
 * mono section header, then row-per-step with the accent pill for
 * the currently-running step. See D-021.
 */

import { useState } from 'react';

import { api, type AgentStateResponse, type AgentStepStatus, type DeckStatePayload } from '../api/client';

interface AgentQueueProps {
  state: AgentStateResponse;
  decks: DeckStatePayload[];
}

export function AgentQueue({ state, decks }: AgentQueueProps) {
  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    setCancelling(true);
    try {
      await api.agentCancel();
    } catch {
      // best-effort — next poll will reveal current state
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div style={{ marginBottom: 28 }}>
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
            font: '500 11px/1 var(--p-mono)',
            color: 'var(--p-accent)',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
          }}
        >
          <span>🤖 Agent</span>
          <span style={{ color: 'var(--p-muted)' }}>
            · {state.steps.length} step{state.steps.length === 1 ? '' : 's'}
          </span>
        </div>
        <span
          onClick={handleCancel}
          style={{
            cursor: cancelling ? 'wait' : 'pointer',
            font: '500 11px/1 var(--p-mono)',
            color: 'var(--p-muted)',
            letterSpacing: '0.06em',
          }}
        >
          {cancelling ? 'cancelling…' : 'cancel'}
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {state.steps.map((step, i) => (
          <AgentRow
            key={i}
            n={i + 1}
            step={step}
            decks={decks}
            last={i === state.steps.length - 1}
          />
        ))}
      </div>
    </div>
  );
}

// ── Per-row rendering ────────────────────────────────────────────────────
//
// Mirrors the visual language of components/PlanStep (rail + node + body
// with monospace fn signature) so the agent queue feels like an extension
// of the plan timeline, not a different widget. The detail line carries
// the trigger description — that's the agent's value-add over a plain
// plan, so it gets prime real estate beneath the fn signature.

function AgentRow({
  n,
  step,
  decks,
  last,
}: {
  n: number;
  step: AgentStepStatus;
  decks: DeckStatePayload[];
  last: boolean;
}) {
  const isRunning = step.status === 'running';
  const isDone = step.status === 'done';
  const isPending = step.status === 'pending';

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        position: 'relative',
        opacity: isDone ? 0.55 : 1,
        transition: 'opacity 0.3s',
      }}
    >
      {/* Rail + node — same geometry as PlanStep */}
      <div style={{ position: 'relative', width: 18, flex: '0 0 18px' }}>
        <span
          style={{
            position: 'absolute',
            top: 3,
            left: 4,
            width: 10,
            height: 10,
            borderRadius: 99,
            background: isDone ? 'var(--p-accent)' : 'var(--p-bg)',
            border: `1.5px solid ${isPending ? 'var(--p-muted-deep)' : 'var(--p-accent)'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background 0.25s, border-color 0.25s, box-shadow 0.25s',
            boxShadow: isRunning ? '0 0 0 4px var(--p-accent-dim)' : 'none',
            animation: isRunning ? 'pilotNodePulse var(--p-beat-2-ms) ease-in-out infinite' : 'none',
          }}
        >
          {isDone && (
            <svg width="7" height="7" viewBox="0 0 10 10" fill="none">
              <path
                d="M2 5 L4 7 L8 3"
                stroke="var(--p-accent-ink)"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
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
              background: isDone ? 'var(--p-accent)' : 'var(--p-border-strong)',
              opacity: isDone ? 0.55 : 0.6,
              transition: 'background 0.25s',
            }}
          />
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, paddingBottom: last ? 0 : 12, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ font: '500 11.5px/1 var(--p-mono)', color: 'var(--p-muted-deep)' }}>
            {String(n).padStart(2, '0')}
          </span>
          <span
            style={{
              font: '500 14px/1.2 var(--p-mono)',
              color: isPending ? 'var(--p-fg-dim)' : 'var(--p-fg)',
              transition: 'color 0.25s',
            }}
          >
            {step.signature || step.label}
          </span>
          <span style={{ flex: 1 }} />
          <TriggerHint step={step} decks={decks} />
        </div>
        <div
          style={{
            marginTop: 4,
            marginLeft: 22,
            font: 'italic 400 13px/1.4 var(--p-serif)',
            color: isPending ? 'var(--p-muted)' : 'var(--p-fg-dim)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            transition: 'color 0.25s',
          }}
        >
          {step.label}
        </div>
      </div>
    </div>
  );
}

function TriggerHint({
  step,
  decks,
}: {
  step: AgentStepStatus;
  decks: DeckStatePayload[];
}) {
  if (step.status === 'done') return null;

  if (step.trigger_kind === 'immediate') {
    return (
      <span style={{ font: '500 10.5px/1 var(--p-mono)', color: 'var(--p-muted)' }}>
        immediate
      </span>
    );
  }

  // after_beats trigger (D-023) — backend computes `remaining_count` from
  // the per-step baseline so we don't have to track it client-side. If the
  // step hasn't become current yet, remaining_count is null and we render
  // the requested total. Live tick comes from `decks[N].beat_count` polled
  // alongside the rest of the deck state — keeps the dot "alive."
  if (step.trigger_kind === 'after_beats') {
    const remaining = step.remaining_count ?? step.trigger_count ?? 0;
    return (
      <span
        style={{
          font: '500 10.5px/1 var(--p-mono)',
          color: 'var(--p-accent)',
          letterSpacing: '0.04em',
        }}
      >
        deck {step.trigger_deck} → {remaining} beat{remaining === 1 ? '' : 's'} to go
      </span>
    );
  }

  // deck_position trigger — render a live countdown to the threshold.
  const deck = decks.find((d) => d.n === step.trigger_deck);
  const target = step.trigger_at ?? 0;
  if (!deck) {
    return (
      <span style={{ font: '500 10.5px/1 var(--p-mono)', color: 'var(--p-muted)' }}>
        waiting…
      </span>
    );
  }
  const remainingPct = Math.max(0, target * 100 - deck.progress.pct);
  return (
    <span
      style={{
        font: '500 10.5px/1 var(--p-mono)',
        color: 'var(--p-accent)',
        letterSpacing: '0.04em',
      }}
    >
      deck {step.trigger_deck} → {remainingPct.toFixed(0)}% to go
    </span>
  );
}
