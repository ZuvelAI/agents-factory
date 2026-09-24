import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./zuvel-theme.css";

export const metadata: Metadata = {
  title: "Agents Factory Control Plane",
  description: "Private platform administration",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
