/**
 * TweaksPanel — runtime UI customization (theme / accent / serif font).
 *
 * Lives bottom-right, glass-styled (backdrop-filter blur). Inspired by
 * the Claude Design "Tweaks" panel (`design/tweaks-panel.jsx`) but
 * trimmed to ~150 lines vs the original 530 — we don't need the
 * postMessage protocol that the design tool used to communicate with
 * the host. This is just three knobs persisted to localStorage.
 *
 * Why a separate component: keeps the styling churn isolated from
 * Pilot.tsx and prevents the inline-style approach used elsewhere
 * from leaking out. All visuals use the same --p-* CSS variables as
 * the rest of the app, so the panel itself respects the theme it
 * controls (clean dogfood).
 */

import {
  ACCENT_PRESETS,
  MODEL_OPTIONS,
  SERIF_FONTS,
  type LLMModel,
  type Theme,
  type UseTweaksApi,
} from '../hooks/useTweaks';

interface TweaksPanelProps {
  api: UseTweaksApi;
  /** Optional close handler — when present, an × button renders in
   *  the header that calls this. Lifted up so the parent owns whether
   *  the panel is visible at all (vs the panel managing its own
   *  open/closed). */
  onClose?: () => void;
}

export function TweaksPanel({ api, onClose }: TweaksPanelProps) {
  const { tweaks, setTheme, setAccent, setSerif, setModel, reset } = api;

  return (
    <div
      style={{
        position: 'fixed',
        right: 16,
        bottom: 16,
        zIndex: 1000,
        width: 260,
        background: 'var(--p-surface)',
        border: '1px solid var(--p-border-strong)',
        borderRadius: 14,
        boxShadow: '0 12px 40px rgba(0, 0, 0, 0.25)',
        backdropFilter: 'blur(20px) saturate(160%)',
        WebkitBackdropFilter: 'blur(20px) saturate(160%)',
        font: '400 12px/1.4 var(--p-sans)',
        color: 'var(--p-fg)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '11px 12px 11px 14px',
          borderBottom: '1px solid var(--p-border)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            font: '500 10.5px/1 var(--p-mono)',
            color: 'var(--p-muted)',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
          }}
        >
          <span style={{ color: 'var(--p-accent)' }}>✱</span>
          <span>Tweaks</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            onClick={reset}
            title="Reset to defaults"
            style={{
              background: 'transparent',
              border: 0,
              color: 'var(--p-muted)',
              font: '400 11px/1 var(--p-mono)',
              cursor: 'pointer',
              padding: '4px 6px',
              borderRadius: 4,
            }}
          >
            reset
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Close"
              style={{
                background: 'transparent',
                border: 0,
                color: 'var(--p-muted)',
                font: '500 14px/1 var(--p-sans)',
                cursor: 'pointer',
                width: 22,
                height: 22,
                borderRadius: 5,
              }}
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div
        style={{
          padding: '12px 14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <Section label="Theme">
          <SegmentedTheme value={tweaks.theme} onChange={setTheme} />
        </Section>

        <Section label="Accent">
          <SwatchRow value={tweaks.accent} onChange={setAccent} />
        </Section>

        <Section label="Serif font">
          <SerifList value={tweaks.serif} onChange={setSerif} />
        </Section>

        <Section label="LLM model">
          <ModelList value={tweaks.model} onChange={setModel} />
        </Section>
      </div>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div
        style={{
          font: '500 9.5px/1 var(--p-mono)',
          color: 'var(--p-muted)',
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function SegmentedTheme({
  value,
  onChange,
}: {
  value: Theme;
  onChange: (t: Theme) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        padding: 2,
        background: 'var(--p-bg)',
        border: '1px solid var(--p-border)',
        borderRadius: 8,
      }}
    >
      {(['dark', 'light'] as Theme[]).map((opt) => {
        const active = value === opt;
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            style={{
              flex: 1,
              padding: '6px 8px',
              border: 0,
              borderRadius: 6,
              background: active ? 'var(--p-surface-hi)' : 'transparent',
              color: active ? 'var(--p-fg)' : 'var(--p-muted)',
              font: '500 11.5px/1 var(--p-sans)',
              cursor: 'pointer',
              textTransform: 'capitalize',
              transition: 'background 0.15s, color 0.15s',
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

function SwatchRow({
  value,
  onChange,
}: {
  value: string;
  onChange: (hex: string) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {ACCENT_PRESETS.map((p) => {
        const active = value.toLowerCase() === p.value.toLowerCase();
        return (
          <button
            key={p.value}
            type="button"
            onClick={() => onChange(p.value)}
            title={p.name}
            style={{
              width: 22,
              height: 22,
              borderRadius: 99,
              border: active
                ? '2px solid var(--p-fg)'
                : '1px solid var(--p-border-strong)',
              background: p.value,
              cursor: 'pointer',
              padding: 0,
              boxShadow: active ? '0 0 0 2px var(--p-bg)' : 'none',
              transition: 'transform 0.1s',
            }}
          />
        );
      })}
    </div>
  );
}

function SerifList({
  value,
  onChange,
}: {
  value: string;
  onChange: (font: string) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {SERIF_FONTS.map((font) => {
        const active = value === font;
        return (
          <button
            key={font}
            type="button"
            onClick={() => onChange(font)}
            style={{
              padding: '6px 10px',
              border: '1px solid var(--p-border)',
              background: active
                ? 'var(--p-accent-dim)'
                : 'var(--p-bg)',
              borderColor: active ? 'var(--p-accent-edge)' : 'var(--p-border)',
              borderRadius: 7,
              color: 'var(--p-fg)',
              // Preview the font *in* the button — clicking is comparing
              // typefaces, not reading text. Italic mirrors how the
              // headline + suggestion title actually render.
              font: `italic 400 16px/1.1 '${font}', 'Times New Roman', serif`,
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 0.15s, border-color 0.15s',
            }}
          >
            {font}
          </button>
        );
      })}
    </div>
  );
}

function ModelList({
  value,
  onChange,
}: {
  value: LLMModel;
  onChange: (m: LLMModel) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {MODEL_OPTIONS.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            style={{
              padding: '6px 10px',
              border: '1px solid var(--p-border)',
              background: active ? 'var(--p-accent-dim)' : 'var(--p-bg)',
              borderColor: active ? 'var(--p-accent-edge)' : 'var(--p-border)',
              borderRadius: 7,
              color: 'var(--p-fg)',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 0.15s, border-color 0.15s',
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              gap: 10,
            }}
          >
            <span style={{ font: '500 13px/1.1 var(--p-mono)' }}>{opt.label}</span>
            <span
              style={{
                font: '400 10.5px/1.1 var(--p-mono)',
                color: 'var(--p-muted)',
              }}
            >
              {opt.note}
            </span>
          </button>
        );
      })}
    </div>
  );
}
