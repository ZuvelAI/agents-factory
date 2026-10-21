# Agent Pause and Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pausar un agente sin desconectar WhatsApp y reactivarlo atendiendo exclusivamente mensajes nuevos.

**Architecture:** Un control operativo persistente por instancia conserva estado y revisión; cada mensaje recibe una admisión inmutable. Recepción, ejecución y envío consultan el mismo servicio, separado de publicación y conexión. El envío usa una exclusión mutua por agente coordinada con las transiciones para cerrar carreras.

**Tech Stack:** Python, FastAPI, SQLAlchemy async, PostgreSQL/RLS, trabajadores existentes, Next.js/TypeScript y Playwright.

**Spec:** `docs/superpowers/specs/2026-10-21-agent-pause-resume-design.md` (aprobado por Daniel).

## Global Constraints

- Al reactivar se atenderán únicamente mensajes nuevos; los anteriores no se reproducen.
- No cambiar versión publicada, conexión, credenciales ni configuración del agente.
- Pausa independiente por empresa e instancia; historial y recepción se conservan.
- Un envío iniciado hacia Meta no se puede retirar; no prometer cancelación.
- Texto, audio y respuestas técnicas automáticas respetan el mismo control.
- Sin archivo, conectores, Railway, eliminación de legado ni llamadas pagas de prueba.
- Solo migraciones aditivas y permisos mínimos; preservar cambios ajenos del checkout.

## Review Focus

1. Mensaje duplicado tras reactivar: conserva admisión original (T2).
2. Mensaje antiguo entregado tarde por Meta: se conserva sin respuesta (T2).
3. Varios ciclos de pausa durante un trabajo: nunca recupera elegibilidad (T3).
4. Excepción o cancelación durante envío: libera exclusión sin duplicar entrega (T4).
5. Publicación o reasignación concurrente: no borra pausa ni atribuye trabajo al agente equivocado (T2/T5).

## Archivos y responsabilidades

Crear módulo `apps/backend/src/agents_factory/modules/agent_operations/` con
`models.py` (contratos), `repository.py` (persistencia), `service.py` (transiciones),
`admission.py` (elegibilidad por mensaje), `delivery_guard.py` (exclusión de envío),
`router.py` (administración) y `__init__.py`.

Integrar en webhook, runtime, audio y outbound existentes sin concentrar estas
reglas en sus archivos grandes. Panel: cliente `lib/agent-operations.ts`, acciones
y componente `components/agent-workspace/agent-operation-controls.tsx`.
Los puntos de entrada actuales se enumeran en cada tarea. No reestructurar
módulos ajenos. Leer instrucciones aplicables y guías locales de Next.js antes
de editar componentes.

### Task 1: Estado operativo, permisos y transiciones administrativas

**Files:** Crear módulo operations models/repository/service/router; crear migración
`supabase/migrations/20261021120000_agent_operations.sql` (verificar colisión antes);
modificar registro de routers de la aplicación. Crear
`apps/backend/tests/integration/test_agent_operations.py` y prueba SQL RLS.

**Interfaces:** `AgentOperationState(tenant_id: UUID, agent_instance_id: UUID,
enabled: bool, revision: int, resumed_at: datetime | None, updated_at: datetime)`.
`AgentOperationService.transition(*, agent_id: UUID, enabled: bool,
expected_revision: int) -> AgentOperationState`, con sesión/contexto inyectados.
`get_state(agent_id: UUID) -> AgentOperationState`.
Endpoint POST `/admin/agent-workspace/companies/{tenant_id}/agents/{agent_id}/operation`
recibe `enabled` y `expected_revision`; usa PlatformAdmin y auditoría existentes.

- [ ] Escribir pruebas RED: agente existente habilitado/revisión 1, nueva instancia inicializada, pausa incrementa revisión, repetición no la incrementa, revisión obsoleta 409, identidad ajena rechazada y auditoría sin secretos.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_operations.py -q`; confirmar fallo por contratos inexistentes.
- [ ] Crear `agent_operation_states` con clave compuesta empresa/instancia, FK compuesta, revisión positiva, RLS forzada y acceso mínimo; backfill habilitado sin corte retrospectivo. Instancias nuevas se inicializan explícitamente en su servicio de creación.
- [ ] Implementar transición con bloqueo por agente, lectura bloqueada, validación de revisión antes de idempotencia y auditoría transaccional. Reactivar fija `resumed_at` del servidor y nueva revisión; pausar no borra el corte previo.
- [ ] Ejecutar pruebas anteriores y SQL de aislamiento, sin resetear ninguna base compartida o de producción; confirmar PASS.
- [ ] Commit únicamente archivos T1 con mensaje `feat: add audited per-agent operation state`.

### Task 2: Admisión inmutable en recepción

**Files:** Crear `admission.py`; ampliar migración aditiva con
`agent_message_admissions`; modificar `modules/whatsapp/webhook.py`,
`modules/agent_factory/channel_binding.py` y pruebas
`apps/backend/tests/integration/test_agent_message_admission.py`.

**Interfaces:** `MessageAdmission(message_id: UUID, agent_instance_id: UUID | None,
operation_revision: int | None, eligible: bool, reason: str)`.
`admit_message(session: AsyncSession, context: TenantContext, *, message_id: UUID,
account_id: UUID, provider_timestamp: datetime | None) -> MessageAdmission`.
`check_message_eligibility(session: AsyncSession, context: TenantContext, *,
message_id: UUID) -> bool` verifica también asignación vigente.

- [ ] Crear RED para recepción pausada con historial intacto; duplicado conserva admisión; mensaje con timestamp anterior/igual al corte se bloquea; posterior pasa; ausente/inválido tras reactivar se bloquea; historial importado nunca admite automatización.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_message_admission.py -q` y confirmar RED.
- [ ] Persistir admisión única por empresa/mensaje con FK y RLS. Conservar razones `paused`, `before_resume`, `invalid_timestamp`, `unassigned`, `eligible`. Comparar timestamp proveedor estrictamente posterior al corte; no existe corte inicial para tráfico previo a esta función.
- [ ] Resolver binding y registrar admisión en la misma transacción que la recepción duradera, antes de encolar. Orden de bloqueos: cuenta lifecycle, agente operation. Binding/publicación adquieren ese mismo orden; transiciones solo bloquean agente y nunca intentan después cuenta. No usar orden de ejecución de trabajador como fecha de admisión.
- [ ] Registrar mensajes antiguos sin admisión como no elegibles al ejecutar; no inventar elegibilidad en un trabajo atrasado. Actualizar fixtures para mensajes nuevos.
- [ ] Añadir carrera reasignación/recepción con dos sesiones y verificar agente/revisión coherentes; ejecutar pruebas y confirmar PASS.
- [ ] Commit T2: `feat: fence inbound messages by agent operation revision`.

### Task 3: Detener procesamiento y respuestas automáticas obsoletas

**Files:** Modificar `workers/agent-worker/src/agent_worker/jobs.py`,
`modules/runtime/turn_service.py`, `modules/audio_ingestion/jobs.py`,
`modules/audio_ingestion/service.py`, `modules/audio_ingestion/fallback.py`.
Crear `apps/backend/tests/integration/test_agent_operation_runtime.py`.

**Interfaces:** Consumir `check_message_eligibility` de T2 antes de trabajo pago,
antes de ejecutar herramientas y antes de persistir/encolar respuesta automática.
La respuesta conserva `in_reply_to_message_id` para que T4 recupere admisión.

- [ ] Escribir RED: pausa antes del trabajo evita modelo/transcriptor; pausa durante generación o transcripción impide encolado; doble pausa/reactivación no revive revisión; fallback de audio tampoco se envía; mensajes nuevos sí pasan. Usar proveedores falsos contables.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_operation_runtime.py -q` y confirmar RED.
- [ ] Añadir guardas compartidas sin duplicar lógica de estado; registrar omisión operativa sin marcar transcripción READY como error ni reintentar llamadas pagas concluidas. No cancelar efectos externos ya iniciados ni iniciar otros tras perder elegibilidad.
- [ ] Ejecutar suite focal y regresiones de audio, primer contacto, prospectos e intervención humana; confirmar PASS y cero llamadas externas.
- [ ] Commit T3: `feat: suppress paused and stale automatic agent turns`.

### Task 4: Frontera segura de entrega

**Files:** Crear `delivery_guard.py`; modificar
`modules/whatsapp/outbound_service.py` y transition de T1; revisar entrada
`workers/outbound-worker/src/outbound_worker/jobs.py`.
Crear `apps/backend/tests/integration/test_agent_operation_delivery.py`.

**Interfaces:** `agent_delivery_guard(engine: AsyncEngine, *, tenant_id: UUID,
agent_id: UUID) -> AsyncContextManager[None]`. Exclusión advisory de sesión en
conexión dedicada por agente, clave idéntica para envío y transición. Liberación
en finally; invalidar conexión si unlock no se confirma. No mantener transacción
abierta durante HTTP. Toda adquisición sigue cuenta antes de agente si ambas son necesarias.

- [ ] Escribir RED con barreras entre sesiones: pausa antes de claim bloquea; pausa entre preparación/envío bloquea; envío ya iniciado termina antes de confirmar pausa; fallo HTTP/cancelación libera guard; estado UNCERTAIN no se reenvía; aislamiento entre agentes.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_operation_delivery.py -q`; confirmar RED.
- [ ] Bajo guard, revalidar admisión, binding, estado y revisión inmediatamente antes de iniciar HTTP. Transición usa el mismo guard hasta su commit. Reutilizar estado BLOCKED con código `agent_operation_ineligible`; nunca reutilizar solicitud bloqueada tras reactivar. No bloquear envíos humanos ni señales de entrega.
- [ ] Probar fallo de lectura como no permitido, y fallback automático sin atribución como bloqueado; no permitir bypass por plantilla automática. Ejecutar pruebas de outbox/outbound existentes y nuevas; confirmar PASS.
- [ ] Commit T4: `feat: serialize agent pauses with outbound delivery`.

### Task 5: Controles y proyección del panel

**Files:** Modificar `workspace_models.py`, `workspace_repository.py`,
`workspace_projection.py`; crear cliente y componente citados arriba y
`components/agent-workspace/operation-actions.ts`; modificar
`agent-overview.tsx`, `status-summary.tsx` y página de detalle existente.
Crear `apps/control-plane/tests/unit/agent-operations.test.ts` y
`apps/control-plane/tests/e2e/agent-operations.spec.ts`.

**Interfaces:** `AgentOperationView` contiene enabled, revision y updated_at;
`setAgentOperation(tenantId: string, agentId: string, enabled: boolean,
expectedRevision: number)` usa proxy autenticado existente, nunca credenciales cliente.

- [ ] Escribir RED de contrato y Playwright: confirmar pausa/reactivación; cancelación no escribe; loading evita doble clic; 409 ofrece recargar; fallo conserva estado anterior; agente pausado se distingue de canal caído; no aparece Archivo habilitado.
- [ ] Ejecutar pruebas nuevas con herramientas pnpm existentes y confirmar RED.
- [ ] Mostrar controles con texto de confirmación de la spec, última modificación y revisión actual. Actualizar ficha y resumen de empresa después de éxito; no inferir atendiendo solo de enabled. Foco/teclado/lectores de pantalla funcionales.
- [ ] Ejecutar unitarias, E2E, tipos, lint y build del panel; confirmar PASS.
- [ ] Commit T5: `feat: expose safe pause and resume controls in agent workspace`.

### Task 6: Integración, revisión y preparación de instalación

**Files:** Crear `docs/pausa-agentes-entrega.md`; actualizar este plan con evidencia.

- [ ] Ejecutar flujo completo local con dos empresas/agentes: recibir texto y audio, pausar con trabajo pendiente, conservar historial, reactivar, enviar nuevo mensaje; afirmar solo nueva respuesta y ningún envío ajeno. Sin OpenAI ni Meta reales.
- [ ] Ejecutar backend completo, aislamiento/RLS y panel completo en entorno aislado; registrar comandos, resultados y commit. No declarar PASS a partir de resultados antiguos.
- [ ] Realizar revisión independiente de la rama según método elegido y resolver hallazgos de concurrencia, permisos y atribución antes de instalar.
- [ ] Preparar orden de despliegue: respaldo y restauración ensayada, esquema aditivo, trabajadores con guardas, backend y panel al final. Mantener controles no disponibles hasta verificar que todos los emisores ejecutan versión compatible. Identificar y bloquear emisores heredados que ignoren el control.
- [ ] Documentar recuperación que mantiene envío bloqueado para agentes pausados y mensajes invalidados; no hacer rollback a binario que ignore fences. Verificar imagen/versión por servicio y salud sin exponer secretos.
- [ ] Commit documentación y presentar resultados. Producción requiere su autorización correspondiente; este plan no ejecuta instalación ni pausa Zuvel.

## Handoff

### Cierre local — 2026-10-21

Tareas 1–6 implementadas y verificadas. Backend 1.024/1.024; panel 161 unitarias,
49 Chromium, tipos/lint/build; seguridad y aislamiento reales locales aprobados;
restauración artificial comprobada. Revisión independiente final con dos hallazgos
importantes corregidos mediante RED→GREEN, sin segunda revisión ni llamadas pagas.
Detalle y condiciones de instalación: `docs/pausa-agentes-entrega.md`.
Producción no instalada; controles administrativos deshabilitados por defecto.

Recomendación: ejecución directa en esta sesión, tareas secuenciales y revisión
independiente final. Antes de implementar, Daniel revisa este plan y elige método.
