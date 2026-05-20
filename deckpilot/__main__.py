"""
CLI entry point.

Two ways to invoke:

Explicit subcommand mode (deterministic, no API key needed):
    python -m deckpilot play --deck 1
    python -m deckpilot fade --deck 2 --seconds 8
    ...

Natural-language mode (parsed via regex + LLM):
    python -m deckpilot "play deck 1"
    python -m deckpilot "fade to deck 2 over 8 seconds"
    python -m deckpilot "kick into the second deck"

The NL form requires ANTHROPIC_API_KEY for anything the regex doesn't cover.
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


# Subcommand names — used to decide between explicit mode and NL mode.
SUBCOMMANDS = {"play", "pause", "crossfader", "fade", "loop", "nudge"}


def _build_explicit_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deckpilot",
        description="Control a DJ deck via virtual MIDI.",
    )
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("play", help="start playback on a deck")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])

    s = sub.add_parser("pause", help="pause a deck")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])

    s = sub.add_parser("crossfader", help="set crossfader position (0.0=left, 1.0=right)")
    s.add_argument("--value", type=float, required=True)

    s = sub.add_parser("fade", help="fade the crossfader to a deck over N seconds")
    s.add_argument("--deck", type=int, default=2, choices=[1, 2])
    s.add_argument("--seconds", type=float, default=8.0)

    s = sub.add_parser("loop", help="toggle an 8-beat loop on a deck")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s.add_argument("--beats", type=int, default=8)

    s = sub.add_parser("nudge", help="briefly nudge a deck forward or back")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s.add_argument("--direction", choices=["forward", "back"], default="forward")

    return p


def _args_to_action(args: argparse.Namespace) -> DJAction:
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


def _resolve_action(argv: list[str]) -> DJAction:
    """Pick the right entry path: explicit subcommand or NL."""
    if not argv:
        # No args at all — show the help for the explicit parser.
        _build_explicit_parser().parse_args([])  # exits
        sys.exit(2)

    if argv[0] in SUBCOMMANDS:
        # Explicit mode.
        args = _build_explicit_parser().parse_args(argv)
        return _args_to_action(args)

    # Natural-language mode. Join everything in case the user forgot quotes:
    #   python -m deckpilot play deck 1   →   "play deck 1"
    text = " ".join(argv)
    # Import lazily so the explicit subcommands work even if the anthropic
    # package isn't installed (e.g. CI for the adapter only).
    from deckpilot.core.parser import parse, ParseError
    try:
        return parse(text)
    except ParseError as exc:
        print(f"[deckpilot] could not parse: {exc}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    action = _resolve_action(argv)

    adapter = MidiAdapter()
    executor = Executor(adapter)

    print(f"[deckpilot] → {action}")
    executor.run(action)
    print("[deckpilot] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
