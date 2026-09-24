"""Fixed test-account runtime preflight. No messages and no credential output."""
import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

from agents_factory.config import load_settings
from agents_factory.database import Database
from agents_factory.common.errors import DomainError
from agents_factory.modules.whatsapp.review_router import templates


async def main():
    settings = load_settings()
    database = Database(settings.database_url)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, database=database)),
        state=SimpleNamespace(correlation_id=uuid4(), restricted_reviewer=True),
    )
    try:
        async with database.session_factory.begin() as session:
            result = await templates(request, UUID("894a6c8b-f1e0-4c6a-abfd-e8feccb0d532"), session)
        print(f"test_templates_loaded={len(result)}; messages_sent=0")
    finally:
        await database.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except DomainError as error:
        print(f"preflight_failed={error.code}; messages_sent=0")
        raise SystemExit(1)
    except Exception as error:
        print(f"preflight_failed={type(error).__name__}; messages_sent=0")
        raise SystemExit(1)
