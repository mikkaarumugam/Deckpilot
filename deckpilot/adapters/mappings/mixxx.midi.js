// DeckPilot — Mixxx controller script.
//
// Why this file exists:
// Mixxx's pure-XML <normal/> binding can't distinguish "play" from "pause"
// using one note because MIDI's "note_on velocity 0" is spec-equivalent to
// note_off and gets dropped before our binding sees it. So we use TWO
// different notes (one for play, one for pause) and a tiny script to call
// engine.setValue() with the exact value we want.
//
// This is the canonical Mixxx approach for "set this control to this exact
// value." Real-world hardware mappings (Pioneer, Native Instruments) ship
// with much larger versions of this file.

var DeckPilot = {};

// --- BPM output -------------------------------------------------------------
//
// Mixxx's standard <output> XML element is great for binary state (play/pause
// → note on/off) but can't scale a continuous float like BPM into a CC byte.
// For that we use scripted output: engine.makeConnection subscribes to a
// control; the callback fires whenever it changes; we scale and send a CC.
//
// Wire format (Mixxx → Python listener):
//   - CC 0x30 on status 0xB0 = deck 1 BPM
//   - CC 0x31 on status 0xB0 = deck 2 BPM
//   - Value 0..127 scaled across the BPM_MIN..BPM_MAX range.
//
// Decoded on the Python side in deckpilot/adapters/midi_feedback.py — the
// two constants below MUST match that file (it inverts the scaling).

var BPM_MIN = 60.0;
var BPM_MAX = 200.0;
var BPM_CC = { "[Channel1]": 0x30, "[Channel2]": 0x31 };

// --- Playhead position output ----------------------------------------------
//
// `playposition` is a continuous control from 0.0 (start of track) to 1.0
// (end). Mixxx fires the callback at ~audio-frame rate while a track is
// playing — way faster than we need. We scale to 7-bit CC (128 values) and
// suppress re-sends so the wire only carries actual position changes.
//
// At 128 CC values for a 4-minute track, granularity is ~2s per CC step.
// The frontend interpolates via a CSS transition so the bar fills smoothly
// between updates.
//
// Wire format (Mixxx → Python listener):
//   - CC 0x32 on status 0xB0 = deck 1 position
//   - CC 0x33 on status 0xB0 = deck 2 position
//   - Value 0..127 scaled linearly from 0.0..1.0
var POSITION_CC = { "[Channel1]": 0x32, "[Channel2]": 0x33 };

// --- Active loop size output ----------------------------------------------
//
// Lets Python's regex parser know which loop size (if any) is currently
// active on each deck, so "stop loop" can fire the matching toggle instead
// of always guessing 8. Without this read-back the regex layer is state-
// blind and would replace a 4-beat loop with an 8-beat one on "stop loop".
//
// Wire format:
//   - CC 0x38 (status 0xB0) = deck 1 active loop size
//   - CC 0x39 (status 0xB0) = deck 2 active loop size
//   - Value: 0 = no loop, else one of {1, 2, 4, 8, 16, 32} (beats)
//
// One CC per deck instead of one per (deck, size) keeps the wire compact
// — Mixxx will never have two beatloop sizes active simultaneously on a
// deck (a new toggle replaces the existing loop).
var LOOP_SIZE_CC = { "[Channel1]": 0x38, "[Channel2]": 0x39 };
var LOOP_SIZES = [1, 2, 4, 8, 16, 32];

// --- Beat tick output ------------------------------------------------------
//
// Lets the Tier-3 agent layer fire on "in N beats, do Y" triggers. Mixxx
// exposes `beat_active` per channel — a 0/1 flag that pulses to 1 briefly
// (~20ms) at each beat. We subscribe, watch the rising edge, and send ONE
// note_on per beat. The Python side just increments a counter on receive,
// no scaling / no wrap-around to worry about.
//
// Wire format (Mixxx → Python listener):
//   - note 0x12 on status 0x90, velocity 0x7F = deck 1 beat tick
//   - note 0x13 on status 0x90, velocity 0x7F = deck 2 beat tick
//
// Adjacent to play-state notes 0x10/0x11; same band so wire-sniffing is
// easy.
var BEAT_NOTE = { "[Channel1]": 0x12, "[Channel2]": 0x13 };

// Rising-edge tracker. `beat_active` callback fires for both the 0→1 and
// 1→0 transitions; only the first one is a beat. Without this we'd emit
// two ticks per beat and the agent would fire half as many beats late
// as it should.
DeckPilot._lastBeatActive = { "[Channel1]": 0, "[Channel2]": 0 };

DeckPilot._sendBeatTick = function(group, value) {
    var prev = DeckPilot._lastBeatActive[group];
    DeckPilot._lastBeatActive[group] = value > 0 ? 1 : 0;
    if (prev === 0 && value > 0) {
        midi.sendShortMsg(0x90, BEAT_NOTE[group], 0x7F);
    }
};

// Suppress re-sends when the scaled BPM didn't actually change — Mixxx fires
// the callback on every beatgrid tick which would spam the wire. We keep the
// last CC value sent per deck and skip duplicates. Same trick for position.
DeckPilot._lastBpmCc = { "[Channel1]": -1, "[Channel2]": -1 };
DeckPilot._lastPositionCc = { "[Channel1]": -1, "[Channel2]": -1 };
DeckPilot._lastLoopSizeCc = { "[Channel1]": -1, "[Channel2]": -1 };
DeckPilot._connections = [];

DeckPilot._sendBpm = function(group, bpm) {
    // CC value 0 is reserved as the "no track / unknown BPM" sentinel
    // so Python can clear the deck card when a track unloads. Real BPM
    // values get encoded into CC 1..127 (i.e. one fewer step than
    // 0..127). The lost precision is ~1 BPM at the extremes — well
    // below the ±0.6 matching tolerance, so it doesn't affect library
    // lookups.
    var ccValue;
    if (!bpm || bpm <= 0) {
        ccValue = 0;
    } else {
        var clamped = Math.max(BPM_MIN, Math.min(BPM_MAX, bpm));
        ccValue = Math.max(1, Math.round((clamped - BPM_MIN) / (BPM_MAX - BPM_MIN) * 127));
    }
    if (ccValue === DeckPilot._lastBpmCc[group]) return;
    DeckPilot._lastBpmCc[group] = ccValue;
    midi.sendShortMsg(0xB0, BPM_CC[group], ccValue);
};

DeckPilot._sendLoopSize = function(group) {
    // Walk the candidate sizes; the first one whose `beatloop_X_enabled`
    // is non-zero is the active size. Mixxx invariant: at most one is on.
    var active = 0;
    for (var i = 0; i < LOOP_SIZES.length; i++) {
        var size = LOOP_SIZES[i];
        if (engine.getValue(group, "beatloop_" + size + "_enabled") > 0) {
            active = size;
            break;
        }
    }
    if (active === DeckPilot._lastLoopSizeCc[group]) return;
    DeckPilot._lastLoopSizeCc[group] = active;
    midi.sendShortMsg(0xB0, LOOP_SIZE_CC[group], active);
};

DeckPilot._sendPosition = function(group, pos) {
    // pos is 0.0..1.0; clamp + scale to 7-bit CC.
    if (pos === undefined || pos === null) return;
    var clamped = Math.max(0, Math.min(1, pos));
    var ccValue = Math.round(clamped * 127);
    if (ccValue === DeckPilot._lastPositionCc[group]) return;
    DeckPilot._lastPositionCc[group] = ccValue;
    midi.sendShortMsg(0xB0, POSITION_CC[group], ccValue);
};

// Required Mixxx lifecycle hooks. On init we subscribe to each deck's BPM
// and arrange to disconnect on shutdown so Mixxx doesn't leak connections
// across mapping reloads.
DeckPilot.init = function(id, debug) {
    // We subscribe to file_bpm rather than bpm. file_bpm is the canonical
    // BPM stored in the track metadata — matches what's in the Mixxx
    // SQLite library DB. The plain "bpm" control is the *live* playback
    // BPM, which drifts with pitch nudges and (more importantly) returns
    // a nonzero estimate even for tracks Mixxx hasn't analysed yet —
    // breaking the library lookup. file_bpm is 0 for un-analysed tracks,
    // which is honest: we genuinely don't know.
    ["[Channel1]", "[Channel2]"].forEach(function(group) {
        var bpmConn = engine.makeConnection(group, "file_bpm", function(value) {
            DeckPilot._sendBpm(group, value);
        });
        // engine.makeConnection returns null if the control doesn't exist;
        // guard so a typo or Mixxx-version skew doesn't crash init.
        if (bpmConn) DeckPilot._connections.push(bpmConn);

        var posConn = engine.makeConnection(group, "playposition", function(value) {
            DeckPilot._sendPosition(group, value);
        });
        if (posConn) DeckPilot._connections.push(posConn);

        // Subscribe to every candidate loop size's _enabled flag. Whenever
        // any of them flips, recompute and emit the per-deck active size.
        // Closure captures `group` so the right deck CC fires.
        LOOP_SIZES.forEach(function(size) {
            var key = "beatloop_" + size + "_enabled";
            var conn = engine.makeConnection(group, key, function() {
                DeckPilot._sendLoopSize(group);
            });
            if (conn) DeckPilot._connections.push(conn);
        });

        // Beat ticks for the Tier-3 agent layer's after_beats trigger.
        var beatConn = engine.makeConnection(group, "beat_active", function(value) {
            DeckPilot._sendBeatTick(group, value);
        });
        if (beatConn) DeckPilot._connections.push(beatConn);
    });

    // Proactively emit current state on init. Otherwise cycling the
    // Mixxx controller (Preferences → toggle Enabled) re-runs init() →
    // re-subscribes → but the subscribed values don't refire until they
    // change, leaving Python with whatever stale state it last saw
    // before the cycle. Most painful symptom: ejected decks keep
    // showing the old track on DeckPilot's deck card forever. By
    // broadcasting state on every init, the cycle becomes the proper
    // "resync" gesture users expect.
    DeckPilot._broadcastState();
};

DeckPilot.shutdown = function() {
    DeckPilot._connections.forEach(function(c) { c.disconnect(); });
    DeckPilot._connections = [];
};

// Request-state handshake. Python's MixxxFeedback sends note 0x7F on
// startup; this re-broadcasts current play state + BPM for both decks
// so the listener doesn't have to wait for the next user-driven change.
//
// Play state can't be re-triggered via the standard <output> binding
// (Mixxx owns that side), so we emit the same wire format directly via
// midi.sendShortMsg. BPM rebroadcasts go through _sendBpm with the
// per-deck de-dup cache reset so the value passes through.
DeckPilot._broadcastState = function() {
    ["[Channel1]", "[Channel2]"].forEach(function(group) {
        var playing = engine.getValue(group, "play") > 0;
        var note = (group === "[Channel1]") ? 0x10 : 0x11;
        midi.sendShortMsg(0x90, note, playing ? 0x7F : 0x00);

        DeckPilot._lastBpmCc[group] = -1;
        DeckPilot._sendBpm(group, engine.getValue(group, "file_bpm"));

        DeckPilot._lastPositionCc[group] = -1;
        DeckPilot._sendPosition(group, engine.getValue(group, "playposition"));

        DeckPilot._lastLoopSizeCc[group] = -1;
        DeckPilot._sendLoopSize(group);
    });
};

DeckPilot.requestState = function(channel, control, value, status, group) {
    if (value > 0) DeckPilot._broadcastState();
};

// Handler signature is (channel, control, value, status, group).
//   value  = velocity (for note messages) or CC value
//   status = full MIDI status byte
//   group  = the <group> from the XML binding, e.g. "[Channel1]"
//
// We only act when value > 0 (the press) and ignore the release. The Python
// adapter only ever sends a press, but this guards against unexpected resets.

// --- Pitch (bipolar CC → ±1.0 rate) ---------------------------------------
//
// Mixxx's `rate` is -1..+1 (full pitch range, default ±8%). MIDI CC is 0..127.
// We center on 64 — CC 64 → rate 0.0 (no pitch shift). Below 64 = pitch down,
// above 64 = pitch up. Both halves use 63 steps so the scaling is symmetric.

DeckPilot._setRate = function(group, value) {
    var rate = (value - 64) / 63;
    if (rate < -1) rate = -1;
    if (rate > 1)  rate = 1;
    engine.setValue(group, "rate", rate);
};

DeckPilot.setPitch1 = function(channel, control, value, status, group) {
    DeckPilot._setRate("[Channel1]", value);
};

DeckPilot.setPitch2 = function(channel, control, value, status, group) {
    DeckPilot._setRate("[Channel2]", value);
};

// --- FX wet (per-deck assignment + per-unit mix) --------------------------
//
// Mixxx's effect-unit `mix` knob is global per unit; the per-deck "wet"
// effect is achieved by toggling the unit's group_[ChannelN]_enable
// assignment. Sending CC 0 disables the assignment (deck is dry on this
// unit) without disturbing the unit mix; sending >0 enables the assignment
// AND sets the unit mix. Trade-off: two decks routed to the same unit
// share the unit mix — documented in D-022.

DeckPilot._setFx = function(unitGroup, channelKey, value) {
    if (value <= 0) {
        engine.setValue(unitGroup, channelKey, 0);
        return;
    }
    engine.setValue(unitGroup, channelKey, 1);
    engine.setValue(unitGroup, "mix", value / 127);
};

DeckPilot.setFxDeck1Unit1 = function(channel, control, value) {
    DeckPilot._setFx("[EffectRack1_EffectUnit1]", "group_[Channel1]_enable", value);
};

DeckPilot.setFxDeck1Unit2 = function(channel, control, value) {
    DeckPilot._setFx("[EffectRack1_EffectUnit2]", "group_[Channel1]_enable", value);
};

DeckPilot.setFxDeck2Unit1 = function(channel, control, value) {
    DeckPilot._setFx("[EffectRack1_EffectUnit1]", "group_[Channel2]_enable", value);
};

DeckPilot.setFxDeck2Unit2 = function(channel, control, value) {
    DeckPilot._setFx("[EffectRack1_EffectUnit2]", "group_[Channel2]_enable", value);
};

DeckPilot.playDeck1 = function(channel, control, value, status, group) {
    if (value > 0) engine.setValue("[Channel1]", "play", 1);
};

DeckPilot.pauseDeck1 = function(channel, control, value, status, group) {
    if (value > 0) engine.setValue("[Channel1]", "play", 0);
};

DeckPilot.playDeck2 = function(channel, control, value, status, group) {
    if (value > 0) engine.setValue("[Channel2]", "play", 1);
};

DeckPilot.pauseDeck2 = function(channel, control, value, status, group) {
    if (value > 0) engine.setValue("[Channel2]", "play", 0);
};
