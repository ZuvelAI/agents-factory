// Synthetic browser contract fixture. PostgreSQL tests cover actual persistence/RLS.
const tenant = "019c2000-0000-7000-8000-000000000102";
const first = "019c2000-0000-7000-8000-000000000501";
const second = "019c2000-0000-7000-8000-000000000502";
const company = {
  commercial_name: "Zuvel",
  legal_name: "",
  country: "",
  city: "",
  industry: "Tecnología",
  timezone: "America/Bogota",
  primary_locale: "es-CO",
  business_description: "Soluciones de inteligencia artificial",
  service_hours: "",
  whatsapp_volume: "unknown",
  responsible_person: "",
  privacy_contact: "",
  incident_contact: "",
};
let profile, drafts;
function reset() {
  profile = {
    tenant_id: tenant,
    revision: 1,
    configuration: structuredClone(company),
    updated_at: "2026-10-15T12:00:00Z",
  };
  drafts = new Map(
    [first, second].map((id, index) => [
      id,
      {
        tenant_id: tenant,
        agent_instance_id: id,
        revision: 1,
        company_revision: 1,
        current_company_revision: 1,
        company_update_available: false,
        company_snapshot: structuredClone(company),
        provenance: { source: "manual" },
        updated_at: "2026-10-15T12:00:00Z",
        validation_issues: [],
        configuration: {
          schema_version: 1,
          purpose: "Orientar clientes",
          agent: {
            agent_name: index ? "Soporte" : "Comercial",
            greeting_style: "BRAND_ONLY",
            tone: "PROFESSIONAL_WARM",
            formality: "TU",
            greeting: "Hola, somos Zuvel",
            instructions: index
              ? "Configuración de soporte"
              : "Configuración comercial",
            supported_languages: ["es-CO"],
            brand_vocabulary: "",
            model: "gpt-6-luna",
          },
          knowledge: {
            source_name: "Servicios",
            source_type: "INTERNAL_TEXT",
            source_reference: "Manual",
            authority: "OFFICIAL",
            approved_summary: "Análisis de datos para toma de decisiones",
            critical_conflicts: 0,
            review_confirmed: true,
          },
          policies_identity: {
            pricing_response: "QUOTE_REQUIRED",
            privacy_policy_status: "APPROVED",
            customer_identity_method: "NONE",
            policy_notes: "",
          },
          human_operations: {
            handoff_enabled: false,
            response_surface: "NONE",
            support_hours: "",
            awaiting_human_policy: "SILENT",
          },
          approval_routes: {
            high_risk_actions_expected: false,
            approver_emails: [],
            strategy: "FIRST_RESPONSE",
            route_notes: "",
          },
          capabilities: {
            use_cases: [],
            selected_capabilities: [],
            unsupported_requirements: [],
            onboarding_classification: "STANDARD",
          },
          integrations: {
            business_systems_required: false,
            required_connectors: [],
            connection_notes: "",
          },
        },
      },
    ]),
  );
}
reset();
export async function handleAgentConfiguration(
  request,
  response,
  url,
  json,
  readJson,
) {
  if (url.pathname === "/__test/reset-configuration") {
    reset();
    json(response, 200, {});
    return true;
  }
  const root = `/admin/agent-workspace/companies/${tenant}`;
  const match = url.pathname.match(
    new RegExp(
      `^${root}/agents/([^/]+)/configuration(?:/(refresh-company|import-legacy))?$`,
    ),
  );
  const conflict = () => {
    response.setHeader("content-type", "application/problem+json");
    response.writeHead(409, { "content-type": "application/problem+json" });
    response.end(
      JSON.stringify({
        type: "https://example.test/conflict",
        title: "Conflict",
        status: 409,
        code: "configuration_revision_conflict",
        detail: "Reload",
        correlation_id: first,
      }),
    );
  };
  if (match) {
    const draft = drafts.get(match[1]);
    if (!draft) {
      json(response, 404, {});
      return true;
    }
    if (request.method === "GET") {
      json(response, 200, {
        ...draft,
        current_company_revision: profile.revision,
        company_update_available: profile.revision !== draft.company_revision,
      });
      return true;
    }
    const body = await readJson(request);
    if (body.configuration?.agent?.instructions === "guardado-lento-controlado")
      await new Promise((resolve) => setTimeout(resolve, 1200));
    if (body.expected_revision !== draft.revision) {
      conflict();
      return true;
    }
    if (body.configuration?.agent.instructions === "conflicto-controlado") {
      draft.configuration.agent.instructions = "Cambio de otro administrador";
      draft.revision++;
      conflict();
      return true;
    }
    if (match[2] === "refresh-company") {
      if (body.expected_company_revision !== profile.revision) {
        conflict();
        return true;
      }
      draft.company_snapshot = structuredClone(profile.configuration);
      draft.company_revision = profile.revision;
    } else {
      draft.configuration = body.configuration;
    }
    draft.revision++;
    json(response, 200, {
      ...draft,
      current_company_revision: profile.revision,
      company_update_available: profile.revision !== draft.company_revision,
    });
    return true;
  }
  if (url.pathname === root + "/profile") {
    if (request.method === "PUT") {
      const body = await readJson(request);
      if (body.configuration?.business_description === "guardado-empresa-lento")
        await new Promise((resolve) => setTimeout(resolve, 1200));
      if (body.expected_revision !== profile.revision) {
        conflict();
        return true;
      }
      profile = {
        ...profile,
        revision: profile.revision + 1,
        configuration: body.configuration,
      };
    }
    json(response, 200, profile);
    return true;
  }
  return false;
}
