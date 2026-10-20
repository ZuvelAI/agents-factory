/** Display metadata only. Routing references are never formatted as phones. */
export type ContactIdentity = {
  customer_wa_id: string;
  contact_name?: string | null;
  contact_username?: string | null;
  contact_phone_number?: string | null;
};

export function validContactIdentity(row: Record<string, unknown>): boolean {
  return ["contact_name", "contact_username", "contact_phone_number"].every(
    (key) => row[key] == null || typeof row[key] === "string",
  );
}

export function contactTitle(contact: ContactIdentity): string {
  return (
    contact.contact_name ||
    contact.contact_phone_number ||
    (contact.contact_username
      ? `@${contact.contact_username.replace(/^@/, "")}`
      : "Contacto sin nombre")
  );
}

export function contactDetails(contact: ContactIdentity): string {
  const parts = [
    contact.contact_phone_number,
    contact.contact_username
      ? `@${contact.contact_username.replace(/^@/, "")}`
      : null,
  ].filter(Boolean);
  return parts.length
    ? parts.join(" · ")
    : `Referencia WhatsApp: ${contact.customer_wa_id}`;
}
