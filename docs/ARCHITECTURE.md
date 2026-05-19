# Architecture

## The pipeline

```
   CLI text  ──▶  parser  ──▶  DJAction  ──▶  MidiAdapter  ──▶  IAC  ──▶  VirtualDJ
                 (LLM +                       (mapping.json)
                  regex)
```

Four moving parts:

1. **CLI** — collects the user's English command.
2. **Parser** — turns English into a structured `DJAction`. Two implementations:
   - Regex parser for the 3–4 most common phrasings. Fast, free, deterministic.
   - LLM parser (Claude Haiku) for everything else. Slower (~1–3s) but flexible.
3. **`DJAction`** — a frozen dataclass with one field per parameter (e.g. `FadeToDeck(deck=2, seconds=8.0)`). This is the **contract** between parsing and execution.
4. **Adapter** — turns a `DJAction` into MIDI events sent through macOS's IAC Driver into VirtualDJ. VirtualDJ has been MIDI-Learned to respond to specific notes and CCs (see `adapters/mappings/virtualdj.json`).

## Why this shape

### Why a structured action schema instead of "let the LLM run the show"?

An LLM that emits raw MIDI bytes would be (a) impossible to test, (b) impossible to safely constrain, and (c) impossible to swap for a different DJ app. By forcing the LLM to emit one of 6 well-defined actions:

- **Tests don't need VirtualDJ running.** The parser can be evaluated in isolation.
- **The LLM can't ask for unsupported things.** If it tries to invent `set_master_volume`, we reject it.
- **The action layer is portable.** Swapping VirtualDJ for Mixxx is "write a new adapter," not "rewrite the LLM prompt."

This pattern — *LLM produces structured intent, deterministic code executes it* — is the dominant architecture for production AI products. See: function calling, tool use, agent action spaces.

### Why regex AND LLM, not just LLM?

- The 5 most-common commands (play, pause, basic fade) make up ~70% of usage.
- A regex matches them in microseconds. Claude takes 1–3 seconds.
- The user experience of "play deck 1" should be instant. Regex catches it.
- For everything else (paraphrases, multi-action commands, unusual phrasings), the LLM is the safety net.

### Why an adapter layer?

The action schema is the same regardless of DJ software. The MIDI mapping is not. Today: VirtualDJ. Tomorrow: Mixxx, Serato, hardware controllers. Each is a new adapter implementing `dispatch(action)`. Nothing else moves.

## The 6 actions (v0.1)

See `deckpilot/core/actions.py` for the source of truth. Summary:

| Action            | Fields                       | What it does                                      |
|-------------------|------------------------------|---------------------------------------------------|
| `PlayDeck`        | `deck: int`                  | Start playback on deck N.                         |
| `PauseDeck`       | `deck: int`                  | Pause deck N.                                     |
| `SetCrossfader`   | `value: float (0.0–1.0)`     | Set crossfader position.                          |
| `FadeToDeck`      | `deck: int, seconds: float`  | Interpolate crossfader to deck N over M seconds.  |
| `LoopDeck`        | `deck: int, beats: int`      | Trigger an N-beat loop on deck N.                 |
| `NudgeDeck`       | `deck: int, direction`       | Small tempo nudge forward/back.                   |

## What's intentionally absent

- **No state read-back.** We don't ask VirtualDJ what BPM is playing. The action layer is fire-and-forget. State-aware actions ("loop the next 8 beats *from now*") would need the VirtualDJ Pro HTTP API.
- **No multi-action plans.** The LLM emits one action per call. "Do a bass-swap transition" would need a planner that produces an ordered list of actions.
- **No undo.** Real DJs would demand it; v0.1 doesn't have it.

All three are listed in the README's "What's next."
