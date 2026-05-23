/**
 * DeckCard — compact "Live state" deck panel.
 *
 * Layout: square album art on the left, content column on the right
 * (deck label + LIVE/CUED + BPM up top, italic track title + meta
 * underneath, accent progress bar across the bottom).
 *
 * Artwork is loaded from /artwork/{trackId} — embedded ID3/MP4 image
 * extracted by the backend's mutagen pipeline. We always try the URL
 * and use onError to swap in a placeholder, so the component doesn't
 * need to know up-front whether the file has art.
 */

import { useEffect, useState } from 'react';

import { API_BASE } from '../api/client';
import { BPMPulse } from './BPMPulse';

interface DeckCardProps {
  n: 1 | 2;
  /** Library row id — used to build the artwork URL. Undefined when
   *  no track is loaded; the artwork slot shows a placeholder. */
  trackId?: number;
  track: string;
  artist: string;
  bpm: number;
  keySig: string;
  status: 'playing' | 'paused' | 'cued';
  progress: { t: string; total: string; pct: number };
}

export function DeckCard({
  n,
  trackId,
  track,
  artist,
  bpm,
  keySig,
  status,
  progress,
}: DeckCardProps) {
  const isPlaying = status === 'playing';

  return (
    <div
      style={{
        flex: 1,
        background: 'var(--p-surface)',
        border: '1px solid var(--p-border)',
        borderRadius: 12,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'row',
        gap: 14,
        alignItems: 'stretch',
        minWidth: 0,
      }}
    >
      {/* Album art (or placeholder) — fixed square on the left. */}
      <Artwork trackId={trackId} />

      {/* Content column on the right — wraps the old layout. */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
      {/* Header row: deck label + LIVE pulse + BPM */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              font: '500 10.5px/1 var(--p-mono)',
              letterSpacing: '0.18em',
              color: 'var(--p-muted)',
              textTransform: 'uppercase',
            }}
          >
            Deck {n}
          </span>
          {isPlaying ? (
            <>
              <BPMPulse bpm={bpm} color="var(--p-live)" size={4} />
              <span
                style={{
                  font: '500 10.5px/1 var(--p-mono)',
                  color: 'var(--p-live)',
                  letterSpacing: '0.14em',
                }}
              >
                LIVE
              </span>
            </>
          ) : (
            <span
              style={{
                font: '500 10.5px/1 var(--p-mono)',
                color: 'var(--p-muted)',
                letterSpacing: '0.14em',
              }}
            >
              · CUED
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
          <span
            style={{
              // Serif numerals (esp. Instrument Serif) read as "I" not "1" at
              // this scale — swapped to mono with tabular figures so each
              // digit gets even spacing and reads as data, not editorial.
              font: '500 42px/1 var(--p-mono)',
              color: 'var(--p-fg)',
              letterSpacing: '-0.02em',
              fontFeatureSettings: '"tnum" 1',
            }}
          >
            {bpm.toFixed(1)}
          </span>
          <span
            style={{
              font: '500 10.5px/1 var(--p-mono)',
              color: 'var(--p-muted)',
              letterSpacing: '0.14em',
            }}
          >
            BPM
          </span>
        </div>
      </div>

      {/* Track meta */}
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            font: 'italic 400 19px/1.2 var(--p-serif)',
            color: 'var(--p-fg)',
            letterSpacing: '-0.005em',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {track}
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginTop: 4,
            minWidth: 0,
          }}
        >
          {/* Artist — visually the lead of this row. Bumped to
              fg-dim so it has real presence vs the muted utility
              chips beside it. */}
          <span
            style={{
              font: '400 13.5px/1.2 var(--p-sans)',
              color: 'var(--p-fg-dim)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              minWidth: 0,
            }}
          >
            {artist}
          </span>
          {/* Key — pill-styled so it reads as a *metadata badge*
              instead of more inline text. Same visual language as
              the fn pill on the command card, downsized. */}
          {keySig && keySig !== '—' && (
            <span
              style={{
                flexShrink: 0,
                font: '500 10.5px/1 var(--p-mono)',
                color: 'var(--p-accent)',
                padding: '3px 7px',
                background: 'var(--p-accent-dim)',
                border: '1px solid var(--p-accent-edge)',
                borderRadius: 5,
                letterSpacing: '0.04em',
              }}
            >
              {keySig}
            </span>
          )}
          {/* Time — only render when we actually have a playhead.
              Currently DeckPilot can't read position so this stays
              hidden until the agent-layer work lands. Removes the
              "— / —" wart that made the row look broken. */}
          {progress.t !== '—' && progress.total !== '—' && (
            <span
              style={{
                flexShrink: 0,
                font: '500 11px/1.2 var(--p-mono)',
                color: 'var(--p-muted)',
                fontFeatureSettings: '"tnum" 1',
              }}
            >
              {progress.t} / {progress.total}
            </span>
          )}
        </div>
      </div>

      {/* Progress bar at the bottom — beefed up from 2px to 4px so
          it actually reads as part of the card. Subtle even when
          progress is 0 (the track outline still gets weight). */}
      <div
        style={{
          marginTop: 4,
          height: 4,
          width: '100%',
          background: 'var(--p-border)',
          borderRadius: 99,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${progress.pct}%`,
            background: 'var(--p-accent)',
            opacity: 0.85,
            borderRadius: 99,
            // Smooth out polls so the bar fills naturally instead of
            // stepping in 250ms-aligned jumps once we have real data.
            transition: 'width 0.3s linear',
          }}
        />
      </div>
      </div>
    </div>
  );
}

/** Square album-art tile rendered to the left of each DeckCard's
 *  content. Tries /artwork/{id}; renders a styled placeholder on
 *  error or when no track is loaded. */
function Artwork({ trackId }: { trackId?: number }) {
  // Loaded flag is the simplest way to do an onError fallback —
  // start optimistic, flip to false if the <img> errors out (404
  // when the track has no embedded art, network error, etc.).
  const [loaded, setLoaded] = useState(true);

  // Reset the optimistic flag when the deck swaps to a different
  // track — otherwise a prior 404 on one track would leave new tracks
  // permanently stuck on the placeholder.
  useEffect(() => {
    setLoaded(true);
  }, [trackId]);

  const showImage = trackId !== undefined && loaded;
  const src = trackId !== undefined ? `${API_BASE}/artwork/${trackId}` : undefined;

  return (
    <div
      style={{
        width: 84,
        height: 84,
        flexShrink: 0,
        borderRadius: 8,
        overflow: 'hidden',
        background: 'var(--p-bg)',
        border: '1px solid var(--p-border)',
        position: 'relative',
      }}
    >
      {showImage && src && (
        <img
          src={src}
          alt=""
          onError={() => setLoaded(false)}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            display: 'block',
          }}
        />
      )}
      {!showImage && (
        // Placeholder — coral diamond on warm surface. Subtle, never
        // distracting; signals "art slot, just nothing embedded."
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background:
              'radial-gradient(circle at 30% 30%, var(--p-accent-dim), transparent 70%)',
          }}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <rect
              x="3.5"
              y="3.5"
              width="11"
              height="11"
              transform="rotate(45 9 9)"
              stroke="var(--p-muted-deep)"
              strokeWidth="1.2"
            />
          </svg>
        </div>
      )}
    </div>
  );
}
