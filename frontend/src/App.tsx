/**
 * Phase 1 placeholder. Confirms the design tokens + fonts load correctly.
 *
 * Replaced in Phase 2 by the real <Pilot /> shell once components are ported.
 * Keep this file lean — it's just the outermost mount point and any
 * top-level providers we end up needing later (theme context, query client).
 */
export default function App() {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '4rem',
        gap: '1.5rem',
      }}
    >
      {/* Phase 1 sanity card — verifies every font + token resolves. Delete
          when Phase 2 lands the real component. */}
      <div
        style={{
          background: 'var(--p-surface)',
          border: '1px solid var(--p-border-strong)',
          borderRadius: 18,
          padding: '32px 40px',
          maxWidth: 640,
          animation: 'pilotGlow 4s ease-in-out infinite',
        }}
      >
        <div
          style={{
            font: '500 10px/1 var(--p-mono)',
            color: 'var(--p-muted)',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            marginBottom: 14,
          }}
        >
          <span style={{ color: 'var(--p-accent)' }}>✱</span> Phase 1 · scaffold ready
        </div>
        <div
          style={{
            font: 'italic 400 28px/1.2 var(--p-serif)',
            color: 'var(--p-fg)',
            letterSpacing: '-0.01em',
            marginBottom: 12,
          }}
        >
          DeckPilot
        </div>
        <div
          style={{
            font: '400 14px/1.5 var(--p-sans)',
            color: 'var(--p-fg-dim)',
            marginBottom: 18,
          }}
        >
          Vite + React + TypeScript scaffold with design tokens, fonts, and
          keyframes loaded. Next phase: port the real components from{' '}
          <code
            style={{
              font: '500 12px/1 var(--p-mono)',
              color: 'var(--p-accent)',
              background: 'var(--p-accent-dim)',
              border: '1px solid var(--p-accent-edge)',
              padding: '2px 6px',
              borderRadius: 4,
            }}
          >
            design/pilot.jsx
          </code>
          .
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="pilot-btn-primary pilot-btn-glow">
            <span>Run</span>
            <span className="pilot-btn-kbd">⏎</span>
          </button>
          <button className="pilot-btn-secondary">
            <span>Queue</span>
            <span style={{ font: '500 10px/1 var(--p-mono)', color: 'var(--p-muted)' }}>⌘⏎</span>
          </button>
        </div>
      </div>
    </div>
  );
}
