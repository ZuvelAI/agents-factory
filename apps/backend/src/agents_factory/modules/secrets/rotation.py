from __future__ import annotations

import argparse
import asyncio
import os
import secrets
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from agents_factory.modules.secrets.contracts import SecretEnvelope
from agents_factory.modules.secrets.envelope import (
    NONCE_BYTES,
    EnvironmentMasterKeyProvider,
    canonical_secret_aad,
)


async def rotate_tenant_keys(
    *,
    database_url: str,
    tenant_id: UUID,
    old_environment: Mapping[str, str],
    new_environment: Mapping[str, str],
    limit: int,
) -> int:
    old_provider = EnvironmentMasterKeyProvider(environment=old_environment)
    new_provider = EnvironmentMasterKeyProvider(environment=new_environment)
    if new_provider.key_version <= old_provider.key_version:
        raise ValueError("new key version must be greater than old key version")
    engine = create_async_engine(database_url)
    run_id = uuid4()
    rotated = 0
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL ROLE agents_factory_key_rotation"))
            await connection.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"),
                {"tenant": str(tenant_id)},
            )
            await connection.execute(
                text(
                    "INSERT INTO public.secret_rotation_runs (id,tenant_id,old_key_version,"
                    "new_key_version,status) VALUES (:id,:tenant,:old,:new,'RUNNING')"
                ),
                {
                    "id": run_id,
                    "tenant": tenant_id,
                    "old": old_provider.key_version,
                    "new": new_provider.key_version,
                },
            )
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT id,tenant_id,purpose,record_context,ciphertext,"
                            "wrapped_data_key,payload_nonce,key_nonce,algorithm,format_version,"
                            "key_id,key_version FROM public.secret_envelopes WHERE tenant_id=:tenant "
                            "AND key_version=:old ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED"
                        ),
                        {
                            "tenant": tenant_id,
                            "old": old_provider.key_version,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                envelope = SecretEnvelope(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    purpose=row["purpose"],
                    record_context=row["record_context"],
                    ciphertext=bytes(row["ciphertext"]),
                    wrapped_data_key=bytes(row["wrapped_data_key"]),
                    payload_nonce=bytes(row["payload_nonce"]),
                    key_nonce=bytes(row["key_nonce"]),
                    algorithm=row["algorithm"],
                    format_version=row["format_version"],
                    key_id=row["key_id"],
                    key_version=row["key_version"],
                )
                aad = canonical_secret_aad(
                    secret_id=envelope.id,
                    tenant_id=tenant_id,
                    purpose=envelope.purpose,
                    record_context=envelope.record_context,
                    version=envelope.format_version,
                    component="data_key",
                )
                data_key = old_provider.unwrap_data_key(
                    envelope.wrapped_data_key, nonce=envelope.key_nonce, aad=aad
                )
                new_nonce = secrets.token_bytes(NONCE_BYTES)
                wrapped = new_provider.wrap_data_key(data_key, nonce=new_nonce, aad=aad)
                await connection.execute(
                    text(
                        "UPDATE public.secret_envelopes SET wrapped_data_key=:wrapped,"
                        "key_nonce=:nonce,key_id=:key_id,key_version=:new WHERE tenant_id=:tenant "
                        "AND id=:id AND key_version=:old"
                    ),
                    {
                        "wrapped": wrapped,
                        "nonce": new_nonce,
                        "key_id": new_provider.key_id,
                        "new": new_provider.key_version,
                        "tenant": tenant_id,
                        "id": envelope.id,
                        "old": old_provider.key_version,
                    },
                )
                rotated += 1
            await connection.execute(
                text(
                    "UPDATE public.secret_rotation_runs SET status='COMPLETED',rotated_count=:count,"
                    "completed_at=now() WHERE tenant_id=:tenant AND id=:id"
                ),
                {"count": rotated, "tenant": tenant_id, "id": run_id},
            )
    finally:
        await engine.dispose()
    return rotated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrap one tenant's envelope data keys"
    )
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000:
        return 64
    required = (
        "ROTATION_DATABASE_URL",
        "OLD_APP_MASTER_KEY",
        "NEW_APP_MASTER_KEY",
        "OLD_APP_MASTER_KEY_VERSION",
        "NEW_APP_MASTER_KEY_VERSION",
    )
    if any(not os.environ.get(name) for name in required):
        return 78
    count = asyncio.run(
        rotate_tenant_keys(
            database_url=os.environ["ROTATION_DATABASE_URL"],
            tenant_id=args.tenant,
            old_environment={
                "APP_MASTER_KEY": os.environ["OLD_APP_MASTER_KEY"],
                "APP_MASTER_KEY_VERSION": os.environ["OLD_APP_MASTER_KEY_VERSION"],
            },
            new_environment={
                "APP_MASTER_KEY": os.environ["NEW_APP_MASTER_KEY"],
                "APP_MASTER_KEY_VERSION": os.environ["NEW_APP_MASTER_KEY_VERSION"],
            },
            limit=args.limit,
        )
    )
    print(f"rotation batch completed: {count} envelope(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
