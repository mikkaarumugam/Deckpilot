/**
 * useBpmSync — bind ambient CSS animation durations to the live Mixxx BPM.
 *
 * Every page-level pulse/glow keyframe reads its duration from
 * `--p-beat-ms` (and multiples). This hook keeps those vars in lockstep
 * with whatever's actually playing in Mixxx, so the whole UI breathes
 * together at the track's BPM. Cheap visual coherence: a 128-BPM banger
 * gets a faster page than an 85-BPM downtempo, automatically.
 *
 * Selection logic: prefer the highest BPM among PLAYING decks. Fall
 * back to deck 1's BPM if it's analysed. Fall back to 120 BPM if
 * nothing is loaded (the default in theme.css).
 *
 * Why deduplicate via useMemo: useDeckState polls every 250ms. Without
 * dedupe, we'd rewrite the CSS vars 4x/s, which can cause subtle
 * jitter in the animations as durations change mid-cycle.
 */

import { useEffect, useMemo } from 'react';
import type { StateResponse } from '../api/client';

const DEFAULT_BPM = 120;
const MIN_BPM = 60;
const MAX_BPM = 200;

export function useBpmSync(state: StateResponse | null) {
  // Distill the snapshot down to a single number; only re-run the
  // CSS write when this changes, not on every poll.
  const bpm = useMemo(() => {
    if (!state) return DEFAULT_BPM;
    const playing = state.decks.filter(
      (d) => d.status === 'playing' && d.bpm > 0,
    );
    if (playing.length > 0) {
      return Math.max(...playing.map((d) => d.bpm));
    }
    // Nothing playing — sample any analysed deck so the page still
    // has *some* tempo character before the user hits play.
    const anyAnalysed = state.decks.find((d) => d.bpm > 0);
    return anyAnalysed?.bpm ?? DEFAULT_BPM;
  }, [state]);

  useEffect(() => {
    const clamped = Math.max(MIN_BPM, Math.min(MAX_BPM, bpm));
    const beatMs = 60000 / clamped;
    const root = document.documentElement;
    root.style.setProperty('--p-beat-ms', `${beatMs.toFixed(0)}ms`);
    root.style.setProperty('--p-beat-2-ms', `${(beatMs * 2).toFixed(0)}ms`);
    root.style.setProperty('--p-beat-4-ms', `${(beatMs * 4).toFixed(0)}ms`);
    root.style.setProperty('--p-beat-8-ms', `${(beatMs * 8).toFixed(0)}ms`);
  }, [bpm]);
}
