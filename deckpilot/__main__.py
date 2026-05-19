"""
CLI entry point. Lets you run DeckPilot like:

    python -m deckpilot "play deck 1"
    python -m deckpilot "fade to deck 2 over 8 seconds"

For M0 (skeleton), this just prints what it received so we can verify the
package is installed and importable.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print('Usage: python -m deckpilot "your command here"')
        return 1

    text = " ".join(argv)
    print(f"[deckpilot] received: {text!r}")
    print("[deckpilot] TODO (M3): parse this and dispatch to the MIDI adapter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
