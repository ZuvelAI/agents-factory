import type { CSSProperties } from "react";

const paths = {
  prospects:
    "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 21v-2a8 8 0 0 1 16 0v2 M18 9h5 M20.5 6.5v5",
  dashboard: "M3 3h7v7H3z M14 3h7v4h-7z M14 11h7v10h-7z M3 14h7v7H3z",
  tenants:
    "M4 21V5l8-2v18 M12 9h8v12 M2 21h20 M7 8h2 M7 12h2 M7 16h2 M16 13h1 M16 17h1",
  agents: "M8 4h8l5 8-5 8H8l-5-8z M9 9h6v6H9z M12 1v3 M12 20v3",
  capabilities: "m13 2-9 12h7l-1 8 10-13h-7z",
  integrations:
    "m8 3 3 3 M3 8l3 3 M5 10l5-5 5 5-5 5z M12 13l3 3 M14 19l5-5 M17 17l4 4",
  whatsapp:
    "M21 11a9 9 0 0 1-13 8l-6 3 2-6A9 9 0 1 1 21 11 M8 7l2 3 2 2 3 2 2-2",
  knowledge:
    "M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1v15",
  conversations:
    "M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0z M7 10h10 M7 14h6",
  cases: "M3 7h18v14H3z M8 7V3h8v4 M3 12h18 M10 12v3h4v-3",
  evals: "M5 3h14v18H5z M8 8l2 2 5-5 M8 14h8 M8 17h5",
  usage: "M4 20V10 M10 20V4 M16 20v-7 M22 20H2",
  operations: "M2 12h4l3-8 5 16 3-8h5",
  settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  arrow: "M4 12h16 M14 6l6 6-6 6",
  back: "M20 12H4 M10 6l-6 6 6 6",
  check: "m5 12 4 4L19 6",
  lock: "M5 10h14v11H5z M8 10V6a4 4 0 0 1 8 0v4 M12 14v3",
  chevron: "m9 5 7 7-7 7",
  save: "M4 3h13l4 4v14H3V3h1 M7 3v6h10V3 M7 21v-8h10v8",
  info: "M12 17v-5 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  logout: "M9 3H3v18h6 M9 12h12 M17 8l4 4-4 4",
} as const;

export type IconName = keyof typeof paths;

export function UiIcon({
  name,
  size = 20,
  style,
}: {
  name: IconName;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      className="ui-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}
