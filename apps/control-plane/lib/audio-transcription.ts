export type AudioReadFields = {
  audio_state?: string | null;
  transcription_id?: string | null;
  transcription_digest?: string | null;
  text_source?: "TEXT" | "AUDIO_TRANSCRIPT" | null;
};
const states = [
  "QUEUED",
  "PROCESSING",
  "READY",
  "FAILED",
  "CANCELLED",
  "UNCERTAIN",
];
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
export function validAudioFields(row: Record<string, unknown>): boolean {
  if (
    row.audio_state != null &&
    (typeof row.audio_state !== "string" || !states.includes(row.audio_state))
  )
    return false;
  if (
    row.transcription_id != null &&
    (typeof row.transcription_id !== "string" ||
      !uuid.test(row.transcription_id))
  )
    return false;
  if (
    row.transcription_digest != null &&
    (typeof row.transcription_digest !== "string" ||
      !/^[0-9a-f]{64}$/.test(row.transcription_digest))
  )
    return false;
  if (
    row.text_source != null &&
    (typeof row.text_source !== "string" ||
      !["TEXT", "AUDIO_TRANSCRIPT"].includes(row.text_source))
  )
    return false;
  if (row.audio_state === "READY")
    return (
      row.message_type === "audio" &&
      row.text_source === "AUDIO_TRANSCRIPT" &&
      typeof row.text === "string" &&
      row.text.trim().length > 0 &&
      row.text.length <= 25000 &&
      typeof row.transcription_id === "string" &&
      typeof row.transcription_digest === "string"
    );
  return row.text_source !== "AUDIO_TRANSCRIPT";
}
