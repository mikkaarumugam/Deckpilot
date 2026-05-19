"""
Abstract Adapter interface. Each DJ software gets its own concrete adapter.

The whole point: the rest of the system never knows which adapter is active.
Add Mixxx later → write a MixxxAdapter, plug it in, nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from deckpilot.core.actions import DJAction


class Adapter(ABC):
    @abstractmethod
    def dispatch(self, action: DJAction) -> None:
        """Execute the action against the target DJ software."""
        ...
