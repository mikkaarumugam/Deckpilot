/**
 * CommandCard — the hero card. Houses everything that depends on phase.
 *
 * Layout (top to bottom):
 *
 *   ✱ Command                                  [PhaseBadge]
 *   › <typed command in italic serif, blinks cursor during typing>
 *   [fn: parsed signature]  N% confident   [Queue]  [Run]
 *   ─ ─ ─ ─ ─ (dashed separator) ─ ─ ─ ─ ─
 *   ● Plan · N steps
 *     <PlanStep × N>
 *
 * All phase-dependent state (which step is hidden / pending / running / done,
 * whether the cursor blinks) is computed from props — keeps the component
 * pure and easy to swap mock-flow for real-flow in Phase 4.
 */

import { type Phase, type PlanStepData, type PlanStepState } from '../types';
import { PhaseBadge } from './PhaseBadge';
import { PlanStep } from './PlanStep';
import { RunButton } from './RunButton';

interface CommandCardProps {
  phase: Phase;
  typedText: string;
  showCursor: boolean;
  parsed: string;
  conf: number;
  plan: PlanStepData[];
  revealed: number;
  executed: number;
  exampleIdx: number;
  onRun?: () => void;
  onQueue?: () => void;
}

function stepStateFor(
  i: number,
  phase: Phase,
  revealed: number,
  executed: number,
): PlanStepState {
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
}

export function CommandCard({
  phase,
  typedText,
  showCursor,
  parsed,
  conf,
  plan,
  revealed,
  executed,
  exampleIdx,
  onRun,
  onQueue,
}: CommandCardProps) {
  const totalSteps = plan.length;
  const currentStep = phase === 'running' ? executed + 1 : phase === 'done' ? totalSteps : 0;
  const stepWord = totalSteps === 1 ? '' : 's';

  return (
    <div
      style={{
        marginBottom: 28,
        background: 'var(--p-surface)',
        border: '1px solid var(--p-border-strong)',
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
            font: '500 10px/1 var(--p-mono)',
            color: 'var(--p-muted)',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
          }}
        >
          <span style={{ color: 'var(--p-accent)' }}>✱</span>
          <span>Command</span>
        </div>
        <PhaseBadge phase={phase} totalSteps={totalSteps} currentStep={currentStep} />
      </div>

      {/* Typed command */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 8,
          font: 'italic 400 28px/1.2 var(--p-serif)',
          color: 'var(--p-fg)',
          minHeight: 36,
          letterSpacing: '-0.01em',
        }}
      >
        <span style={{ color: 'var(--p-accent)', fontStyle: 'normal' }}>›</span>
        <span>
          {typedText}
          {showCursor && (
            <span
              style={{
                display: 'inline-block',
                width: 2,
                height: 24,
                background: 'var(--p-accent)',
                marginLeft: 2,
                transform: 'translateY(4px)',
                animation: 'pilotBlink 1.1s steps(2) infinite',
              }}
            />
          )}
        </span>
      </div>

      {/* Parsed action row */}
      <div
        style={{
          marginTop: 18,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          opacity: phase === 'typing' ? 0.3 : 1,
          transition: 'opacity 0.3s',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 10px',
            background: 'var(--p-accent-dim)',
            border: '1px solid var(--p-accent-edge)',
            borderRadius: 8,
            font: '500 12px/1 var(--p-mono)',
            color: 'var(--p-fg)',
          }}
        >
          <span style={{ color: 'var(--p-accent)' }}>fn</span>
          <span>{parsed}</span>
        </div>
        <span style={{ font: '400 11.5px/1 var(--p-mono)', color: 'var(--p-muted)' }}>
          {conf}% confident
        </span>
        <span style={{ flex: 1 }} />
        <RunButton
          phase={phase}
          currentStep={currentStep}
          totalSteps={totalSteps}
          onClick={onRun}
        />
        <button className="pilot-btn-secondary" onClick={onQueue} type="button">
          <span>Queue</span>
          <span style={{ font: '500 10px/1 var(--p-mono)', color: 'var(--p-muted)' }}>⌘⏎</span>
        </button>
      </div>

      {/* Plan */}
      <div
        style={{
          marginTop: 18,
          paddingTop: 16,
          borderTop: '1px dashed var(--p-border)',
          opacity: phase === 'typing' ? 0.25 : 1,
          transition: 'opacity 0.3s',
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
              font: '500 10px/1 var(--p-mono)',
              color: 'var(--p-muted)',
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
            }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <circle cx="5" cy="5" r="4" stroke="var(--p-accent)" strokeWidth="1.2" fill="none" />
              <circle cx="5" cy="5" r="1.5" fill="var(--p-accent)" />
            </svg>
            <span>
              Plan · {totalSteps} step{stepWord}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {plan.map((step, i) => (
            <PlanStep
              key={`${exampleIdx}-${i}`}
              n={i + 1}
              step={step}
              last={i === totalSteps - 1}
              state={stepStateFor(i, phase, revealed, executed)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
