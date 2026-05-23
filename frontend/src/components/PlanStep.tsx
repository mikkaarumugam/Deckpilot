/**
 * PlanStep — one row in the plan timeline. Rail + node + body.
 *
 * Four visual states (mapped from PlanStepState):
 *
 *   hidden  — collapsed; opacity 0 (used while the parser streams steps in)
 *   pending — visible but muted; node is outlined
 *   running — node pulses; progress bar fills over dMs ms
 *   done    — node solid + checkmark; rail to next node is accent-tinted
 *
 * The progress bar is a one-shot animation keyed to dMs so it always
 * completes at the correct time regardless of React's render cadence. We
 * key by `${n}-${dMs}` so changing the duration mid-run triggers a fresh
 * animation rather than picking up partway through.
 */

import { type PlanStepState, type PlanStepData } from '../types';

interface PlanStepProps {
  n: number;
  step: PlanStepData;
  last: boolean;
  state: PlanStepState;
}

export function PlanStep({ n, step, last, state }: PlanStepProps) {
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
        transition: 'opacity 0.35s, transform 0.35s',
      }}
    >
      {/* Rail + node — left gutter */}
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
      <div style={{ flex: 1, paddingBottom: last ? 0 : 10, minWidth: 0 }}>
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
            {step.fn}
          </span>
          <span style={{ flex: 1 }} />
          {step.t && step.t !== '—' && (
            <span style={{ font: '500 11.5px/1 var(--p-mono)', color: 'var(--p-muted)' }}>
              {step.t}
            </span>
          )}
          {isDone && (
            <span
              style={{
                font: '500 11px/1 var(--p-mono)',
                color: 'var(--p-live)',
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
            font: '400 12.5px/1.4 var(--p-mono)',
            color: isPending ? 'var(--p-muted)' : 'var(--p-fg-dim)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            transition: 'color 0.25s',
          }}
        >
          {step.detail}
        </div>
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
              key={`bar-${n}-${step.dMs}`}
              style={{
                height: '100%',
                width: '100%',
                background: 'var(--p-accent)',
                transformOrigin: 'left center',
                animation: `pilotStepBar ${step.dMs}ms linear forwards`,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
