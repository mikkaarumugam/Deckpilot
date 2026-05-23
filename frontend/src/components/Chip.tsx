/**
 * Chip — rounded suggestion button with an optional keyboard hint.
 *
 * Used in the "Try" row beneath the hero card. Click handler is wired up
 * in Phase 4 (currently no-op; just visual).
 *
 * Styles for `.pilot-chip` + `.pilot-chip-kbd` live in styles/theme.css so
 * hover/active feel is consistent without re-defining transitions per render.
 */

import { type ReactNode } from 'react';

interface ChipProps {
  children: ReactNode;
  kbd?: string;
  onClick?: () => void;
}

export function Chip({ children, kbd, onClick }: ChipProps) {
  return (
    <button className="pilot-chip" onClick={onClick} type="button">
      <span>{children}</span>
      {kbd && <span className="pilot-chip-kbd">{kbd}</span>}
    </button>
  );
}
