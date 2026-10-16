import Link from "next/link";
import { AgentConfigurationForm } from "../../../../../../../components/agent-workspace/agent-configuration-form";
import { LegacyImportForm } from "../../../../../../../components/agent-workspace/company-profile-form";
import {
  readConfiguration,
  readProfile,
} from "../../../../../../../lib/agent-configuration";
import {
  BackendProblem,
  callAuthenticatedBackend,
} from "../../../../../../../lib/api";
export default async function EditAgentPage({
  params,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
}) {
  const { tenantId, agentId } = await params;
  let draft = null,
    companyRevision = 0,
    legacyRevision = 0;
  try {
    try {
      draft = await readConfiguration(tenantId, agentId);
    } catch (error) {
      if (
        !(
          error instanceof BackendProblem &&
          error.code === "agent_configuration_missing"
        )
      )
        throw error;
    }
    if (!draft) {
      try {
        companyRevision = (await readProfile(tenantId)).revision;
      } catch (error) {
        if (
          !(
            error instanceof BackendProblem &&
            error.code === "company_profile_missing"
          )
        )
          throw error;
      }
      const legacy = await callAuthenticatedBackend<unknown>(
        `/admin/tenants/${tenantId}/onboarding`,
      );
      if (
        !legacy ||
        typeof legacy !== "object" ||
        !("revision" in legacy) ||
        !Number.isSafeInteger(legacy.revision) ||
        Number(legacy.revision) < 1
      )
        throw new Error("legacy_missing");
      legacyRevision = Number(legacy.revision);
    }
  } catch {
    return (
      <section className="workspace">
        <h1>Borrador no disponible</h1>
        <p>
          No pudimos leer una configuración editable o un origen heredado
          verificable. No se cambió el agente. Puedes crear un agente nuevo
          desde su empresa.
        </p>
        <Link href={`/tenants/${tenantId}`}>Volver a empresa</Link>
      </section>
    );
  }
  return draft ? (
    <AgentConfigurationForm initial={draft} />
  ) : (
    <LegacyImportForm
      tenant={tenantId}
      agent={agentId}
      legacyRevision={legacyRevision}
      companyRevision={companyRevision}
    />
  );
}
