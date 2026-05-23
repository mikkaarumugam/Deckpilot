/**
 * CommandCard — the hero card. Phase 4 version (real backend).
 *
 * Differences from Phase 2:
 * - The typed-command region is a real `<input>` styled to match the
 *   design's italic serif rendering. Browser-native caret replaces the
 *   custom blinking-cursor element from the design.
 * - Plan steps are sourced from the live ParseResponse (real or null).
 *   When phase < 'ready' the plan area is dim; when 'running' / 'done'
 *   the executed step advances visually via the parent hook's timer.
 * - LoadTrack suggestions (D-015) replace the plan area with a
 *   suggestion panel — a card showing the picked track + LLM reasoning.
 *   Run button becomes disabled in that state.
 * - Errors render inline beneath the parsed pill.
 */

import {
  type ParseResponse,
  type SuggestionPayload,
} from '../api/client';
import { type Phase, type PlanStepState } from '../types';
import { PhaseBadge } from './PhaseBadge';
import { PlanStep } from './PlanStep';
import { RunButton } from './RunButton';

interface CommandCardProps {
  phase: Phase;
  text: string;
  onTextChange: (text: string) => void;
  parseResult: ParseResponse | null;
  executed: number;
  error: string | null;
  suggestion: SuggestionPayload | null;
  /** True when the regex parser found no match. UI uses this to render
   *  a "Press ⏎ to ask Haiku" hint instead of an empty plan area. */
  regexMissed: boolean;
  /** True while the GUI auto-load countdown is in flight. Drives the
   *  Cancel button + animated progress bar on the suggestion card.
   *  See D-019. */
  autoLoadPending: boolean;
  /** Countdown duration in ms — used to size the CSS animation. */
  autoLoadCountdownMs: number;
  /** Cancels the in-flight auto-load + clears suggestion + plan. */
  onCancelAutoLoad: () => void;
  /** Triggered by Enter on the input or click on the primary button.
   *  The hook decides whether this means "run the plan" or "ask the LLM". */
  onSubmit: () => void;
  onQueue?: () => void;
}

function stepStateFor(i: number, phase: Phase, executed: number): PlanStepState {
  if (phase === 'typing') return 'hidden';
  // During parsing we WANT steps visible — they're streaming in
  // one-by-one from /parse/stream. Render as pending until the
  // 'complete' event flips us into 'ready'.
  if (phase === 'parsing') return 'pending';
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
  text,
  onTextChange,
  parseResult,
  executed,
  error,
  suggestion,
  regexMissed,
  autoLoadPending,
  autoLoadCountdownMs,
  onCancelAutoLoad,
  onSubmit,
  onQueue,
}: CommandCardProps) {
  const plan = parseResult?.plan ?? [];
  const totalSteps = plan.length;
  const currentStep = phase === 'running' ? executed + 1 : phase === 'done' ? totalSteps : 0;
  const stepWord = totalSteps === 1 ? '' : 's';
  // Only surface the "ask Haiku" hint when the user has typed something
  // meaningful — avoids it flickering on after 2-3 chars during normal typing.
  const hintReady = regexMissed && text.trim().length >= 4;
  const parsedLabel = suggestion
    ? parseResult?.parsed ?? '(suggestion)'
    : parseResult?.parsed ?? (hintReady ? '(press ⏎ to ask Haiku)' : '(awaiting input)');
  const confValue = parseResult?.conf ?? 0;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      onSubmit();
    }
  };

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

      {/* Typed command — real <input> styled to match the design */}
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
        <input
          type="text"
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="bass swap into deck 2 over 4 seconds…"
          autoFocus
          style={{
            all: 'unset',
            flex: 1,
            font: 'inherit',
            color: 'inherit',
            letterSpacing: 'inherit',
            caretColor: 'var(--p-accent)',
          }}
        />
      </div>

      {/* Parsed action row */}
      <div
        style={{
          marginTop: 18,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          opacity: phase === 'typing' && !text ? 0.3 : 1,
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
          <span>{parsedLabel}</span>
        </div>
        {confValue > 0 && (
          <span style={{ font: '400 11.5px/1 var(--p-mono)', color: 'var(--p-muted)' }}>
            {confValue}% confident
          </span>
        )}
        <span style={{ flex: 1 }} />
        <RunButton
          phase={phase}
          currentStep={currentStep}
          totalSteps={totalSteps}
          onClick={onSubmit}
        />
        <button className="pilot-btn-secondary" onClick={onQueue} type="button">
          <span>Queue</span>
          <span style={{ font: '500 10px/1 var(--p-mono)', color: 'var(--p-muted)' }}>⌘⏎</span>
        </button>
      </div>

      {/* Error row — shown when parse / execute fails */}
      {error && (
        <div
          style={{
            marginTop: 10,
            padding: '8px 12px',
            background: 'rgba(248, 113, 113, 0.08)',
            border: '1px solid rgba(248, 113, 113, 0.3)',
            borderRadius: 6,
            font: '400 12px/1.4 var(--p-mono)',
            color: '#f87171',
          }}
        >
          {error}
        </div>
      )}

      {/* Plan OR Suggestion */}
      {suggestion ? (
        <SuggestionPanel
          suggestion={suggestion}
          autoLoadPending={autoLoadPending}
          autoLoadCountdownMs={autoLoadCountdownMs}
          onCancelAutoLoad={onCancelAutoLoad}
        />
      ) : (
        <PlanArea
          plan={plan}
          phase={phase}
          executed={executed}
          stepWord={stepWord}
          showDim={phase === 'typing' && !text}
          regexMissed={hintReady}
          hasText={text.trim().length > 0}
        />
      )}
    </div>
  );
}

// ── Inline subcomponents ────────────────────────────────────────────────

function PlanArea({
  plan,
  phase,
  executed,
  stepWord,
  showDim,
  regexMissed,
  hasText,
}: {
  plan: ParseResponse['plan'];
  phase: Phase;
  executed: number;
  stepWord: string;
  showDim: boolean;
  regexMissed: boolean;
  hasText: boolean;
}) {
  return (
    <div
      style={{
        marginTop: 18,
        paddingTop: 16,
        borderTop: '1px dashed var(--p-border)',
        opacity: showDim ? 0.25 : 1,
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
            Plan · {plan.length} step{stepWord}
          </span>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {plan.map((step, i) => (
          <PlanStep
            key={i}
            n={i + 1}
            step={step}
            last={
              // While streaming, treat the last STREAMED step as a
              // continuation point (we render an "incoming…" row right
              // below it). Only mark it as last when the stream has
              // committed and we're in ready/running/done.
              phase === 'parsing'
                ? false
                : i === plan.length - 1
            }
            state={stepStateFor(i, phase, executed)}
          />
        ))}
        {/* Streaming indicator — shown beneath the last streamed step
            while we're still waiting for more. Disappears the moment
            phase flips to 'ready' (the 'complete' SSE event fired). */}
        {phase === 'parsing' && plan.length > 0 && <StreamingTail />}
        {plan.length === 0 && (
          <div
            style={{
              padding: '8px 22px',
              font: '400 11.5px/1.4 var(--p-mono)',
              color: 'var(--p-muted)',
            }}
          >
            {phase === 'parsing'
              ? 'asking Haiku…'
              : regexMissed && hasText
                ? <>regex didn't match — press <span style={{ color: 'var(--p-accent)' }}>⏎</span> to ask Haiku</>
                : 'plan will render here'}
          </div>
        )}
      </div>
    </div>
  );
}

/** Row shown beneath the last streamed plan step while the SSE
 *  stream is still open. Pulses softly to indicate "more incoming".
 *  Mirrors PlanStep's visual layout (rail + node + label) so it
 *  feels like a placeholder for the next step. */
function StreamingTail() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        paddingLeft: 22,
        marginTop: 4,
        font: '400 11.5px/1.4 var(--p-mono)',
        color: 'var(--p-muted)',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 99,
          background: 'var(--p-accent)',
          animation: 'pilotPulse 1.2s ease-in-out infinite',
        }}
      />
      <span>streaming next step…</span>
    </div>
  );
}

function SuggestionPanel({
  suggestion,
  autoLoadPending,
  autoLoadCountdownMs,
  onCancelAutoLoad,
}: {
  suggestion: SuggestionPayload;
  autoLoadPending: boolean;
  autoLoadCountdownMs: number;
  onCancelAutoLoad: () => void;
}) {
  const { track, deck, reasoning, auto_loadable } = suggestion;
  const showCountdown = auto_loadable && autoLoadPending;
  const countdownSeconds = (autoLoadCountdownMs / 1000).toFixed(1);
  return (
    <div
      style={{
        marginTop: 18,
        paddingTop: 16,
        borderTop: '1px dashed var(--p-border)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          font: '500 10px/1 var(--p-mono)',
          color: 'var(--p-accent)',
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          marginBottom: 14,
        }}
      >
        <span>{showCountdown ? '↻ Loading' : '💡 AI suggests'} for deck {deck}</span>
      </div>
      <div
        style={{
          font: 'italic 400 20px/1.3 var(--p-serif)',
          color: 'var(--p-fg)',
          marginBottom: 6,
        }}
      >
        {track.title}
      </div>
      <div style={{ font: '400 14px/1.2 var(--p-sans)', color: 'var(--p-fg-dim)', marginBottom: 12 }}>
        {track.artist}
      </div>
      <div
        style={{
          display: 'flex',
          gap: 14,
          font: '500 12px/1 var(--p-mono)',
          color: 'var(--p-muted)',
          marginBottom: 14,
        }}
      >
        <span><code>{track.bpm.toFixed(1)} BPM</code></span>
        <span>key: <code>{track.key || '—'}</code></span>
        <span>genre: <code>{track.genre || '—'}</code></span>
      </div>
      {reasoning && (
        <div
          style={{
            padding: '10px 14px',
            background: 'var(--p-accent-dim)',
            border: '1px solid var(--p-accent-edge)',
            borderRadius: 6,
            font: 'italic 400 14.5px/1.5 var(--p-serif)',
            color: 'var(--p-fg)',
          }}
        >
          <span style={{ color: 'var(--p-accent)', fontStyle: 'normal', fontWeight: 500, fontFamily: 'var(--p-mono)', fontSize: '12px' }}>
            Why this track:&nbsp;
          </span>
          {reasoning}
        </div>
      )}

      {showCountdown ? (
        // Auto-load mode (D-019): countdown bar + Cancel button. Bar
        // fills over autoLoadCountdownMs via inline CSS animation —
        // simpler than a state-driven tick and re-renders only once.
        <div
          style={{
            marginTop: 14,
            padding: '12px 14px',
            background: 'var(--p-accent-dim)',
            border: '1px solid var(--p-accent-edge)',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 14,
          }}
        >
          <div style={{ flex: 1 }}>
            <div
              style={{
                font: '500 11.5px/1.3 var(--p-mono)',
                color: 'var(--p-fg)',
                marginBottom: 8,
              }}
            >
              Auto-loading onto deck {deck} in {countdownSeconds}s — DeckPilot is flying Mixxx
            </div>
            <div
              style={{
                width: '100%',
                height: 3,
                background: 'var(--p-border)',
                borderRadius: 99,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: '100%',
                  height: '100%',
                  background: 'var(--p-accent)',
                  transformOrigin: 'left center',
                  animation: `pilotCountdown ${autoLoadCountdownMs}ms linear forwards`,
                }}
              />
            </div>
          </div>
          <button
            type="button"
            onClick={onCancelAutoLoad}
            className="pilot-btn-secondary"
            style={{ flexShrink: 0 }}
          >
            Cancel
          </button>
        </div>
      ) : (
        // Fallback: backend reported the load is ambiguous (multiple
        // library rows match the title+artist) or the GUI adapter
        // isn't wired. User does the load manually. See D-015.
        <div
          style={{
            marginTop: 12,
            font: '400 12.5px/1.5 var(--p-mono)',
            color: 'var(--p-muted)',
          }}
        >
          {auto_loadable
            ? `Drag this onto deck ${deck} in Mixxx when ready.`
            : `Title + artist matches multiple tracks — drag this onto deck ${deck} manually.`}
        </div>
      )}
    </div>
  );
}
