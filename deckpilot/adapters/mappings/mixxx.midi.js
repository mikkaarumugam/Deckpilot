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

// Required Mixxx lifecycle hooks. Empty for us — we have no LEDs to light
// up, no state to initialize.
DeckPilot.init = function(id, debug) {};
DeckPilot.shutdown = function() {};

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
