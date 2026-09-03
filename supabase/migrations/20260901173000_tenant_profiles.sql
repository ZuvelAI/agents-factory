alter table public.tenants
add column legal_name text,
add column industry text,
add column timezone text,
add column locale text,
add column revision integer not null default 1;

alter table public.tenants
add constraint tenants_legal_name_check
check (legal_name is null or length(btrim(legal_name)) between 1 and 200)
not valid;
alter table public.tenants validate constraint tenants_legal_name_check;

alter table public.tenants
add constraint tenants_industry_check
check (industry is null or length(btrim(industry)) between 1 and 120)
not valid;
alter table public.tenants validate constraint tenants_industry_check;

alter table public.tenants
add constraint tenants_timezone_check
check (timezone is null or length(timezone) between 1 and 100)
not valid;
alter table public.tenants validate constraint tenants_timezone_check;

alter table public.tenants
add constraint tenants_locale_check
check (locale is null or locale in ('es-CO','en-US'))
not valid;
alter table public.tenants validate constraint tenants_locale_check;

alter table public.tenants
add constraint tenants_revision_check check (revision > 0) not valid;
alter table public.tenants validate constraint tenants_revision_check;
