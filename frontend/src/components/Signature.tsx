/**
 * Signature — syntax-highlighted rendering of a function-call style
 * string like `transport.play(deck:1)` or `swap.bass(deck:1 → deck:2, t:4s)`.
 *
 * Designed for parsed-action labels (PlanStep.fn, AgentRow.signature,
 * CommandCard's parsed pill). Mirrors a REPL prompt's vibe — function
 * name in foreground, params muted, literal values highlighted.
 *
 * Strudel-style aesthetic: monospace everywhere, color carries meaning.
 * Falls back to a plain monospace render for strings that don't match
 * the `name(args)` shape — keeps it safe for labels like "noop" or
 * "(suggestion)" that go through the same component.
 */

import type { CSSProperties } from 'react';

interface SignatureProps {
  text: string;
  /** Size in px. Default 14 to match PlanStep.fn. */
  size?: number;
  /** Override the foreground color of the function name. Used to
   *  dim pending plan steps vs. running/done ones. */
  fgColor?: string;
  style?: CSSProperties;
}

const PARSE_RE = /^([\w.]+)\(([^)]*)\)\s*$/;

export function Signature({ text, size = 14, fgColor, style }: SignatureProps) {
  const baseStyle: CSSProperties = {
    font: `500 ${size}px/1.2 var(--p-mono)`,
    color: fgColor ?? 'var(--p-fg)',
    letterSpacing: '0',
    ...style,
  };

  const match = PARSE_RE.exec(text);
  if (!match) {
    // Not a name(args) shape — render plain. Covers things like "noop",
    // "(suggestion)", and any future signature shape we haven't covered.
    return <span style={baseStyle}>{text}</span>;
  }

  const [, fnName, argsRaw] = match;
  const punctStyle: CSSProperties = { color: 'var(--p-muted-deep)' };
  const keyStyle: CSSProperties = { color: 'var(--p-muted)' };
  const valStyle: CSSProperties = { color: 'var(--p-live)' };

  // Tokenise the args section. Split on `, ` first; each token is
  // either `key:value` (most common) or a free-floating value
  // (e.g. "deck:1 → deck:2" inside one arg). The arrow stays attached
  // to its value-bearing token.
  const argTokens = argsRaw.length > 0 ? argsRaw.split(/,\s*/) : [];

  return (
    <span style={baseStyle}>
      <span>{fnName}</span>
      <span style={punctStyle}>(</span>
      {argTokens.map((arg, i) => {
        const colonIdx = arg.indexOf(':');
        const isLast = i === argTokens.length - 1;
        if (colonIdx === -1) {
          return (
            <span key={i}>
              <span style={valStyle}>{arg}</span>
              {!isLast && <span style={punctStyle}>, </span>}
            </span>
          );
        }
        const key = arg.slice(0, colonIdx);
        const value = arg.slice(colonIdx + 1);
        return (
          <span key={i}>
            <span style={keyStyle}>{key}</span>
            <span style={punctStyle}>:</span>
            <span style={valStyle}>{value}</span>
            {!isLast && <span style={punctStyle}>, </span>}
          </span>
        );
      })}
      <span style={punctStyle}>)</span>
    </span>
  );
}
