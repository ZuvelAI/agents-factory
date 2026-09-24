-- The runtime login keeps the application role by default. It may assume the
-- admin role only after the backend has authenticated a Platform Admin JWT.
-- INHERIT FALSE prevents admin privileges from being available implicitly.
grant agents_factory_admin to agents_factory_app
with inherit false, set true;
grant agents_factory_admin to agents_factory_app
with inherit false, set true;
