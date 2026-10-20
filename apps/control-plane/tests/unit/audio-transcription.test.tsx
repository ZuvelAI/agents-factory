import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { AudioTranscription } from "../../components/audio-transcription";
import { validAudioFields } from "../../lib/audio-transcription";
import { ProspectDetail } from "../../components/leads/prospect-detail";

it("rejects malformed status and source instead of showing missing audio", () => {
  expect(validAudioFields({ audio_state: ["READY"] })).toBe(false);
  expect(validAudioFields({ text_source: ["TEXT"] })).toBe(false);
});

it("labels automatic transcription and escapes HTML without media links", () => {
  const html = renderToStaticMarkup(
    createElement(AudioTranscription, {
      state: "READY",
      text: "<script>audio</script>",
    }),
  );
  expect(html).toContain("Transcripción automática");
  expect(html).toContain("&lt;script&gt;audio&lt;/script&gt;");
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("<audio");
  expect(html).not.toContain("href=");
});

it("prospect evidence distinguishes automatic audio from original written text", () => {
  const identity = "019c2000-0000-7000-8000-000000000102";
  const detail = {
    prospect: {
      id: identity,
      tenant_id: identity,
      contact_name: "Ana",
      contact_username: null,
      phone_number: null,
      declared_company: null,
      service_interests: [],
      need_summary: null,
      status: "NEW" as const,
      capture_suppressed: false,
      identity_conflict: false,
      first_conversation_id: identity,
      last_conversation_id: identity,
      created_at: "2026-10-20T12:00:00Z",
      updated_at: "2026-10-20T12:00:00Z",
    },
    events: {
      items: [
        {
          id: identity,
          conversation_id: identity,
          inbound_message_id: identity,
          agent_instance_id: identity,
          agent_version_id: identity,
          agent_name: "Agente",
          version_number: 1,
          operation: "CAPTURE" as const,
          evidence: [{ message_id: identity, quote: "Quiero un agente" }],
          transcription_sources: [
            {
              message_id: identity,
              source_kind: "AUDIO_TRANSCRIPT" as const,
              transcription_id: identity,
              digest: "a".repeat(64),
            },
          ],
          created_at: "2026-10-20T12:00:00Z",
        },
      ],
      next_cursor: null,
    },
  };
  expect(
    renderToStaticMarkup(
      createElement(ProspectDetail, { detail, tenant: identity }),
    ),
  ).toContain("Fuente: transcripción automática de audio");
  detail.events.items[0].transcription_sources = [];
  expect(
    renderToStaticMarkup(
      createElement(ProspectDetail, { detail, tenant: identity }),
    ),
  ).toContain("Fuente: texto escrito por el contacto");
});
it.each(["QUEUED", "PROCESSING", "FAILED", "CANCELLED", "UNCERTAIN", null])(
  "shows preparation %s, not an invented transcript",
  (state) => {
    const html = renderToStaticMarkup(
      createElement(AudioTranscription, { state, text: "must not render" }),
    );
    expect(html).not.toContain("must not render");
    expect(html).toContain("Nota de voz");
  },
);
