/** Small stroke icon set drawn for Breatheasy (24px grid, 1.8 stroke). */
const PATHS: Record<string, string> = {
  x: "M6 6l12 12M18 6 6 18",
  alert: "M12 4 21 19.5H3zM12 10v4.5M12 17.2v.01",
  share: "M12 3.5v11M8 7.5l4-4 4 4M5 12.5V19a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-6.5",
  star: "m12 3.6 2.55 5.2 5.75.84-4.15 4.05.98 5.71L12 16.7l-5.13 2.7.98-5.71L3.7 9.64l5.75-.84z",
  locate: "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z",
  home: "M4 11.2 12 4.5l8 6.7V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z",
  briefcase: "M4 8h16v11H4zM9 8V5.5h6V8M4 13h16",
  clock: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 4v4.4l3 1.8",
  pin: "M12 21s-6.5-6.1-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.9 12 21 12 21zm0-8.7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  swap: "M7.5 4v15m0 0L4 15.5M7.5 19l3.5-3.5M16.5 20V5m0 0L13 8.5M16.5 5 20 8.5",
  walk: "M13 4.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zM10.5 21l1.5-6 2.5 2.5V21M9 11.5l2.5-3.5 3 2 2.5 1M11.5 8l-1.5 6.5",
  bike: "M5.5 18a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zm13 0a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5.5 14.5 9 8h6l3.5 6.5M9 8l3 6.5h-6.5M14 5.5h2.5L15 8",
  scooter: "M5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zm14 0a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM7.5 15.5h7l3-6.5h-3M14.5 15.5 12 9H8.5",
  car: "M4 16.5V12l2-5h12l2 5v4.5zM4 12h16M7.5 19.5v-3m9 3v-3M7.5 14.2h.01M16.5 14.2h.01",
  sliders: "M4 7h9m4 0h3M4 17h3m4 0h9M15 4.5v5M9 14.5v5",
  chevron: "m9 6 6 6-6 6",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7.5 8a7.5 7.5 0 0 1 15 0",
  navigate: "M4 11.5 20 4l-7.5 16-2-6.5z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-10v5.5M12 7.8v.01",
  layers: "m12 4 8.5 4.5L12 13 3.5 8.5zm-8.5 8 8.5 4.5 8.5-4.5",
  leaf: "M5.5 18.5C5 10 10 5.5 19 5.3c.3 8.8-4.4 13.8-13.5 13.5zM5.5 18.5 13 11",
  mic: "M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8",
  drop: "M12 3.8S6.2 10.1 6.2 14.1a5.8 5.8 0 0 0 11.6 0C17.8 10.1 12 3.8 12 3.8z",
  road: "M8.5 3.5 5 20.5M15.5 3.5l3.5 17M12 5v2.5M12 11v2.5M12 17v2.5",
  factory: "M3.5 20V10.5l5 3v-3l5 3V7h3.5v13zM3.5 20h17M17 7V4h3v16",
  cone: "M12 3.5l6 16.5H6zM8.4 13.2h7.2M10 8.6h4M4 20h16",
  check: "M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17zM8.5 12.3l2.4 2.4 4.6-4.9",
  wifiOff: "M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 4.5-2.5M19 13a10 10 0 0 0-2.2-1.6M2 9.5a15 15 0 0 1 4.5-2.8M22 9.5A15 15 0 0 0 11 5.6M12 20h.01",
};

export function Icon({ name, size = 20, className }: { name: keyof typeof PATHS | string; size?: number; className?: string }) {
  return (
    <svg
      className={`icon${className ? ` ${className}` : ""}`}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={PATHS[name] ?? PATHS.info} />
    </svg>
  );
}
