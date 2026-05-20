"""
CLI entry point.

Two ways to invoke:

Explicit subcommand mode (deterministic, no API key needed):
    python -m deckpilot play --deck 1
    python -m deckpilot fade --deck 2 --seconds 8
    ...

Natural-language mode (parsed via regex + LLM):
    python -m deckpilot "play deck 1"
    python -m deckpilot "bass swap into deck 2"
    python -m deckpilot "kick into the second deck"

The NL form uses the regex fast-path for canonical phrasings and falls
back to Claude (via `claude -p`) for paraphrases and multi-step plans
like the bass swap.
"""

from __future__ import annotations

import argparse
import sys

from deckpilot.adapters.midi import MidiAdapter
from deckpilot.core.actions import (
    ActionPlan,
    DJAction,
    FadeToDeck,
    LoopDeck,
    NudgeDeck,
    PauseDeck,
    PlayDeck,
    SetCrossfader,
)
from deckpilot.core.executor import Executor


SUBCOMMANDS = {"play", "pause", "crossfader", "fade", "loop", "nudge"}


def _build_explicit_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deckpilot",
        description="Control a DJ deck via virtual MIDI.",
    )
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("play");       s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s = sub.add_parser("pause");      s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s = sub.add_parser("crossfader"); s.add_argument("--value", type=float, required=True)
    s = sub.add_parser("fade")
    s.add_argument("--deck", type=int, default=2, choices=[1, 2])
    s.add_argument("--seconds", type=float, default=8.0)
    s = sub.add_parser("loop")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s.add_argument("--beats", type=int, default=8)
    s = sub.add_parser("nudge")
    s.add_argument("--deck", type=int, default=1, choices=[1, 2])
    s.add_argument("--direction", choices=["forward", "back"], default="forward")

    return p


def _args_to_action(args: argparse.Namespace) -> DJAction:
    if args.action == "play":       return PlayDeck(deck=args.deck)
    if args.action == "pause":      return PauseDeck(deck=args.deck)
    if args.action == "crossfader": return SetCrossfader(value=args.value)
    if args.action == "fade":       return FadeToDeck(deck=args.deck, seconds=args.seconds)
    if args.action == "loop":       return LoopDeck(deck=args.deck, beats=args.beats)
    if args.action == "nudge":      return NudgeDeck(deck=args.deck, direction=args.direction)
    raise ValueError(f"Unhandled action: {args.action!r}")


def _resolve_plan(argv: list[str]) -> ActionPlan:
    if not argv:
        _build_explicit_parser().parse_args([])  # exits with help
        sys.exit(2)

    if argv[0] in SUBCOMMANDS:
        args = _build_explicit_parser().parse_args(argv)
        return ActionPlan.single(_args_to_action(args))

    # Natural-language mode.
    text = " ".join(argv)
    from deckpilot.core.parser import parse, ParseError
    try:
        return parse(text)
    except ParseError as exc:
        print(f"[deckpilot] could not parse: {exc}", file=sys.stderr)
        sys.exit(1)


def _print_plan(plan: ActionPlan) -> None:
    if len(plan.steps) == 1 and plan.steps[0].at_seconds == 0:
        # Single immediate action — keep the log line concise.
        print(f"[deckpilot] → {plan.steps[0].action}")
        return

    print(f"[deckpilot] → plan with {len(plan.steps)} steps:")
    for step in plan.steps:
        print(f"    t={step.at_seconds:5.2f}s  {step.action}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    plan = _resolve_plan(argv)

    adapter = MidiAdapter()
    executor = Executor(adapter)

    _print_plan(plan)
    executor.run_plan(plan)
    print("[deckpilot] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
