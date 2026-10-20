const labels: Record<string, string> = {
  QUEUED: "En espera de transcripción",
  PROCESSING: "Preparando transcripción",
  FAILED: "No se pudo transcribir",
  CANCELLED: "Procesamiento cancelado",
  UNCERTAIN: "No se pudo confirmar la transcripción",
};
export function AudioTranscription({
  state,
  text,
}: {
  state?: string | null;
  text: string | null;
}) {
  return (
    <section aria-label="Nota de voz" style={{ overflowWrap: "anywhere" }}>
      <small>
        Nota de voz ·{" "}
        {state === "READY"
          ? "Transcripción automática"
          : (labels[state ?? ""] ?? "Sin transcripción")}
      </small>
      {state === "READY" && text ? (
        <>
          <p style={{ whiteSpace: "pre-wrap" }}>{text}</p>
          <small>La transcripción automática puede contener errores.</small>
        </>
      ) : null}
    </section>
  );
}
