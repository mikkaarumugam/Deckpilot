/**
 * useAgentState — polls GET /agent/state at 500ms so the UI's
 * AgentQueue can render which scheduled step is currently running /
 * pending. Mirrors the shape of useDeckState.
 *
 * Returns null until the first response lands; from then on always
 * the latest snapshot. When no schedule is active, the snapshot has
 * `active: false` + an empty steps list — caller hides the panel.
 */

import { useEffect, useState } from 'react';
import { api, type AgentStateResponse } from '../api/client';

const POLL_MS = 500;

export function useAgentState(): AgentStateResponse | null {
  const [state, setState] = useState<AgentStateResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();

    const tick = async () => {
      try {
        const res = await api.agentState(ctrl.signal);
        if (!cancelled) setState(res);
      } catch {
        // Backend hiccup — keep the prior snapshot rather than null.
        // Polling resumes automatically on the next tick.
      }
    };

    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
      ctrl.abort();
    };
  }, []);

  return state;
}
