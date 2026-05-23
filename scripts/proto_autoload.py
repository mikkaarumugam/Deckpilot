"""
Throwaway prototype — auto-load a track into Mixxx via GUI automation.

The question this answers: does it actually feel good to watch DeckPilot
ghost-type into Mixxx's search bar and load a track for you?

Flow:
  1. Copy "<title> <artist>" to the macOS clipboard via pbcopy.
  2. AppleScript: activate Mixxx, Cmd+F to focus library search, Cmd+V
     to paste, brief delay for the library list to filter.
  3. AppleScript: Shift+F1 or Shift+F2 (Mixxx's default "load selected
     to deck 1/2" shortcut) — loads whatever row is highlighted.

What to watch for when you run it:
  - Does Mixxx popping to the front read as "AI is flying my app" or
    as a jarring glitch?
  - Does the search field correctly receive the paste? (Some Mixxx
    builds focus the wrong text input on Cmd+F.)
  - Does the top result of the filtered library happen to be the
    track you wanted? Library sort order matters here.
  - Does Shift+F1/F2 actually load? (Default Mixxx shortcut on macOS —
     if you've remapped, this won't fire.)

If any step misfires, the failure is visible — nothing destructive
happens unless the load step fires, and if it loads the WRONG track,
just reset Mixxx.

Run:
  python scripts/proto_autoload.py --title "Live Forever" --artist "Oasis" --deck 2
"""

from __future__ import annotations

import argparse
import subprocess
import time


def copy_to_clipboard(text: str) -> None:
    """pbcopy is the macOS native; one subprocess call, no deps."""
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def run_osascript(script: str) -> None:
    """Fire an AppleScript via osascript. Raises CalledProcessError on
    non-zero exit so we don't silently swallow Accessibility-permission
    denials."""
    subprocess.run(["osascript", "-e", script], check=True)


def focus_mixxx_and_paste_search(query: str) -> None:
    """Bring Mixxx to the front, focus the library search field via
    Cmd+F, and paste the query. The delays are hand-tuned; if you see
    misfires on a slower machine, bump them up.

    NB: this requires the calling process to have macOS Accessibility
    permission. First run will prompt; grant it to whatever terminal /
    Python binary is running this script. Permanent after that.
    """
    copy_to_clipboard(query)
    script = """
    tell application "Mixxx" to activate
    delay 0.25
    tell application "System Events"
        keystroke "f" using {command down}
        delay 0.15
        keystroke "a" using {command down}
        delay 0.05
        keystroke "v" using {command down}
    end tell
    """
    run_osascript(script)


def commit_search_and_highlight_first_row() -> None:
    """After paste, focus is still in the search field — any global
    Mixxx shortcut would be swallowed as text input. Return commits the
    filter and moves focus to the result list; Down arrow ensures row 1
    is actually highlighted (not just present).

    Return = key code 36, Down arrow = key code 125 on macOS.
    """
    script = """
    tell application "System Events"
        key code 36
        delay 0.1
        key code 125
    end tell
    """
    run_osascript(script)


def load_to_deck(deck: int) -> None:
    """Mixxx default keyboard mapping (en_US) on this machine, verified
    by the user: Shift+Left → load selected to deck 1, Shift+Right →
    load to deck 2.

    Left arrow = key code 123, Right arrow = key code 124 on macOS.
    """
    if deck == 1:
        key_code = 123
    elif deck == 2:
        key_code = 124
    else:
        raise ValueError(f"deck must be 1 or 2; got {deck}")

    script = f"""
    tell application "System Events"
        key code {key_code} using {{shift down}}
    end tell
    """
    run_osascript(script)


def clear_search() -> None:
    """Restore Mixxx's full library view after our load fires. Cmd+F
    focuses the search field, Cmd+A selects whatever is there, Delete
    wipes it. Mixxx re-shows the unfiltered library immediately.

    Delete (backspace) = key code 51 on macOS.
    """
    script = """
    tell application "System Events"
        keystroke "f" using {command down}
        delay 0.1
        keystroke "a" using {command down}
        delay 0.05
        key code 51
    end tell
    """
    run_osascript(script)


def play_deck(deck: int) -> None:
    """Mixxx play/pause hotkeys on this machine (verified by user):
    D = deck 1, L = deck 2. Note this is a TOGGLE — firing on an
    already-playing deck pauses it.
    Key codes: D = 2, L = 37.
    """
    if deck == 1:
        key_code = 2
    elif deck == 2:
        key_code = 37
    else:
        raise ValueError(f"deck must be 1 or 2; got {deck}")

    script = f"""
    tell application "System Events"
        key code {key_code}
    end tell
    """
    run_osascript(script)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--title", required=True, help="track title")
    p.add_argument("--artist", default="", help="artist (helps disambiguate)")
    p.add_argument("--deck", type=int, default=1, choices=[1, 2])
    p.add_argument(
        "--filter-delay",
        type=float,
        default=0.6,
        help="seconds to wait for Mixxx's library to filter after paste "
        "(default 0.6; bump up if the load fires before filter settles)",
    )
    p.add_argument(
        "--no-load",
        action="store_true",
        help="search only, do not fire the load — useful for the first "
        "test run to confirm the search step looks right before risking "
        "a wrong-track load",
    )
    p.add_argument(
        "--play",
        action="store_true",
        help="after loading, also press the deck's play hotkey "
        "(D for deck 1, F for deck 2). Default off — load only.",
    )
    p.add_argument(
        "--play-delay",
        type=float,
        default=0.4,
        help="seconds between load and play (default 0.4; gives Mixxx "
        "time to finish loading the track before play fires)",
    )
    args = p.parse_args()

    query = f"{args.title} {args.artist}".strip()
    print(f"[1/3] copying query to clipboard: {query!r}")
    print("[2/3] activating Mixxx + pasting into search…")
    focus_mixxx_and_paste_search(query)

    print(f"[…] waiting {args.filter_delay}s for library to filter")
    time.sleep(args.filter_delay)

    if args.no_load:
        print("[3/3] --no-load set; skipping load step. Check the search field in Mixxx.")
        return

    print("[3/3a] committing search + highlighting top row (Return, Down)")
    commit_search_and_highlight_first_row()
    time.sleep(0.15)

    arrow = "Left" if args.deck == 1 else "Right"
    print(f"[3/3b] firing Shift+{arrow} to load highlighted row into deck {args.deck}")
    load_to_deck(args.deck)

    if args.play:
        time.sleep(args.play_delay)
        hotkey = "D" if args.deck == 1 else "L"
        print(f"[4/5] firing {hotkey} to play deck {args.deck}")
        play_deck(args.deck)

    time.sleep(0.2)
    print("[5/5] clearing search field so the full library shows again")
    clear_search()

    print("done. If the wrong track loaded, just reset Mixxx and re-try with a more specific --artist.")


if __name__ == "__main__":
    main()
