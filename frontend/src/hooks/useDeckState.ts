/**
 * useDeckState — polls GET /state at a fixed cadence.
 *
 * Returns the latest snapshot. Polling is cheap (the endpoint is fast +
 * read-only + JSON-only — no MIDI traffic on the read side). Default
 * cadence: 250ms. That's the same value the design's animation cycle
 * implies — fast enough to feel "live" but slow enough not to thrash.
 *
 * Errors are swallowed (last good state is kept). If Mixxx isn't running
 * the backend returns sensible defaults, so we don't need to special-case.
 */

import { useEffect, useRef, useState } from 'react';
import { api, type StateResponse } from '../api/client';

const DEFAULT_INTERVAL_MS = 250;

export function useDeckState(intervalMs = DEFAULT_INTERVAL_MS): StateResponse | null {
  const [snapshot, setSnapshot] = useState<StateResponse | null>(null);
  // Use a ref for the in-flight controller so a fast re-render doesn't
  // double-fire the next tick.
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let stopped = false;

    const tick = async () => {
      if (stopped) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const next = await api.state(controller.signal);
        if (!stopped) setSnapshot(next);
      } catch {
        // Network / backend hiccup — keep the last good snapshot.
      }
    };

    void tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      stopped = true;
      clearInterval(id);
      abortRef.current?.abort();
    };
  }, [intervalMs]);

  return snapshot;
}
