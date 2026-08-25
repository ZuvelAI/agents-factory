create policy tenants_app_select
on public.tenants for select
to agents_factory_app
using (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy tenants_app_insert
on public.tenants for insert
to agents_factory_app
with check (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy tenants_app_update
on public.tenants for update
to agents_factory_app
using (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy tenants_admin_select
on public.tenants for select
to agents_factory_admin
using (true);

create policy tenants_admin_insert
on public.tenants for insert
to agents_factory_admin
with check (true);

create policy tenants_admin_update
on public.tenants for update
to agents_factory_admin
using (true)
with check (true);

create policy platform_admins_admin_select
on public.platform_admins for select
to agents_factory_admin
using (true);

create policy platform_admins_admin_insert
on public.platform_admins for insert
to agents_factory_admin
with check (true);

create policy platform_admins_admin_delete
on public.platform_admins for delete
to agents_factory_admin
using (true);

create policy audit_events_app_select
on public.audit_events for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy audit_events_app_insert
on public.audit_events for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy audit_events_admin_select
on public.audit_events for select
to agents_factory_admin
using (true);

create policy audit_events_admin_insert
on public.audit_events for insert
to agents_factory_admin
with check (true);

create policy outbox_jobs_app_select
on public.outbox_jobs for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy outbox_jobs_app_insert
on public.outbox_jobs for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy outbox_jobs_app_update
on public.outbox_jobs for update
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy outbox_jobs_admin_select
on public.outbox_jobs for select
to agents_factory_admin
using (true);

create policy outbox_jobs_admin_insert
on public.outbox_jobs for insert
to agents_factory_admin
with check (true);

create policy outbox_jobs_admin_update
on public.outbox_jobs for update
to agents_factory_admin
using (true)
with check (true);

create policy job_attempts_app_select
on public.job_attempts for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy job_attempts_app_insert
on public.job_attempts for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy job_attempts_app_update
on public.job_attempts for update
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy job_attempts_admin_select
on public.job_attempts for select
to agents_factory_admin
using (true);

create policy job_attempts_admin_insert
on public.job_attempts for insert
to agents_factory_admin
with check (true);

create policy job_attempts_admin_update
on public.job_attempts for update
to agents_factory_admin
using (true)
with check (true);

create policy dead_letter_jobs_app_select
on public.dead_letter_jobs for select
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy dead_letter_jobs_app_insert
on public.dead_letter_jobs for insert
to agents_factory_app
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy dead_letter_jobs_app_update
on public.dead_letter_jobs for update
to agents_factory_app
using (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid)
with check (tenant_id = nullif((select current_setting('app.tenant_id', true)), '')::uuid);

create policy dead_letter_jobs_admin_select
on public.dead_letter_jobs for select
to agents_factory_admin
using (true);

create policy dead_letter_jobs_admin_insert
on public.dead_letter_jobs for insert
to agents_factory_admin
with check (true);

create policy dead_letter_jobs_admin_update
on public.dead_letter_jobs for update
to agents_factory_admin
using (true)
with check (true);
