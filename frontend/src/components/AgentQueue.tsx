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

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {state.steps.map((step, i) => (
          <AgentRow key={i} n={i + 1} step={step} decks={decks} />
        ))}
      </div>
    </div>
  );
}

// ── Per-row rendering ────────────────────────────────────────────────────

function AgentRow({
  n,
  step,
  decks,
}: {
  n: number;
  step: AgentStepStatus;
  decks: DeckStatePayload[];
}) {
  const isRunning = step.status === 'running';
  const isDone = step.status === 'done';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '10px 14px',
        background: isRunning ? 'var(--p-accent-dim)' : 'var(--p-surface)',
        border: `1px solid ${
          isRunning ? 'var(--p-accent-edge)' : 'var(--p-border)'
        }`,
        borderRadius: 10,
        opacity: isDone ? 0.45 : 1,
        transition: 'background 0.2s, border-color 0.2s, opacity 0.2s',
      }}
    >
      <StatusIcon status={step.status} />
      <span
        style={{
          font: '500 11px/1 var(--p-mono)',
          color: 'var(--p-muted-deep)',
          width: 18,
        }}
      >
        {String(n).padStart(2, '0')}
      </span>
      <span
        style={{
          flex: 1,
          font: 'italic 400 16px/1.2 var(--p-serif)',
          color: 'var(--p-fg)',
          letterSpacing: '-0.005em',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {step.label}
      </span>
      <TriggerHint step={step} decks={decks} />
    </div>
  );
}

function StatusIcon({ status }: { status: AgentStepStatus['status'] }) {
  if (status === 'done') {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="6" fill="var(--p-accent)" />
        <path
          d="M3.5 7.5 L6 10 L10.5 4.5"
          stroke="var(--p-accent-ink)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (status === 'running') {
    return (
      <span
        style={{
          width: 12,
          height: 12,
          borderRadius: 99,
          background: 'var(--p-accent)',
          // Reuse the BPM-bound pulse so the agent-active dot beats
          // with the music. Cheap visual coherence.
          animation: 'pilotPulse var(--p-beat-2-ms) ease-in-out infinite',
          boxShadow: '0 0 10px var(--p-accent-edge)',
        }}
      />
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle
        cx="7"
        cy="7"
        r="5.5"
        stroke="var(--p-muted)"
        strokeWidth="1.2"
        fill="none"
      />
    </svg>
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
