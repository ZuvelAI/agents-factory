export type SimulatedLeadProposal = {
  operation: "CAPTURE" | "SUPPRESS";
  simulated: true;
  declared_name: string | null;
  declared_company: string | null;
  service_interest: string | null;
  need_summary: string | null;
  evidence: { message_id: string; quote: string }[];
};
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const nullable = (value: unknown, limit: number) =>
  value === null ||
  (typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= limit);
export function parseSimulatedProposals(
  value: unknown,
): SimulatedLeadProposal[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 1)
    throw new Error("invalid_lead_simulation");
  for (const item of value) {
    if (
      !record(item) ||
      item.simulated !== true ||
      !["CAPTURE", "SUPPRESS"].includes(String(item.operation)) ||
      !nullable(item.declared_name, 200) ||
      !nullable(item.declared_company, 200) ||
      !nullable(item.service_interest, 300) ||
      !nullable(item.need_summary, 2000) ||
      !Array.isArray(item.evidence) ||
      item.evidence.length < 1 ||
      item.evidence.length > 5 ||
      !item.evidence.every(
        (e) =>
          record(e) &&
          typeof e.message_id === "string" &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
            e.message_id,
          ) &&
          typeof e.quote === "string" &&
          e.quote.trim().length > 0 &&
          e.quote.length <= 500,
      ) ||
      (item.operation === "SUPPRESS" &&
        [
          item.declared_name,
          item.declared_company,
          item.service_interest,
          item.need_summary,
        ].some((v) => v !== null))
    )
      throw new Error("invalid_lead_simulation");
  }
  return value as SimulatedLeadProposal[];
}
