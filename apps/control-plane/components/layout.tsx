"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

export const navigation = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Tenants", href: "/tenants" },
  { label: "Agents", href: "/agents" },
  { label: "Capabilities", href: "/capabilities" },
  { label: "Integrations", href: "/integrations" },
  { label: "Knowledge", href: "/knowledge" },
  { label: "Conversations", href: "/conversations" },
  { label: "Cases", href: "/cases" },
  { label: "Evals", href: "/evals" },
  { label: "Usage & Costs", href: "/usage" },
  { label: "Operations", href: "/operations" },
  { label: "Settings", href: "/settings" },
] as const;

function isCurrent(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/" || pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavigationLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <ul>
      {navigation.map(({ label, href }) => {
        const current = isCurrent(pathname, href);
        return (
          <li key={href}>
            <Link
              aria-current={current ? "page" : undefined}
              className={current ? "nav-link nav-link-current" : "nav-link"}
              href={href}
              onClick={onNavigate}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function AppShell({
  children,
  signOutAction,
}: {
  children: ReactNode;
  signOutAction: () => Promise<void>;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="control-plane-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="topbar">
        <Link
          className="brand"
          href="/dashboard"
          aria-label="Agents Factory home"
        >
          <span aria-hidden="true" className="brand-mark">
            AF
          </span>
          <span>
            <strong>Agents Factory</strong>
            <small>Control Plane</small>
          </span>
        </Link>
        <div className="topbar-actions">
          <span className="admin-label">Platform admin</span>
          <button
            aria-controls="mobile-navigation"
            aria-expanded={menuOpen}
            className="menu-button"
            onClick={() => setMenuOpen((value) => !value)}
            type="button"
          >
            {menuOpen ? "Close menu" : "Menu"}
          </button>
          <form action={signOutAction}>
            <button className="quiet-button" type="submit">
              Sign out
            </button>
          </form>
        </div>
      </header>
      <aside className="desktop-sidebar">
        <nav aria-label="Control Plane">
          <NavigationLinks />
        </nav>
      </aside>
      <div
        className={
          menuOpen ? "mobile-sidebar mobile-sidebar-open" : "mobile-sidebar"
        }
        id="mobile-navigation"
      >
        <nav aria-label="Mobile Control Plane">
          <NavigationLinks onNavigate={() => setMenuOpen(false)} />
        </nav>
      </div>
      <main className="private-content" id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
