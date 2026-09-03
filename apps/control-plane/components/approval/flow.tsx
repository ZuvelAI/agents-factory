"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { submitApproval } from "../../app/approval/[token]/actions";
import {
  LINK_PATTERN,
  type ApprovalReply,
  type ReviewDetails,
  type ReviewResult,
} from "../../lib/approval-contract";
import { DecisionForm, type DecisionFields } from "./decision-form";
import { OTPForm } from "./otp-form";
import { ApprovalResult } from "./result";

type Stage = "LOADING" | "EMAIL" | "OTP" | "DECISION" | "CLOSED" | "RECORDED";
type Proof = {
  link_token: string;
  email?: string;
  code?: string;
  challenge_id?: string;
};
declare global {
  interface Window {
    __afTakeApprovalLink?: () => string;
  }
}

export function ApprovalFlow() {
  const proof = useRef<Proof>({ link_token: "" });
  const started = useRef(false);
  const locked = useRef(false);
  const generation = useRef(0);
  const heading = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState<Stage>("LOADING");
  const [details, setDetails] = useState<ReviewDetails>();
  const [result, setResult] = useState<ReviewResult>();
  const [error, setError] = useState("");
  const [busy, startTransition] = useTransition();

  function close() {
    proof.current = { link_token: "" };
    setDetails(undefined);
    setError("");
    setStage("CLOSED");
  }

  function accept(reply: ApprovalReply, operation: string) {
    if (reply.status === "CLOSED") return close();
    if (
      reply.status === "RATE_LIMITED" ||
      reply.status === "UNAVAILABLE" ||
      reply.status === "INVALID_VERIFICATION"
    ) {
      setError(
        reply.status === "RATE_LIMITED"
          ? "Demasiados intentos. Espera un minuto antes de volver a intentar."
          : reply.status === "INVALID_VERIFICATION"
            ? "No pudimos verificar el código. Revisa el correo; el código puede haber vencido."
            : "No se pudo confirmar el resultado. Abre de nuevo el enlace del correo antes de volver a intentar.",
      );
      if (reply.status === "INVALID_VERIFICATION" && operation !== "inspect") {
        delete proof.current.code;
        setDetails(undefined);
        setStage("OTP");
      } else if (stage === "LOADING") setStage("EMAIL");
      return;
    }
    setError("");
    if (reply.status === "OPEN") {
      if (reply.details) {
        setDetails(reply.details);
        setStage("DECISION");
      } else setStage("EMAIL");
    } else if (reply.status === "IF_AUTHORIZED_SENT") {
      proof.current.challenge_id = reply.challenge_id;
      delete proof.current.code;
      setStage("OTP");
    } else if (reply.status === "RECORDED") {
      proof.current = { link_token: "" };
      setDetails(undefined);
      setResult(reply.result);
      setStage("RECORDED");
    }
  }

  function send(operation: string, fields: Record<string, unknown> = {}) {
    if (locked.current || !proof.current.link_token) return;
    locked.current = true;
    const current = generation.current;
    startTransition(async () => {
      try {
        const reply = await submitApproval(operation, {
          ...proof.current,
          ...fields,
        });
        if (generation.current === current) accept(reply, operation);
      } catch {
        if (generation.current === current)
          setError(
            "No se pudo confirmar el resultado. Abre de nuevo el enlace del correo.",
          );
      } finally {
        if (generation.current === current) locked.current = false;
      }
    });
  }

  useEffect(() => {
    // No storage, cookies, hidden form fields, URL parameters or action closures.
    if (!started.current) {
      started.current = true;
      const value = window.__afTakeApprovalLink?.() ?? "";
      delete window.__afTakeApprovalLink;
      if (LINK_PATTERN.test(value)) {
        proof.current = { link_token: value };
        send("inspect");
      } else {
        // The one-time fragment is external browser state, unavailable during SSR.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        close();
      }
    }
    const clear = () => {
      generation.current += 1;
      locked.current = false;
      proof.current = { link_token: "" };
      document
        .querySelectorAll<HTMLFormElement>(".approval-form")
        .forEach((form) => form.reset());
      setDetails(undefined);
      setResult(undefined);
      setError("");
      setStage("CLOSED");
    };
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) clear();
    };
    const changedLink = () => {
      const value =
        new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
      history.replaceState(null, "", "/approval/review");
      clear();
      if (LINK_PATTERN.test(value)) {
        proof.current = { link_token: value };
        setStage("LOADING");
        send("inspect");
      }
    };
    window.addEventListener("pagehide", clear);
    window.addEventListener("pageshow", restored);
    window.addEventListener("hashchange", changedLink);
    return () => {
      window.removeEventListener("pagehide", clear);
      window.removeEventListener("pageshow", restored);
      window.removeEventListener("hashchange", changedLink);
    };
    // Intentionally mount-only: never re-request an OTP/decision as a render effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (stage !== "LOADING") heading.current?.focus();
  }, [stage]);
  return (
    <div ref={heading} tabIndex={-1} className="approval-flow" aria-busy={busy}>
      {error ? <p role="alert">{error}</p> : null}
      {stage === "LOADING" ? <p role="status">Comprobando el enlace…</p> : null}
      {stage === "EMAIL" || stage === "OTP" ? (
        <OTPForm
          stage={stage}
          busy={busy}
          onEmail={(email) => {
            proof.current.email = email;
            send("otp");
          }}
          onCode={(code) => {
            proof.current.code = code;
            send("review");
          }}
          onResend={() => send("otp")}
        />
      ) : null}
      {stage === "DECISION" && details ? (
        <DecisionForm
          details={details}
          busy={busy}
          onDecision={(fields: DecisionFields) => send("decision", fields)}
        />
      ) : null}
      {stage === "CLOSED" || stage === "RECORDED" ? (
        <ApprovalResult result={stage === "RECORDED" ? result : undefined} />
      ) : null}
    </div>
  );
}
