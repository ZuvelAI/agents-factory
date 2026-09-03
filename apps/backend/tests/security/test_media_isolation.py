from uuid import uuid4

import pytest

from agents_factory.modules.media.contracts import MediaError
from agents_factory.modules.media.storage import LocalPrivateMediaStore


async def test_private_store_rejects_symlinks_and_cross_tenant_object_paths(tmp_path):
    store = LocalPrivateMediaStore(tmp_path / "media")
    tenant, other, identifier = uuid4(), uuid4(), uuid4()
    key, digest = await store.put(
        tenant_id=tenant, media_id=identifier, content=b"private fixture"
    )
    assert key == f"{tenant}/{identifier}/{digest}"
    assert (store.root / key).stat().st_mode & 0o077 == 0
    with pytest.raises(MediaError):
        await store.read(tenant_id=other, media_id=identifier, digest=digest)
    with pytest.raises(MediaError):
        await store.read(tenant_id=tenant, media_id=identifier, digest="../../outside")
    target = store.root / str(other)
    target.symlink_to(store.root / str(tenant), target_is_directory=True)
    with pytest.raises(MediaError):
        await store.read(tenant_id=other, media_id=identifier, digest=digest)
    with pytest.raises(MediaError):
        await store.put(
            tenant_id=other, media_id=uuid4(), content=b"must not follow link"
        )
    await store.delete(tenant_id=tenant, media_id=identifier, digest=digest)
    assert not (store.root / key).exists()
