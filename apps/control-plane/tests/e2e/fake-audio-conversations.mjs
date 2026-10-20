// Synthetic transcript fixtures only; real tenant/RLS behavior is tested in PostgreSQL.
export const audioTenant = "019c2000-0000-7000-8000-000000000102";
export const audioConversation = "019c2000-0000-7000-8000-000000000303";
export function audioMessages(state = "READY") {
  return [
    {
      id: "019c2000-0000-7000-8000-000000000881",
      arrival_sequence: 1,
      direction: "inbound",
      message_type: "audio",
      text:
        state === "READY"
          ? "Consulta por audio <script>audio-fixture</script>"
          : null,
      created_at: "2026-10-20T15:00:00Z",
      agent_id: null,
      agent_spec_id: null,
      delivery_status: null,
      audio_state: state,
      transcription_id: "019c2000-0000-7000-8000-000000000882",
      transcription_digest: state === "READY" ? "a".repeat(64) : null,
      text_source: state === "READY" ? "AUDIO_TRANSCRIPT" : null,
    },
  ];
}
export function handleAudioConversations(request, response, url, json) {
  const root = `/admin/tenants/${audioTenant}/conversations`;
  if (url.pathname === root) {
    json(response, 200, [
      {
        id: audioConversation,
        customer_wa_id: "Contacto de audio",
        control_state: "AI_ACTIVE",
        updated_at: "2026-10-20T15:00:00Z",
      },
    ]);
    return true;
  }
  if (url.pathname === `${root}/${audioConversation}/messages`) {
    const offset = url.searchParams.get("offset");
    json(
      response,
      offset === "100" ? 503 : 200,
      offset === "100"
        ? {}
        : audioMessages(offset === "50" ? "QUEUED" : "READY"),
    );
    return true;
  }
  return false;
}
