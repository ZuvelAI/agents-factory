"""Explicit role contracts for publication/editing tables, separate from runtime DML."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class AgentTableContract:
    table_name: str
    row_column: str = "id"
    app_select: bool = True


AGENT_TABLE_CONTRACTS = (
    AgentTableContract("public.agent_approved_knowledge_versions"),
    AgentTableContract("public.panel_agent_candidates", "version_id"),
    AgentTableContract("public.agent_publication_test_runs"),
    AgentTableContract("public.agent_publication_test_results", "run_id"),
    AgentTableContract("public.agent_publication_reviews"),
    AgentTableContract("public.account_agent_bindings", "whatsapp_account_id"),
    AgentTableContract("public.account_agent_binding_history"),
    AgentTableContract("public.company_profiles", "tenant_id", False),
    AgentTableContract("public.agent_configuration_drafts", "agent_instance_id", False),
    AgentTableContract("public.workspace_agent_candidates", "version_id"),
)


async def seed_agent_tables(
    connection: AsyncConnection, tenant: UUID, rows: dict[str, UUID]
) -> None:
    """Synthetic valid rows only; no actual publication, account connection or provider call."""
    run = uuid4()
    parameters = {
        "tenant": tenant,
        "agent": rows["public.agent_instances"],
        "version": rows["public.agent_spec_versions"],
        "account": rows["public.whatsapp_accounts"],
        "run": run,
        "digest": "a" * 64,
    }
    statements = (
        (
            "public.agent_approved_knowledge_versions",
            uuid4(),
            "INSERT INTO public.agent_approved_knowledge_versions(id,tenant_id,digest,snapshot) VALUES(:id,:tenant,:digest,'{}')",
        ),
        (
            "public.panel_agent_candidates",
            parameters["version"],
            "INSERT INTO public.panel_agent_candidates(tenant_id,onboarding_revision,code_digest,version_id) VALUES(:tenant,1,:digest,:version)",
        ),
        (
            "public.agent_publication_test_runs",
            run,
            "INSERT INTO public.agent_publication_test_runs(id,tenant_id,version_id,onboarding_revision,agent_spec_digest,knowledge_digest,code_digest) VALUES(:run,:tenant,:version,1,:digest,:digest,:digest)",
        ),
        (
            "public.agent_publication_test_results",
            run,
            "INSERT INTO public.agent_publication_test_results(run_id,tenant_id,result) VALUES(:run,:tenant,'{}')",
        ),
        (
            "public.agent_publication_reviews",
            uuid4(),
            "INSERT INTO public.agent_publication_reviews(id,run_id,tenant_id,reviewer_id,approved) VALUES(:id,:run,:tenant,:id,true)",
        ),
        (
            "public.account_agent_bindings",
            parameters["account"],
            "INSERT INTO public.account_agent_bindings(tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision) VALUES(:tenant,:account,:agent,:version,1)",
        ),
        (
            "public.account_agent_binding_history",
            uuid4(),
            "INSERT INTO public.account_agent_binding_history(id,tenant_id,whatsapp_account_id,agent_instance_id,version_id,revision,action) VALUES(:id,:tenant,:account,:agent,:version,1,'PUBLISH')",
        ),
        (
            "public.company_profiles",
            tenant,
            "INSERT INTO public.company_profiles(tenant_id,revision,configuration) VALUES(:tenant,1,'{}')",
        ),
        (
            "public.agent_configuration_drafts",
            parameters["agent"],
            "INSERT INTO public.agent_configuration_drafts(tenant_id,agent_instance_id,revision,company_revision,company_snapshot,configuration,provenance) VALUES(:tenant,:agent,1,1,'{}','{}','{}')",
        ),
        (
            "public.workspace_agent_candidates",
            parameters["version"],
            "INSERT INTO public.workspace_agent_candidates(tenant_id,agent_instance_id,draft_revision,company_revision,source_digest,code_digest,version_id) VALUES(:tenant,:agent,1,1,:digest,:digest,:version)",
        ),
    )
    for table, identity, statement in statements:
        await connection.execute(text(statement), {**parameters, "id": identity})
        rows[table] = identity
