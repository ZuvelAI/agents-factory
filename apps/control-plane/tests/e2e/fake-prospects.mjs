// Fictitious read fixtures only; persistence and access control use real PostgreSQL tests.
const tenant = "019c2000-0000-7000-8000-000000000102";
const uuid = (n) => `019c2000-0000-7000-8000-${String(n).padStart(12, "0")}`;
const conversation = uuid(303);
const rows = [
  [
    901,
    "Valentina Rojas",
    "valentina",
    "Nexo Estudio",
    "Agentes de inteligencia artificial",
    "Quiere automatizar la atención de clientes y mejorar el seguimiento comercial.",
  ],
  [
    902,
    "Andrés Molina",
    null,
    null,
    "Generación y gestión de leads",
    "Busca oportunidades comerciales para su empresa.",
  ],
  [
    903,
    "Laura Torres",
    "lauratorres",
    "Taller Norte",
    "Automatización de procesos",
    "Necesita organizar las solicitudes de servicio.",
  ],
].map(([n, name, username, company, interest, summary]) => ({
  id: uuid(n),
  tenant_id: tenant,
  contact_name: name,
  contact_username: username,
  phone_number: `+57300000000${n - 900}`,
  declared_company: company,
  service_interests: [interest],
  need_summary: summary,
  status: "NEW",
  capture_suppressed: false,
  identity_conflict: false,
  first_conversation_id: conversation,
  last_conversation_id: conversation,
  created_at: "2026-10-19T10:00:00Z",
  updated_at: "2026-10-19T10:00:00Z",
}));
export function handleProspects(request, response, url, json) {
  const match = url.pathname.match(
    /^\/admin\/agent-workspace\/companies\/([^/]+)\/(?:prospects(?:\/([^/]+)(\/events)?)?|conversations\/([^/]+)\/prospect)$/,
  );
  if (!match) return false;
  if (request.method !== "GET") {
    json(response, 405, {});
    return true;
  }
  if (match[1] !== tenant) {
    json(response, 404, {});
    return true;
  }
  if (match[4]) {
    json(response, 200, match[4] === conversation ? rows[0] : null);
    return true;
  }
  if (!match[2]) {
    const q = url.searchParams.get("q") || "";
    if (q === "trigger-error") {
      json(response, 503, {});
      return true;
    }
    const items =
      q === "html"
        ? [{ ...rows[0], contact_name: "<script>ejemplo</script>" }]
        : q
          ? rows.filter((r) =>
              JSON.stringify(r).toLowerCase().includes(q.toLowerCase()),
            )
          : url.searchParams.has("cursor")
            ? rows.slice(2)
            : rows.slice(0, 2);
    json(response, 200, {
      items,
      next_cursor: !q && !url.searchParams.has("cursor") ? "later" : null,
    });
    return true;
  }
  const row = rows.find((r) => r.id === match[2]);
  const privacyRow =
    match[2] === uuid(904)
      ? {
          ...rows[0],
          id: uuid(904),
          capture_suppressed: true,
          identity_conflict: true,
        }
      : undefined;
  if (!row && !privacyRow) {
    json(response, 404, {});
    return true;
  }
  const events = {
    items: [
      {
        id: uuid(950),
        conversation_id: conversation,
        inbound_message_id: uuid(951),
        agent_instance_id: uuid(501),
        agent_version_id: uuid(601),
        agent_name: "Agente comercial",
        version_number: 2,
        operation: "CAPTURE",
        evidence: [
          {
            message_id: uuid(951),
            quote:
              "Me interesa un agente para atender clientes de Nexo Estudio.",
          },
        ],
        created_at: (row ?? privacyRow).created_at,
      },
    ],
    next_cursor: null,
  };
  json(
    response,
    200,
    match[3] ? events : { prospect: row ?? privacyRow, events },
  );
  return true;
}
