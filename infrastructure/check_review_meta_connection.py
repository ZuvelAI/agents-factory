"""Print only Meta error codes, never credentials or provider response bodies."""
import asyncio
from uuid import UUID, uuid4
import httpx
from agents_factory.config import load_settings
from agents_factory.database import Database
from agents_factory.common.context import TenantContext
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.whatsapp.account_service import DatabaseMetaAccessTokenResolver

async def main():
    settings = load_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory.begin() as session:
            resolver = DatabaseMetaAccessTokenResolver(session=session, key_provider=EnvironmentMasterKeyProvider(
                environment={"APP_MASTER_KEY": settings.app_master_key.get_secret_value()}))
            secret = await resolver.resolve(context=TenantContext(
                tenant_id=UUID("c5cd8d04-01f2-49be-aa27-1075520a2a20"),
                actor_id=UUID("894a6c8b-f1e0-4c6a-abfd-e8feccb0d532"),
                actor_type="customer", correlation_id=uuid4()),
                whatsapp_account_id=UUID("d4dfa61a-7ed6-4a87-877a-1d34e7dbf837"))
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(settings.meta_graph_api_base_url.rstrip("/") + "/1894805611498111/message_templates",
                    params={"fields": "name,status", "limit": "1"},
                    headers={"Authorization": "Bearer " + secret.reveal().decode()})
            error = response.json().get("error", {})
            print({"http_status": response.status_code, "meta_code": error.get("code"),
                   "meta_subcode": error.get("error_subcode"), "messages_sent": 0})
    finally:
        await db.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print({"failure": type(error).__name__})
        raise SystemExit(1)
