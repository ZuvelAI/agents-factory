"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UiIcon, type IconName } from "./ui-icon";

const navigation = [
  ["Dashboard", "/"],
  ["Tenants", "/tenants"],
  ["Agents", "/agents"],
  ["Capabilities", "/capabilities"],
  ["Integrations", "/integrations"],
  ["Knowledge", "/knowledge"],
  ["Conversations", "/conversations"],
  ["Cases", "/cases"],
  ["Evals", "/evals"],
  ["Usage & Costs", "/usage"],
  ["Operations", "/operations"],
  ["Settings", "/settings"],
] as const;

export function ControlPlaneNavigation() {
  const pathname = usePathname();
  const icons: IconName[] = [
    "dashboard",
    "tenants",
    "agents",
    "capabilities",
    "integrations",
    "knowledge",
    "conversations",
    "cases",
    "evals",
    "usage",
    "operations",
    "settings",
  ];

  return (
    <nav className="primary-navigation" aria-label="Control Plane">
      <ul>
        {navigation.map(([label, href], index) => {
          const active =
            href === "/"
              ? pathname === "/"
              : pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href}>
              {index === 0 || index === 6 || index === 9 ? (
                <p className="nav-group-label">
                  {index === 0
                    ? "WORKSPACE"
                    : index === 6
                      ? "ACTIVIDAD"
                      : "ADMINISTRACIÓN"}
                </p>
              ) : null}
              <Link
                href={href}
                aria-label={label}
                title={label}
                className={active ? "active" : undefined}
                aria-current={active ? "page" : undefined}
              >
                <UiIcon name={icons[index]} size={18} />
                <span>{label}</span>
                {active ? <span className="active-nav-dot" /> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
