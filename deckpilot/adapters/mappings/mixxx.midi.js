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

// Suppress re-sends when the scaled BPM didn't actually change — Mixxx fires
// the callback on every beatgrid tick which would spam the wire. We keep the
// last CC value sent per deck and skip duplicates.
DeckPilot._lastBpmCc = { "[Channel1]": -1, "[Channel2]": -1 };
DeckPilot._connections = [];

DeckPilot._sendBpm = function(group, bpm) {
    // BPM = 0 means no track loaded (or pre-analysis). Skip rather than
    // emitting a misleading 0-CC value.
    if (!bpm || bpm <= 0) return;
    var clamped = Math.max(BPM_MIN, Math.min(BPM_MAX, bpm));
    var ccValue = Math.round((clamped - BPM_MIN) / (BPM_MAX - BPM_MIN) * 127);
    if (ccValue === DeckPilot._lastBpmCc[group]) return;
    DeckPilot._lastBpmCc[group] = ccValue;
    midi.sendShortMsg(0xB0, BPM_CC[group], ccValue);
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
        var conn = engine.makeConnection(group, "file_bpm", function(value) {
            DeckPilot._sendBpm(group, value);
        });
        // engine.makeConnection returns null if the control doesn't exist;
        // guard so a typo or Mixxx-version skew doesn't crash init.
        if (conn) DeckPilot._connections.push(conn);
    });
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
