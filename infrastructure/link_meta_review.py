"""Operator-only bootstrap for the fixed Meta TEST account; never sends messages."""
import asyncio
import json
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import text

from agents_factory.common.context import TenantContext
from agents_factory.database import Database, set_tenant_context
from agents_factory.modules.secrets.envelope import EnvironmentMasterKeyProvider
from agents_factory.modules.secrets.repository import SecretVault
from agents_factory.modules.whatsapp.account_service import WhatsAppAccountRepository
from agents_factory.modules.whatsapp.signup_service import ACCESS_TOKEN_PURPOSE, REQUIRED_META_SCOPES


async def main():
    env = dotenv_values('/workspace/.env')
    review = dotenv_values('/workspace/.env.meta-review')
    review_access_token = review['META_REVIEW_ACCESS_TOKEN']
    tenant = UUID('c5cd8d04-01f2-49be-aa27-1075520a2a20')
    phone, waba, business = '1334721596385520', '1894805611498111', '1121764643872916'
    async with httpx.AsyncClient(base_url='https://graph.facebook.com/v25.0', timeout=20) as c:
        r = await c.get('/debug_token', params={'input_token': review_access_token}, headers={'Authorization': 'Bearer ' + env['META_APP_ID'] + '|' + env['META_APP_SECRET']})
        r.raise_for_status()
        d = r.json()['data']
        assert d['is_valid'] and str(d['app_id']) == '4513182438959780'
        assert REQUIRED_META_SCOPES.issubset(d['scopes'])
        headers = {'Authorization': 'Bearer ' + review_access_token}
        r = await c.get('/' + waba, params={'fields': 'id,name,owner_business_info'}, headers=headers)
        r.raise_for_status()
        assert r.json()['owner_business_info']['id'] == business
        assert r.json()['name'] == 'Test WhatsApp Business Account'
        r = await c.get('/' + waba + '/phone_numbers', params={'fields': 'id'}, headers=headers)
        r.raise_for_status()
        assert any(p['id'] == phone for p in r.json()['data'])
    db = Database(SecretStr(env['DATABASE_URL']))
    try:
        async with db.session_factory.begin() as s:
            await s.execute(text('SET LOCAL ROLE agents_factory_admin'))
            await set_tenant_context(s, tenant)
            admin = UUID('894a6c8b-f1e0-4c6a-abfd-e8feccb0d532')
            assert await s.scalar(text('SELECT EXISTS(SELECT 1 FROM public.platform_admins WHERE user_id=:id)'), {'id': admin})
            context = TenantContext(tenant_id=tenant, actor_id=admin, actor_type='platform_admin', correlation_id=uuid4())
            repo = WhatsAppAccountRepository(s)
            await repo.lock_phone_number(phone_number_id=phone)
            existing = await repo.find_by_phone_number(phone_number_id=phone)
            rotating = '--rotate-fixed-test' in sys.argv
            if rotating:
                assert existing is not None
                assert existing.id == UUID('d4dfa61a-7ed6-4a87-877a-1d34e7dbf837')
                assert existing.tenant_id == tenant and existing.waba_id == waba
                assert existing.business_id == business and existing.status == 'active'
            elif existing is not None:
                raise RuntimeError('Existing mapping: refusing to overwrite')
            account_id = existing.id if rotating else uuid4()
            binding = f'whatsapp_account:{account_id}'
            vault = SecretVault.for_session(s, key_provider=EnvironmentMasterKeyProvider(environment={'APP_MASTER_KEY': env['APP_MASTER_KEY']}))
            ref = await vault.store(context=context, purpose=ACCESS_TOKEN_PURPOSE, record_context=binding, plaintext=review_access_token.encode())
            expiry = datetime.fromtimestamp(d['expires_at'], UTC) if d.get('expires_at') else None
            result = await repo.connect_account(account_id=account_id, context=context, business_id=business, waba_id=waba, phone_number_id=phone, access_token_secret_ref=ref, mode='API_ONLY', coexistence_eligibility='UNKNOWN', granted_scopes=tuple(sorted(d['scopes'])), token_expires_at=expiry, verified_at=datetime.now(UTC))
            loaded = await vault.load(context=context, reference=ref, purpose=ACCESS_TOKEN_PURPOSE, record_context=binding)
            assert loaded.reveal() == review_access_token.encode()
        print(json.dumps({'linked_test_account': str(result.id), 'encrypted_token_verified': True, 'token_type': d.get('type'), 'expires_at': d.get('expires_at'), 'data_access_expires_at': d.get('data_access_expires_at'), 'required_scopes_verified': True, 'messages_sent': 0}))
    finally:
        await db.dispose()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        # Never print exception bodies: HTTP/SQL exceptions may contain secrets.
        print(json.dumps({'failed': type(error).__name__}))
        raise SystemExit(1)
