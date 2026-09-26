alter table public.whatsapp_accounts
  add column display_phone_digits text
  constraint whatsapp_accounts_display_phone_digits_check check (
    display_phone_digits is null
    or display_phone_digits ~ '^[0-9]{7,20}$'
  );

create unique index whatsapp_accounts_active_coexistence_display_phone_key
  on public.whatsapp_accounts (waba_id, display_phone_digits)
  where provider = 'meta'
    and status = 'active'
    and mode = 'COEXISTENCE'
    and display_phone_digits is not null;
