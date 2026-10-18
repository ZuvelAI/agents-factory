"""Resolve typed provider aliases without guessing or merging conflicting people."""

from uuid import UUID

from agents_factory.common.ids import new_uuid7

from .models import LeadSubjectResolution, TrustedLeadContext
from .repository import LeadRepository


class LeadIdentityResolver:
    def __init__(self, repository: LeadRepository) -> None:
        self.repository = repository

    async def resolve(self, trusted: TrustedLeadContext) -> LeadSubjectResolution:
        repo = self.repository
        keys: list[tuple[str, UUID | None, str]] = [
            ("PROVIDER", trusted.account_id, value) for value in trusted.provider_keys
        ]
        if trusted.phone_number:
            keys.append(("PHONE", None, trusted.phone_number))
        if not keys:
            return LeadSubjectResolution(None)
        keys.sort(key=lambda key: f"{key[0]}:{key[1]}:{key[2]}")
        for kind, account, value in keys:
            await repo.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))",
                {"key": f"lead:{trusted.tenant_id}:{kind}:{account}:{value}"},
            )
        subjects: set[UUID] = set()
        for kind, account, value in keys:
            result = await repo.execute(
                "SELECT subject_id FROM public.lead_subject_keys WHERE tenant_id=:tenant AND kind=:kind AND whatsapp_account_id IS NOT DISTINCT FROM :account AND value=:value",
                {"kind": kind, "account": account, "value": value},
            )
            subject_id = result.scalar_one_or_none()
            if subject_id:
                subjects.add(subject_id)
        if len(subjects) > 1:
            return LeadSubjectResolution(
                None, conflicted=True, conflict_subject_ids=tuple(sorted(subjects))
            )
        subject_id = next(iter(subjects), None)
        if subject_id is None:
            subject_id = new_uuid7()
            await repo.execute(
                "INSERT INTO public.lead_subjects(id,tenant_id) VALUES(:id,:tenant)",
                {"id": subject_id},
            )
        await repo.lock_subject(subject_id)
        for kind, account, value in keys:
            await repo.execute(
                "INSERT INTO public.lead_subject_keys(id,tenant_id,subject_id,kind,whatsapp_account_id,value) VALUES(:id,:tenant,:subject,:kind,:account,:value) ON CONFLICT DO NOTHING",
                {
                    "id": new_uuid7(),
                    "subject": subject_id,
                    "kind": kind,
                    "account": account,
                    "value": value,
                },
            )
        return LeadSubjectResolution(subject_id)
