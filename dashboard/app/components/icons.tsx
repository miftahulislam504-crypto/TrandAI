// একটাই আইকন সেট: পাতলা কালো লাইনের SVG। ইমোজি নয়।
const PATHS: Record<string, string[]> = {
  list: ["M4 6h16", "M4 12h16", "M4 18h10"],
  bookmark: ["M6 4h12v17l-6-4-6 4z"],
  bell: ["M6 9a6 6 0 1 1 12 0c0 6 2 7 2 7H4s2-1 2-7", "M10 20a2 2 0 0 0 4 0"],
  megaphone: ["M3 11v2a1 1 0 0 0 1 1h2l8 4V6L6 10H4a1 1 0 0 0-1 1z", "M18 9a4 4 0 0 1 0 6"],
  pulse: ["M3 12h4l3-8 4 16 3-8h4"],
  search: ["M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z", "M20 20l-4-4"],
  left: ["M15 6l-6 6 6 6"],
  right: ["M9 6l6 6-6 6"],
  download: ["M12 4v11", "M7 11l5 5 5-5", "M5 20h14"],
  close: ["M6 6l12 12", "M18 6L6 18"],
  check: ["M5 12l5 5 10-11"],
  alert: ["M12 4l9 16H3z", "M12 10v4", "M12 17.5v.01"],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 8v.01"],
  external: ["M7 17L17 7", "M9 7h8v8"],
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 20, filled = false }: { name: IconName; size?: number; filled?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {PATHS[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}
