/**
 * useTweaks — user-facing UI customization state.
 *
 * Three knobs the Tweaks panel exposes:
 *   - theme   ("dark" | "light")  → flips data-theme on <html>; CSS vars
 *                                    in theme.css handle the rest
 *   - accent  (hex color)          → rewrites --p-accent + the three
 *                                    derived tokens via color-mix()
 *   - serif   (font family name)   → rewrites --p-serif; affects the
 *                                    italic display headline + the
 *                                    suggestion card track title
 *
 * Persistence: localStorage under DECKPILOT_TWEAKS_KEY. Survives page
 * reloads. No backend involvement; this is purely client preference.
 *
 * Design note: everything in the app uses CSS variables, so the
 * "apply tweaks" effect is just rewriting a handful of `style.setProperty`
 * calls on document.documentElement. Components don't need to know
 * which theme is active — they always read `var(--p-fg)` etc.
 */

import { useCallback, useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';

/** LLM model the parser uses on the LLM path. Sent to the backend
 *  per-request so the user can flip without restarting uvicorn.
 *  Values are passed through to `claude -p --model <value>`. */
export type LLMModel = 'haiku' | 'sonnet' | 'opus';

export interface Tweaks {
  theme: Theme;
  /** Hex color used for the coral-ish accent. */
  accent: string;
  /** Display serif font family name (must be one already loaded in
   *  index.html, otherwise the browser falls back through the chain). */
  serif: string;
  /** Which Claude model the LLM parser invokes. Haiku is fastest +
   *  cheapest (the documented default per D-008). Opus is most
   *  creative for goal-style prompts — pick it for "come up with a
   *  set" or "what should I mix into X". Sonnet is the middle ground. */
  model: LLMModel;
}

/** Presets shown as colored swatches in the Tweaks panel. */
export const ACCENT_PRESETS: { name: string; value: string }[] = [
  { name: 'hot coral', value: '#ff5a2e' },  // saturated default; see DECISIONS UI overhaul
  { name: 'amber', value: '#f0b860' },
  { name: 'emerald', value: '#5ec095' },
  { name: 'indigo', value: '#7c8cf0' },
  { name: 'violet', value: '#b07ce0' },
];

/** Serif families loaded in frontend/index.html. Adding a new entry
 *  here requires also loading the font in index.html, else the radio
 *  option will silently fall back to the next family in the chain. */
export const SERIF_FONTS: string[] = [
  'Instrument Serif',
  'DM Serif Display',
  'Cormorant Garamond',
  'Newsreader',
];

const DEFAULTS: Tweaks = {
  theme: 'dark',
  accent: '#ff5a2e',
  serif: 'Instrument Serif',
  model: 'haiku',
};

/** Display labels + descriptions for the model selector. */
export const MODEL_OPTIONS: { value: LLMModel; label: string; note: string }[] = [
  { value: 'haiku', label: 'Haiku', note: 'fast · ~4s · default' },
  { value: 'sonnet', label: 'Sonnet', note: 'middle · ~8s' },
  { value: 'opus', label: 'Opus', note: 'creative · ~15s' },
];

const STORAGE_KEY = 'deckpilot.tweaks';

/** Hex values that used to be DEFAULTS in older builds. When we find
 *  one of these in persisted state we silently bump to the new default
 *  so existing users get the visual refresh without a manual reset. */
const LEGACY_ACCENTS = ['#f08760'];

function readPersisted(): Tweaks {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = { ...DEFAULTS, ...JSON.parse(raw) };
    // Spread DEFAULTS first so any missing keys fill in safely if we
    // add fields later — forward-compat for older persisted blobs.
    if (LEGACY_ACCENTS.includes(parsed.accent?.toLowerCase?.())) {
      parsed.accent = DEFAULTS.accent;
    }
    return parsed;
  } catch {
    return DEFAULTS;
  }
}

export interface UseTweaksApi {
  tweaks: Tweaks;
  setTheme: (t: Theme) => void;
  setAccent: (a: string) => void;
  setSerif: (s: string) => void;
  setModel: (m: LLMModel) => void;
  reset: () => void;
}

export function useTweaks(): UseTweaksApi {
  const [tweaks, setTweaks] = useState<Tweaks>(readPersisted);

  // Apply tweaks to the document root + persist on every change.
  // Putting both side-effects in one effect keeps them in lockstep —
  // the saved blob always matches what the user sees.
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-theme', tweaks.theme);

    root.style.setProperty('--p-accent', tweaks.accent);
    root.style.setProperty(
      '--p-accent-dim',
      `color-mix(in srgb, ${tweaks.accent} 16%, transparent)`,
    );
    root.style.setProperty(
      '--p-accent-edge',
      `color-mix(in srgb, ${tweaks.accent} 38%, transparent)`,
    );
    root.style.setProperty(
      '--p-accent-ink',
      // Ink (foreground on accent buttons) needs enough contrast on
      // both light and dark — same formula as the design's
      // buildPilotVars, which mixes the accent with a deep neutral.
      `color-mix(in srgb, ${tweaks.accent} 22%, #0a0805 86%)`,
    );

    root.style.setProperty(
      '--p-serif',
      `'${tweaks.serif}', 'Times New Roman', Georgia, serif`,
    );

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tweaks));
    } catch {
      // Storage full / Safari private mode / etc. — preferences just
      // don't survive the session. Not worth surfacing to the user.
    }
  }, [tweaks]);

  const setTheme = useCallback(
    (theme: Theme) => setTweaks((prev) => ({ ...prev, theme })),
    [],
  );
  const setAccent = useCallback(
    (accent: string) => setTweaks((prev) => ({ ...prev, accent })),
    [],
  );
  const setSerif = useCallback(
    (serif: string) => setTweaks((prev) => ({ ...prev, serif })),
    [],
  );
  const setModel = useCallback(
    (model: LLMModel) => setTweaks((prev) => ({ ...prev, model })),
    [],
  );
  const reset = useCallback(() => setTweaks(DEFAULTS), []);

  return { tweaks, setTheme, setAccent, setSerif, setModel, reset };
}
