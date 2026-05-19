"""
The executor takes a DJAction (or list of them) and runs it through the adapter.

For simple actions (play, pause) it just dispatches once. For time-based actions
like FadeToDeck, it steps the crossfader CC over time — that's the only
"interesting" loop in the codebase, and we'll write it for real in M2.
"""

from __future__ import annotations

# TODO(M2): implement run(action, adapter) — handles instant + time-based actions.
