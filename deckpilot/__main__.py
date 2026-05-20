"""
CLI entry point.

For M2 we ship a subcommand-style interface (one subcommand per action):

    python -m deckpilot play --deck 1
    python -m deckpilot pause --deck 1
    python -m deckpilot crossfader --value 0.5
    python -m deckpilot fade --deck 2 --seconds 8
    python -m deckpilot loop --deck 1
    python -m deckpilot nudge --deck 1 --direction forward

In M3 we'll add a natural-language form (`python -m deckpilot "play deck 1"`)
that parses the sentence and emits the same DJAction.
"""

from __future__ import annotations

import argparse
import sys

from deckpilot.adapters.midi import MidiAdapter
from deckpilot.core.actions import (
    DJAction,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
)
from deckpilot.core.executor import Executor


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deckpilot",
        description="Control a DJ deck via virtual MIDI.",
    )
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("play", help="start playback on a deck")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])

    s = sub.add_parser("pause", help="pause a deck")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])

    s = sub.add_parser("crossfader", help="set crossfader position (0.0 = left, 1.0 = right)")
    s.add_argument("--value", type=float, required=True)

    s = sub.add_parser("fade", help="fade the crossfader to a deck over N seconds")
    s.add_argument("--deck", type=int, default=2, choices=[1, 2])
    s.add_argument("--seconds", type=float, default=8.0)

    s = sub.add_parser("loop", help="toggle an 8-beat loop on a deck")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s.add_argument("--beats", type=int, default=8,
                   help="(v0.1 always loops 8 beats regardless of this value)")

    s = sub.add_parser("nudge", help="briefly nudge a deck forward or back")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s.add_argument("--direction", choices=["forward", "back"], default="forward")

    return p


def _args_to_action(args: argparse.Namespace) -> DJAction:
    """Translate parsed CLI args into a DJAction dataclass."""
    if args.action == "play":
        return PlayDeck(deck=args.deck)
    if args.action == "pause":
        return PauseDeck(deck=args.deck)
    if args.action == "crossfader":
        return SetCrossfader(value=args.value)
    if args.action == "fade":
        return FadeToDeck(deck=args.deck, seconds=args.seconds)
    if args.action == "loop":
        return LoopDeck(deck=args.deck, beats=args.beats)
    if args.action == "nudge":
        return NudgeDeck(deck=args.deck, direction=args.direction)
    raise ValueError(f"Unhandled action: {args.action!r}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    action = _args_to_action(args)

    adapter = MidiAdapter()
    executor = Executor(adapter)

    print(f"[deckpilot] → {action}")
    executor.run(action)
    print("[deckpilot] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
