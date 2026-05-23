/**
 * PhaseBadge — top-right indicator on the hero card.
 *
 * Renders the current phase with a tinted pulse-dot prefix and an optional
 * checkmark when applied. The 5 phases map to 4 visual tones because
 * "ready" and "parsing" share the accent color but differ in label.
 *
 * Pure presentation — no state, no side effects. Driven entirely by the
 * `phase` prop coming from usePilotFlow.
 */

import { type Phase } from '../types';

interface PhaseBadgeProps {
  phase: Phase;
  totalSteps: number;
  currentStep: number;
}

type Tone = 'neutral' | 'accent' | 'ready' | 'live';

interface ToneConfig {
  dot: string;
  fg: string;
  pulse?: boolean;
}

const TONE_COLORS: Record<Tone, ToneConfig> = {
  neutral: { dot: 'var(--p-muted)', fg: 'var(--p-muted)' },
  accent: { dot: 'var(--p-accent)', fg: 'var(--p-accent)', pulse: true },
  ready: { dot: 'var(--p-accent)', fg: 'var(--p-accent)' },
  live: { dot: 'var(--p-live)', fg: 'var(--p-live)' },
};

export function PhaseBadge({ phase, totalSteps, currentStep }: PhaseBadgeProps) {
  const stepWord = totalSteps === 1 ? '' : 's';
  const config: Record<Phase, { text: string; tone: Tone }> = {
    typing: { text: 'Listening', tone: 'neutral' },
    parsing: { text: 'Streaming plan', tone: 'accent' },
    ready: { text: `Ready · ${totalSteps} step${stepWord}`, tone: 'ready' },
    running: { text: `Executing · ${currentStep}/${totalSteps}`, tone: 'accent' },
    done: { text: 'Applied', tone: 'live' },
  };

  const cfg = config[phase];
  const c = TONE_COLORS[cfg.tone];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        font: '500 10px/1 var(--p-mono)',
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
          animation: c.pulse ? 'pilotPulse var(--p-beat-2-ms) ease-in-out infinite' : 'none',
        }}
      />
      <span>{cfg.text}</span>
      {phase === 'done' && (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path
            d="M2 5.2 L4 7.2 L8 3"
            stroke={c.fg}
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </span>
  );
}
