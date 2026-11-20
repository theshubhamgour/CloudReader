import { useId } from "react";

/** CloudReader's mark: a cloud with a sound wave, on a rounded blue tile. Original artwork. */
export function Logo({ size = 28, className }: { size?: number; className?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} role="img" aria-label="CloudReader logo">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#5AC8FA" />
          <stop offset="1" stopColor="#0A6CFF" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14.5" fill={`url(#${id})`} />
      <g transform="translate(-1.5 1.5)" fill="#fff">
        <circle cx="24" cy="36" r="10" />
        <circle cx="34.5" cy="28" r="13" />
        <circle cx="44" cy="37" r="9" />
        <rect x="24" y="30" width="20" height="16" />
      </g>
      <g stroke="#0A6CFF" strokeWidth="2.8" strokeLinecap="round">
        <line x1="23" y1="34" x2="23" y2="38" />
        <line x1="27.5" y1="31" x2="27.5" y2="41" />
        <line x1="32" y1="28" x2="32" y2="44" />
        <line x1="36.5" y1="31" x2="36.5" y2="41" />
        <line x1="41" y1="34" x2="41" y2="38" />
      </g>
    </svg>
  );
}
