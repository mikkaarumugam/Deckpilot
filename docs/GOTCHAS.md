# GOTCHAS

Every painful debugging session we already paid the price for, so
future you (or future Claude) doesn't pay it again. Newest first.

---

## Mixxx caches analysed BPM in RAM; library DB lags until a clean quit
**Symptom.** A track shows e.g. 90.6 BPM in Mixxx's library UI, but
`SELECT bpm FROM library WHERE id=...` returns `0.0`. DeckPilot's
sidebar shows "(not in library)" or "(BPM not yet analysed)" for a
track Mixxx clearly identified.

**Cause.** Mixxx analyses BPM on track load and shows the result in the
UI immediately, but doesn't always flush the summary `bpm` column to
the SQLite library DB until Mixxx exits cleanly. The detailed beat data
lands in the binary `beats` column sooner, but our reader uses the
plain `bpm` column.

**Fix.** Quit Mixxx (Cmd+Q) and reopen. Clean shutdown persists all
analysis; on reopen, `library.bpm` is populated and DeckPilot's lookup
resolves the track. Alternatively right-click → "Reanalyze" in Mixxx
forces a per-track write.

**Why we don't engineer around it.** The fixes (read ID3 from the
audio file via `mutagen`, or parse Mixxx's protobuf `beats` blob) both
violate the "minimal deps" project rule. The user-facing
"(BPM not yet analysed)" message is honest, and quitting Mixxx is one
keystroke. Documented over fixed.

---

## Streamlit + rtmidi segfaults on auto-reload
**Symptom.** Edit a file while Streamlit is running, Streamlit
auto-reloads, browser shows "Streamlit stopped." Background log has
`Segmentation fault: 11` and no Python traceback.

**Cause.** rtmidi's MidiIn callback runs on a native thread. When
Streamlit reloads, Python tears down state but the rtmidi callback
thread can still fire — referencing freed memory.

**Fix.** In `MixxxFeedback.stop()`, call `cancel_callback()` BEFORE
`close_port()` to close the race window. Also register `stop` with
`atexit` so the port closes cleanly on Python process exit. Cold-
restart Streamlit if the segfault has already happened — the OS may
hold the IAC port for a few seconds afterward.

---

## VirtualDJ Home throttles MIDI controllers to 10 minutes/launch
**Symptom.** VDJ shows "Activity" in the IAC Driver controllers panel
(it's receiving the MIDI) but actions silently no-op. No error, no
warning. Manual play works fine.

**Cause.** VirtualDJ Home (the free version, when not logged in)
restricts unrecognized MIDI controllers to the first 10 minutes after
each launch. IAC Driver is treated as "unrecognized." After 10 min,
MIDI events are received but actions don't fire.

**Fix.** **Use Mixxx instead.** Mixxx is fully open-source, no
licensing wall. The DeckPilot architecture is software-agnostic — same
code, different adapter mapping.

**Time lost discovering this:** ~45 minutes on May 19, 2026.

---

## Mixxx audio output defaults to wrong device
**Symptom.** Deck visually plays in Mixxx (waveform cursor moves) but
no sound through speakers.

**Cause.** Mixxx persists the last-used sound device. If you ever ran
it with an external monitor connected as the audio output, it'll keep
trying that device on launch even after the monitor's gone.

**Fix.** Mixxx → Preferences → Sound Hardware → **Master** dropdown →
pick "MacBook Air Speakers" (or your built-in speaker name). Apply.

---

## MIDI "note_on velocity 0" is treated as note_off (and dropped)
**Symptom.** Using one note for play AND pause via velocity doesn't
work in Mixxx with `<normal/>` bindings. Velocity 127 plays the deck
but velocity 0 doesn't pause it.

**Cause.** The MIDI spec says note_on with velocity 0 is equivalent to
note_off. Mixxx's MIDI driver enforces that interpretation: it
converts velocity-zero note_ons to note_offs at the input layer,
*before* user bindings see them. So a `<normal/>` binding listening on
status 0x90 never receives the velocity-0 event.

**Fix.** Use **separate notes** for each intent (note 60 = play deck 1,
note 61 = pause deck 1) and route them through `<script-binding/>` to
JS handlers in `mixxx.midi.js` that explicitly call
`engine.setValue("[Channel1]", "play", 1 or 0)`. See `D-004` in
DECISIONS.md.

---

## Streamlit hot-reloads function bodies but NOT new imports
**Symptom.** Add a new function to a module → import it in
`dashboard.py` → refresh the browser → `ImportError: cannot import
name 'foo' from 'bar'`.

**Cause.** Streamlit's auto-reloader re-runs the script on file save
but doesn't re-import already-cached modules. Adding new exported
symbols requires a full restart.

**Fix.** Ctrl+C the Streamlit terminal, rerun `streamlit run
app/dashboard.py`. Browser refresh alone won't do it.

---

## VirtualDJ's "Deck" dropdown does NOT prepend to the action string
**Symptom.** Setting Action: `play_button`, Deck dropdown: `left`
saves to XML as `<map action="play_button" />` — no deck specified —
and silently doesn't fire on either deck.

**Cause.** The Deck dropdown is purely a UI filter for the action
list. It doesn't get injected into the saved action string. VDJ
expects the deck to be part of the action text: `deck 1 play_button`.

**Fix (for VDJ).** Type the deck prefix directly into the Action text:
`deck 1 play_button` or `deck left play_button`.

**Why this still matters even though we use Mixxx now.** This is a
generic "the UI is lying to you" pattern that bit us once and could
bite again with any other tool's MIDI mapping editor.

---

## Mixxx 2.5.6 doesn't have stems (2.6+ required)
**Symptom.** "Mute the vocals on deck 1" doesn't work; the
`[Channel1Stem1]` group doesn't exist.

**Cause.** Stem mixing was introduced in Mixxx 2.6 beta (May 2025).
The brew cask currently ships 2.5.6 stable; brew `mixxx@snapshot`
ships 2.7-alpha.

**Workaround.** Use EQ-based bass swap (D-010): pre-cut deck 2 bass
with SetEQ → fade crossfader → cut deck 1 bass at midpoint → restore.
Same musical result. Real DJs do it this way anyway.

---

## `claude -p` default model is Sonnet/Opus, not Haiku
**Symptom.** LLM parsing takes 1.5-3s per command for what should be
sub-second classification work.

**Cause.** Without `--model haiku`, `claude -p` uses whatever Claude
Code's interactive default is.

**Fix.** Pass `--model haiku` in the subprocess args. See
`llm.py:LLM_MODEL`.

---

## EQ control group is `[EqualizerRack1_[Channel1]_Effect1]`, not `[Channel1]`
**Symptom.** Sending a CC to `[Channel1].filterLow` or `[Channel1].eq_low`
silently no-ops in modern Mixxx.

**Cause.** Mixxx moved EQ controls out of the `[ChannelN]` group into a
named effect rack. The group name is now nested:
`[EqualizerRack1_[ChannelN]_Effect1]` with `parameter1` = low,
`parameter2` = mid, `parameter3` = high.

**Fix.** Use the correct group string in the XML. See
`mixxx.midi.xml` EQ section.

---

## IAC Driver isn't enabled by default on macOS
**Symptom.** `python scripts/send_test_note.py` prints "(no MIDI
ports found)".

**Fix.** Open **Audio MIDI Setup** (Spotlight: "Audio MIDI Setup") →
Window → Show MIDI Studio → double-click **IAC Driver** → check
**"Device is online"** → ensure at least Bus 1 is in the port list →
Apply.

---

## Mixxx Accessibility permission popup is unrelated to our MIDI flow
**Symptom.** When Mixxx launches, macOS shows "Mixxx would like to
control this computer using accessibility features." Scary.

**Fix.** Click **Deny.** We use MIDI, not accessibility. The popup is
for a Mixxx keyboard/global-hotkey feature we don't need.
