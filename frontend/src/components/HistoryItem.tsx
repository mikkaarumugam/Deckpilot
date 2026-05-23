/**
 * HistoryItem — one row in the history panel below the queue.
 *
 * Italic serif renders the user's prompt verbatim ("kill the bass on deck 1");
 * a small mono pill shows the parsed function call ("eq.low(deck:1) = -inf");
 * the bottom row shows a human summary and (optionally) a from→to diff for
 * reversible actions.
 *
 * `isNew` triggers the pilotFadeIn keyframe — used when an item just
 * landed in history so the appearance reads as "this just happened" rather
 * than "this has been here."
 */

import { type HistoryEntry } from '../types';

export function HistoryItem({ when, prompt, parsed, summary, diff, isNew }: HistoryEntry) {
  return (
    <div
      style={{
        position: 'relative',
        background: 'var(--p-surface)',
        border: '1px solid var(--p-border)',
        borderRadius: 12,
        padding: '14px 16px 14px 18px',
        animation: isNew ? 'pilotFadeIn 0.5s ease-out' : 'none',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <div
          style={{
            font: 'italic 400 16px/1.3 var(--p-serif)',
            color: 'var(--p-fg)',
            letterSpacing: '-0.005em',
          }}
        >
          &ldquo;{prompt}&rdquo;
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: '0 0 auto', marginLeft: 14 }}>
          <span style={{ font: '400 11px/1 var(--p-mono)', color: 'var(--p-muted-deep)' }}>
            {when}
          </span>
          <button className="pilot-icon-btn" title="Undo" type="button">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
              <path
                d="M3 8 L 6 5 M3 8 L 6 11 M3 8 H 11 A 3 3 0 0 1 11 14"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </div>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '3px 8px',
          background: 'var(--p-border)',
          border: '1px solid var(--p-border)',
          borderRadius: 6,
          marginBottom: 8,
          font: '500 11.5px/1 var(--p-mono)',
          color: 'var(--p-fg-dim)',
        }}
      >
        <span style={{ color: 'var(--p-accent)' }}>→</span>
        <span>{parsed}</span>
      </div>
      <div style={{ font: '400 12.5px/1.4 var(--p-sans)', color: 'var(--p-muted)' }}>
        {summary}
        {diff && (
          <span style={{ marginLeft: 8, font: '500 11.5px/1 var(--p-mono)', color: 'var(--p-fg-dim)' }}>
            <span style={{ color: 'var(--p-muted-deep)' }}>{diff.from}</span>
            <span style={{ margin: '0 6px', color: 'var(--p-accent)' }}>→</span>
            <span style={{ color: 'var(--p-fg)' }}>{diff.to}</span>
          </span>
        )}
      </div>
    </div>
  );
}
