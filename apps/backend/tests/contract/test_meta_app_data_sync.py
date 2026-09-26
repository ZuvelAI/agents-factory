import httpx
import pytest
from pydantic import SecretStr

from agents_factory.modules.secrets.redaction import ResolvedSecret
from agents_factory.modules.whatsapp.meta_provider import MetaCloudApiProvider


@pytest.mark.parametrize("sync_type", ["smb_app_state_sync", "history"])
async def test_meta_app_data_sync_uses_phone_and_records_request_id(sync_type):
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"messaging_product": "whatsapp", "request_id": "support-123"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = MetaCloudApiProvider(
            app_secret=SecretStr("test-only"),
            http_client=client,
            graph_api_base_url="https://graph.facebook.com/v25.0",
        )
        request_id = await provider.request_app_data_sync(
            phone_number_id="123456",
            sync_type=sync_type,
            access_token=ResolvedSecret(b"test-token"),
        )
    assert request_id == "support-123"
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "https://graph.facebook.com/v25.0/123456/smb_app_data"
    assert seen[0].headers["Authorization"] == "Bearer test-token"
    assert seen[0].read().decode() == (
        '{"messaging_product":"whatsapp","sync_type":"' + sync_type + '"}'
    )


async def test_meta_app_data_sync_requires_request_id():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"messaging_product": "whatsapp"})
        )
    ) as client:
        provider = MetaCloudApiProvider(
            app_secret=SecretStr("test-only"),
            http_client=client,
            graph_api_base_url="https://graph.facebook.com/v25.0",
        )
        with pytest.raises(RuntimeError, match="request ID"):
            await provider.request_app_data_sync(
                phone_number_id="123456",
                sync_type="history",
                access_token=ResolvedSecret(b"test-token"),
            )


async def test_meta_app_data_sync_requires_configured_graph_endpoint():
    provider = MetaCloudApiProvider(app_secret=SecretStr("test-only"))
    with pytest.raises(RuntimeError, match="not configured"):
        await provider.request_app_data_sync(
            phone_number_id="123456",
            sync_type="history",
            access_token=ResolvedSecret(b"test-token"),
        )
