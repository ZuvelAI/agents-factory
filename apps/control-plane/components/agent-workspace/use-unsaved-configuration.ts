"use client";

import { useEffect } from "react";

/** Protect unsaved text in internal navigation, page unload and browser Back. */
export function useUnsavedConfiguration(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const url = window.location.href,
      guardId = crypto.randomUUID();
    let active = true,
      leaving = false;
    const question =
      "Tienes cambios sin guardar. ¿Quieres salir y descartarlos?";
    const guard = () =>
      window.history.pushState(
        { ...window.history.state, configurationGuard: guardId },
        "",
        url,
      );
    guard();
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const click = (event: MouseEvent) => {
      if (
        !(event.target instanceof Element) ||
        !event.target.closest("a[href]")
      )
        return;
      if (window.confirm(question)) {
        leaving = true;
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    const pop = (event: PopStateEvent) => {
      if (!active) return;
      event.stopImmediatePropagation();
      if (window.confirm(question)) {
        leaving = true;
        active = false;
        window.removeEventListener("popstate", pop, true);
        window.history.back();
      } else guard();
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", click, true);
    window.addEventListener("popstate", pop, true);
    return () => {
      active = false;
      window.removeEventListener("beforeunload", unload);
      document.removeEventListener("click", click, true);
      window.removeEventListener("popstate", pop, true);
      if (
        !leaving &&
        window.location.href === url &&
        window.history.state?.configurationGuard === guardId
      )
        window.history.back();
    };
  }, [dirty]);
}
