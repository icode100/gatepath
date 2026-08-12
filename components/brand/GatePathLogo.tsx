type GatePathLogoProps = {
  className?: string;
  title?: string;
};

export function GatePathLogo({ className, title }: GatePathLogoProps) {
  return (
    <svg
      aria-hidden={title ? undefined : true}
      aria-label={title}
      className={className}
      role={title ? "img" : undefined}
      viewBox="0 0 64 64"
      xmlns="http://www.w3.org/2000/svg"
    >
      {title ? <title>{title}</title> : null}
      <rect width="64" height="64" rx="16" fill="currentColor" />
      <path
        d="M43 20.5a18 18 0 1 0 5.5 13.5H33"
        fill="none"
        stroke="var(--logo-route, #F8FAFF)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="7"
      />
      <circle cx="48.5" cy="34" r="4.5" fill="var(--logo-waypoint, #F5A65B)" />
    </svg>
  );
}
