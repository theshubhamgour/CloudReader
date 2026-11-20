// Small app-style tiles for external links. The GitHub mark is from Simple Icons (CC0).
const Tile = ({ bg, children, size }: { bg: string; children: React.ReactNode; size: number }) => (
  <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden className="shrink-0">
    <rect width="32" height="32" rx="7.5" fill={bg} />
    <g transform="translate(4 4)">{children}</g>
  </svg>
);

export function YouTubeTile({ size = 30 }: { size?: number }) {
  return (
    <Tile bg="#FF0033" size={size}>
      <rect x="1" y="4.5" width="22" height="15" rx="4.5" fill="#fff" />
      <path d="M9.75 8.6v6.8l5.9-3.4z" fill="#FF0033" />
    </Tile>
  );
}

export function LinkedInTile({ size = 30 }: { size?: number }) {
  return (
    <Tile bg="#0A66C2" size={size}>
      <g fill="#fff">
        <circle cx="6.4" cy="6.2" r="1.9" />
        <rect x="4.8" y="9.4" width="3.2" height="9.6" rx="0.4" />
        <path d="M10.4 9.4h3v1.35c.55-.95 1.7-1.6 3.15-1.6 2.6 0 3.55 1.65 3.55 4.35V19h-3.15v-4.8c0-1.25-.35-2.15-1.55-2.15s-1.85.9-1.85 2.15V19h-3.15z" />
      </g>
    </Tile>
  );
}

export function GitHubTile({ size = 30 }: { size?: number }) {
  return (
    <Tile bg="#24292F" size={size}>
      <path transform="translate(1 1) scale(0.9167)" fill="#fff" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </Tile>
  );
}

export function HeartTile({ size = 30 }: { size?: number }) {
  return (
    <Tile bg="#FF2D55" size={size}>
      <path fill="#fff" d="M12 20.3s-7.6-4.6-7.6-10.1A4.3 4.3 0 0 1 12 7.6a4.3 4.3 0 0 1 7.6 2.6c0 5.5-7.6 10.1-7.6 10.1z" />
    </Tile>
  );
}
