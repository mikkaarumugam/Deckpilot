/**
 * RunButton — the primary action button on the hero card. Morphs by phase.
 *
 *   idle (typing) → "Run" (disabled — nothing parsed yet)
 *   parsing       → "Drafting…" (disabled while LLM thinks)
 *   ready         → "Run" + glow animation (accept Enter)
 *   running       → "Running 2/6" (disabled, shows progress)
 *   done          → "Applied" (disabled)
 *
 * The disabled states aren't just visual — Enter / click should be ignored
 * during them, since firing a Run on an in-progress execution would double-
 * dispatch. Wired up in Phase 4.
 */

import { type Phase } from '../types';

interface RunButtonProps {
  phase: Phase;
  currentStep: number;
  totalSteps: number;
  /** True when the input has typed text. In phase='typing' this flips
   *  the button from disabled to "Ask Haiku" — same behaviour as the
   *  Enter keyboard handler, which falls through to LLM parse when no
   *  plan is ready. Without this, Run looked broken on paraphrased
   *  prompts. */
  hasText?: boolean;
  onClick?: () => void;
}

export function RunButton({ phase, currentStep, totalSteps, hasText, onClick }: RunButtonProps) {
  let label = 'Run';
  let kbd: string | null = '⏎';
  let disabled = false;
  let extraClass = '';

  if (phase === 'typing') {
    if (hasText) {
      // Mirror what Enter does: kick off the LLM parse. Label matches
      // the pill hint ("press ⏎ to ask Haiku") so the action is clear.
      label = 'Ask Haiku';
      extraClass = 'pilot-btn-glow';
    } else {
      label = 'Run';
      disabled = true;
    }
  } else if (phase === 'parsing') {
    label = 'Drafting…';
    disabled = true;
  } else if (phase === 'ready') {
    label = 'Run';
    extraClass = 'pilot-btn-glow';
  } else if (phase === 'running') {
    label = `Running ${currentStep}/${totalSteps}`;
    disabled = true;
    kbd = null;
  } else if (phase === 'done') {
    label = 'Applied';
    disabled = true;
    kbd = null;
  }

  return (
    <button
      className={`pilot-btn-primary ${extraClass}`}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <span>{label}</span>
      {kbd && <span className="pilot-btn-kbd">{kbd}</span>}
    </button>
  );
}
