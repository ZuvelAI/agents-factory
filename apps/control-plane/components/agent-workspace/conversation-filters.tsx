"use client";
import type { ReactNode } from "react";

export function ConversationFilters({ children }: { children: ReactNode }) {
  return (
    <form
      className="workspace-filters"
      action="/conversation-log"
      onChange={(event) => {
        if (
          event.target instanceof HTMLSelectElement &&
          event.target.name === "tenant"
        ) {
          for (const field of ["agent", "account"]) {
            const control = event.currentTarget.elements.namedItem(field);
            if (control instanceof HTMLSelectElement) control.value = "";
          }
        }
      }}
    >
      {children}
    </form>
  );
}
