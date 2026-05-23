// app.jsx — DeckPilot canvas: Pilot direction (full-width) + Tweaks panel.

const { Pilot } = window;

// Tweakable defaults. Block must be valid JSON; the host rewrites this on save.
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#f08760",
  "serif": "Instrument Serif",
  "theme": "dark"
}/*EDITMODE-END*/;

const ACCENT_SWATCHES = [
  "#f08760", // coral (default)
  "#e8c54f", // amber
  "#9ec98a", // sage
  "#7ea3ff", // electric blue
];

const SERIF_OPTIONS = [
  "Instrument Serif",
  "DM Serif Display",
  "Cormorant Garamond",
  "Newsreader",
];

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);

  return (
    <>
      <DesignCanvas>
        <DCSection
          id="deckpilot"
          title="DeckPilot · companion window for Mixxx"
          subtitle="AI-native direction. Sized as a portrait window to sit beside Mixxx. Watch one full loop to see all states: idle → parsing → ready → running → applied."
        >
          <DCArtboard id="pilot" label="Pilot · AI-native companion" width={920} height={1380}>
            <Pilot tweaks={tweaks} />
          </DCArtboard>
        </DCSection>
      </DesignCanvas>

      <TweaksPanel title="Tweaks">
        <TweakSection label="Appearance">
          <TweakRadio
            label="Theme"
            value={tweaks.theme}
            options={["dark", "light"]}
            onChange={(v) => setTweak("theme", v)}
          />
          <TweakColor
            label="Accent"
            value={tweaks.accent}
            options={ACCENT_SWATCHES}
            onChange={(v) => setTweak("accent", v)}
          />
        </TweakSection>
        <TweakSection label="Typography">
          <TweakSelect
            label="Display serif"
            value={tweaks.serif}
            options={SERIF_OPTIONS}
            onChange={(v) => setTweak("serif", v)}
          />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
