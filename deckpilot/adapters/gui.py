"""
MixxxGuiAdapter — fills the one gap MIDI can't reach.

Mixxx's controller-script API exposes everything we need EXCEPT
path-based track loading (verified across 2.5-2.7; see DECISIONS §
D-015 / D-019). For that one operation we drive Mixxx's GUI via
macOS `osascript`: paste the title+artist into the library search,
highlight the top result, fire Mixxx's load shortcut.

Why a separate adapter (vs folding this into MidiAdapter):
- The adapter pattern stays clean — MidiAdapter is MIDI-only, this
  one is GUI-only. Routing decisions stay in one place (the executor /
  MidiAdapter._dispatch_load_track), but each adapter does one kind
  of thing.
- Future-proof: a Mixxx version that adds a real load API would swap
  out THIS adapter, leaving MidiAdapter untouched. Same shape for
  Traktor / Serato if we ever target them.

Keyboard shortcuts assumed (Mixxx default en_US, verified on user's
machine 2026-05-23):
- Shift+Left  → load selected to deck 1
- Shift+Right → load selected to deck 2

If your Mixxx has a custom keyboard map, edit `_LOAD_KEY_CODES`
below. Better long-term fix: add a `LoadSelectedTrack` MIDI binding
in mixxx.midi.xml and dispatch via MIDI instead of keystroke (no
focus-steal). Kept as GUI for now because the focus-steal IS the
demo's "DeckPilot is flying Mixxx" beat — see D-019.
"""

from __future__ import annotations

import subprocess
import time


# macOS key codes used in AppleScript `key code` invocations.
_KEY_RETURN = 36
_KEY_DELETE = 51  # backspace
_KEY_DOWN = 125
_KEY_LEFT = 123
_KEY_RIGHT = 124

# Deck → arrow key for "load selected to deck N" (Mixxx default en_US).
_LOAD_KEY_CODES = {1: _KEY_LEFT, 2: _KEY_RIGHT}


class GuiAdapterError(RuntimeError):
    """Raised when an osascript call fails — usually a permissions issue
    (macOS Accessibility not granted) or Mixxx not running."""


class MixxxGuiAdapter:
    """Drive Mixxx via macOS GUI automation for actions MIDI can't reach.

    Currently exposes one operation: `load_track(deck, query)`. The
    method blocks for ~1-1.5s while Mixxx's library filters and loads,
    so any subsequent step in the plan (e.g. PlayDeck) fires at the
    right moment without explicit scheduling.

    All delays are deliberate — they protect against races where the
    next keystroke arrives before Mixxx's UI has processed the previous
    one. Hand-tuned on the user's machine; bump them up if you see
    misfires under load.
    """

    # Tunable delays (seconds). Exposed as instance attrs so a test or
    # a slow-machine override can bump them without forking the class.
    activate_delay: float = 0.25       # Mixxx → frontmost
    focus_delay: float = 0.15          # Cmd+F → search field focused
    select_all_delay: float = 0.05     # Cmd+A → existing text selected
    filter_delay: float = 0.6          # post-paste → library settles
    highlight_delay: float = 0.1       # Return → focus on result list
    load_settle_delay: float = 0.4     # post-load → deck has the track
    clear_delay: float = 0.2           # post-load → before wiping search

    # ── Public API ────────────────────────────────────────────────────

    def load_track(self, deck: int, query: str) -> None:
        """Search Mixxx for `query`, highlight the top result, load to
        `deck`, then clear the search so the library shows everything
        again. Blocks until the whole flow completes.

        Raises GuiAdapterError if osascript exits non-zero (typically
        means Accessibility permission isn't granted yet).
        """
        if deck not in _LOAD_KEY_CODES:
            raise ValueError(f"deck must be 1 or 2; got {deck}")

        self._copy_to_clipboard(query)
        self._activate_mixxx_and_paste_into_search()
        time.sleep(self.filter_delay)
        self._commit_search_and_highlight_first_row()
        time.sleep(self.highlight_delay)
        self._send_load_shortcut(deck)
        time.sleep(self.load_settle_delay)
        self._clear_search()
        time.sleep(self.clear_delay)

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)

    def _run_osascript(self, script: str) -> None:
        try:
            subprocess.run(["osascript", "-e", script], check=True)
        except subprocess.CalledProcessError as exc:
            raise GuiAdapterError(
                "osascript failed — most likely macOS Accessibility "
                "permission isn't granted for this process. Open "
                "System Settings → Privacy & Security → Accessibility "
                "and enable your terminal/IDE."
            ) from exc

    def _activate_mixxx_and_paste_into_search(self) -> None:
        # Cmd+A before Cmd+V wipes any leftover search text from a
        # previous run (defensive — clear_search at the end of the
        # last call usually handles this, but races happen).
        script = f"""
        tell application "Mixxx" to activate
        delay {self.activate_delay}
        tell application "System Events"
            keystroke "f" using {{command down}}
            delay {self.focus_delay}
            keystroke "a" using {{command down}}
            delay {self.select_all_delay}
            keystroke "v" using {{command down}}
        end tell
        """
        self._run_osascript(script)

    def _commit_search_and_highlight_first_row(self) -> None:
        # After paste, focus is still in the search field — any global
        # Mixxx shortcut would be swallowed as text input. Return
        # commits the filter + moves focus to the result list; Down
        # arrow makes sure row 1 is actually highlighted (not just
        # present in the filtered list).
        script = f"""
        tell application "System Events"
            key code {_KEY_RETURN}
            delay 0.1
            key code {_KEY_DOWN}
        end tell
        """
        self._run_osascript(script)

    def _send_load_shortcut(self, deck: int) -> None:
        key_code = _LOAD_KEY_CODES[deck]
        script = f"""
        tell application "System Events"
            key code {key_code} using {{shift down}}
        end tell
        """
        self._run_osascript(script)

    def _clear_search(self) -> None:
        # Restore Mixxx's full library view after the load. Re-focus
        # the search field, select-all, delete.
        script = f"""
        tell application "System Events"
            keystroke "f" using {{command down}}
            delay {self.focus_delay}
            keystroke "a" using {{command down}}
            delay {self.select_all_delay}
            key code {_KEY_DELETE}
        end tell
        """
        self._run_osascript(script)
