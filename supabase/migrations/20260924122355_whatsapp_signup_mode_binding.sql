-- Existing authorization sessions were API-only. Preserve that default;
-- a callback may never substitute a different onboarding mode.
alter table agents_factory_private.whatsapp_signup_states
  add column requested_mode text not null default 'API_ONLY'
  check (requested_mode in ('API_ONLY', 'COEXISTENCE'));
