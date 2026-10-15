"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
export function ConversationRefresh() {
  const router = useRouter();
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (
        !document.hidden &&
        !(document.activeElement instanceof HTMLInputElement) &&
        !(document.activeElement instanceof HTMLSelectElement)
      )
        router.refresh();
    }, 45000);
    return () => window.clearInterval(timer);
  }, [router]);
  return (
    <span className="workspace-muted">
      Actualización automática cada 45 s mientras esta vista esté visible.
    </span>
  );
}
