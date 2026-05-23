/**
 * DeckCard — compact "Live state" deck panel.
 *
 * Shows deck number + LIVE/CUED indicator (with a BPM-synced pulse when
 * playing), BPM in big serif numerals, italic track title, artist + key +
 * playhead position, and a thin accent progress bar at the bottom.
 *
 * All deck-state data is consumed via props — the parent (Pilot) is
 * responsible for sourcing it from /state polling (Phase 4). For Phase 2
 * we pass mock data; visual identity is the goal here, not data flow.
 */

import { BPMPulse } from './BPMPulse';

interface DeckCardProps {
  n: 1 | 2;
  track: string;
  artist: string;
  bpm: number;
  keySig: string;
  status: 'playing' | 'paused' | 'cued';
  progress: { t: string; total: string; pct: number };
}

export function DeckCard({ n, track, artist, bpm, keySig, status, progress }: DeckCardProps) {
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
        flexDirection: 'column',
        gap: 8,
      }}
    >
      {/* Header row: deck label + LIVE pulse + BPM */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              font: '500 9.5px/1 var(--p-mono)',
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
                  font: '500 9.5px/1 var(--p-mono)',
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
                font: '500 9.5px/1 var(--p-mono)',
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
              font: '400 28px/1 var(--p-serif)',
              color: 'var(--p-fg)',
              letterSpacing: '-0.02em',
              fontFeatureSettings: '"tnum" 1',
            }}
          >
            {bpm.toFixed(1)}
          </span>
          <span
            style={{
              font: '500 9.5px/1 var(--p-mono)',
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
            font: 'italic 400 15px/1.2 var(--p-serif)',
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
            gap: 8,
            font: '400 11px/1.2 var(--p-sans)',
            color: 'var(--p-muted)',
            marginTop: 2,
          }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {artist}
          </span>
          <span style={{ color: 'var(--p-muted-deep)' }}>·</span>
          <span style={{ font: '500 10.5px/1.2 var(--p-mono)' }}>{keySig}</span>
          <span style={{ color: 'var(--p-muted-deep)' }}>·</span>
          <span style={{ font: '500 10.5px/1.2 var(--p-mono)' }}>
            {progress.t} / {progress.total}
          </span>
        </div>
      </div>

      {/* Thin progress bar at the bottom */}
      <div
        style={{
          marginTop: 2,
          height: 2,
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
            opacity: 0.7,
            borderRadius: 99,
          }}
        />
      </div>
    </div>
  );
}
