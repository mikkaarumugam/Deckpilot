/**
 * BPMPulse — a single dot that pulses at the track's BPM.
 *
 * Pure visual flair: the period is computed from BPM (60 / BPM seconds per
 * beat) so the pulse animation matches what the deck is actually playing.
 * `color` is passed as a CSS color value (typically a var(--p-*) ref) so the
 * pulse re-tints if the theme changes.
 *
 * The keyframe `pilotPulse` lives in styles/theme.css.
 */

interface BPMPulseProps {
  bpm: number;
  color: string;
  size?: number;
}

export function BPMPulse({ bpm, color, size = 6 }: BPMPulseProps) {
  const period = 60 / bpm;
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: 99,
        background: color,
        boxShadow: `0 0 12px ${color}`,
        animation: `pilotPulse ${period}s ease-in-out infinite`,
      }}
    />
  );
}
