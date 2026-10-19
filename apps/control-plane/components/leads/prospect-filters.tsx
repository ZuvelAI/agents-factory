"use client";
import type { ReactNode } from "react";
export function ProspectFilters({ children }: { children: ReactNode }) {
  return (
    <form
      action="/prospects"
      className="workspace-filters"
      onChange={(e) => {
        if (
          e.target instanceof HTMLSelectElement &&
          e.target.name === "tenant"
        ) {
          const agent = e.currentTarget.elements.namedItem("agent");
          if (agent instanceof HTMLSelectElement) agent.value = "";
          e.currentTarget.requestSubmit();
        }
      }}
    >
      {children}
    </form>
  );
}
