"""Lead tables participate in catalog discovery and real role attack tests."""

from uuid import uuid4

from sqlalchemy import text

LEAD_TABLES = tuple(
    f"public.{name}"
    for name in (
        "lead_subjects",
        "lead_subject_keys",
        "lead_prospects",
        "lead_capture_events",
    )
)


async def seed_lead_tables(connection, tenant, rows):
    for table in LEAD_TABLES:
        rows[table] = uuid4()
    params = {
        "tenant": tenant,
        "subject": rows[LEAD_TABLES[0]],
        "key": rows[LEAD_TABLES[1]],
        "prospect": rows[LEAD_TABLES[2]],
        "event": rows[LEAD_TABLES[3]],
        "account": rows["public.whatsapp_accounts"],
        "conversation": rows["public.conversations"],
        "message": rows["public.messages"],
        "agent": rows["public.agent_instances"],
        "version": rows["public.agent_spec_versions"],
    }
    for statement in (
        "INSERT INTO public.lead_subjects(id,tenant_id) VALUES(:subject,:tenant)",
        "INSERT INTO public.lead_subject_keys(id,tenant_id,subject_id,kind,whatsapp_account_id,value) VALUES(:key,:tenant,:subject,'PROVIDER',:account,'user:matrix')",
        "INSERT INTO public.lead_prospects(id,tenant_id,subject_id,first_conversation_id,last_conversation_id) VALUES(:prospect,:tenant,:subject,:conversation,:conversation)",
        "INSERT INTO public.lead_capture_events(id,tenant_id,prospect_id,conversation_id,inbound_message_id,agent_instance_id,agent_version_id,operation,evidence) VALUES(:event,:tenant,:prospect,:conversation,:message,:agent,:version,'CAPTURE','[{\"quote\":\"Interés de prueba\"}]')",
    ):
        await connection.execute(text(statement), params)
