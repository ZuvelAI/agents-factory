# Inventario para entrega A — 2026-10-14

Checkout aislado codex/whatsapp-coexistence, base ce460da; hay cambios anteriores
de conversaciones/WhatsApp que deben conservarse fuera de commits de esta entrega.

- Montaje: apps/backend/src/agents_factory/main.py, create_app/include_router.
- Admin: PlatformAdmin en common/security.py; TenantContext en cada lectura de agente.
- Datos: tenants, agent_instances, agent_spec_versions, agent_spec_deployments,
  account_agent_bindings, whatsapp_accounts; mensajes y conversaciones existentes.
- Contrato legado: tenant_onboarding_configs por empresa, no por instancia.
- Versiones inmutables: no actualizar configuración ni generar borradores en GET.
- Lecturas nuevas: /admin/agent-workspace/companies y sus agentes por UUID.
- Catálogos: capacidades vacío y conectores UNAVAILABLE; no convertirlos en activos.
- No hay campo estructurado de nombre/tono por instancia en el AgentSpec actual:
  la proyección usará nombre de negocio identificado como heredado y dejará tono
  desconocido hasta entrega B. Nunca extraer campos desde párrafos de instrucciones.
- Salud de cuenta tiene last_health_checked_at; no demuestra salud del worker.
- Pruebas solo sobre PostgreSQL local55322 y Redis56379 desechables.
- Sin migraciones, permisos nuevos, efectos externos ni despliegue en A.
