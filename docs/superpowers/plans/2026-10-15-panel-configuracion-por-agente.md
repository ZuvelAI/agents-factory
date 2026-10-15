# Configuración independiente por agente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Método nativo conservado de la entrega A; una revisión independiente final.

**Goal:** Crear y editar empresas y borradores independientes por agente en el panel operativo, sin cambiar ninguna respuesta publicada.

**Architecture:** Un solo backend, mismos permisos administrativos y repositorios existentes. La identidad empresarial compartida y el borrador editable por instancia se guardan separados del AgentSpec inmutable de ejecución. La importación del asistente anterior es explícita, dirigida a una instancia concreta y reversible sin borrar sus datos.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, PostgreSQL/Supabase; Next.js, React, TypeScript; pytest, Vitest y Playwright existentes.

**Spec:** `docs/superpowers/specs/2026-10-14-panel-operativo-multiagente-design.md`, aprobado. Antecedente: entrega A en `docs/panel-operativo-entrega-a.md`.

## Global Constraints

- El panel es interno para Daniel y administradores autorizados en esta entrega.
- Empresa contiene agentes; cada agente tiene identidad estable, borrador propio, versiones, pruebas y publicaciones.
- Guardar borrador conserva cambios sin afectar producción.
- Panel y operaciones realizadas con Codex usan los mismos servicios de aplicación, permisos, revisión esperada y auditoría.
- Las capacidades no implementadas aparecen como no disponibles, con motivo.
- No hay eliminación definitiva en esta entrega.
- Un número de WhatsApp tiene un único agente responsable activo; no tocar bindings, credenciales, webhooks ni Embedded Signup.
- No desplegar, aplicar migraciones productivas, limpiar tablas ni migrar Railway. Conservar panel anterior y cambios previos ajenos.
- Node >=22, pnpm11.24.0, Supabase CLI2.115.0; sin dependencias nuevas por defecto. No actualizar herramientas como parte de esta entrega.
- Backend: rutas delgadas, modelos estrictos, servicios de aplicación, SQL en repositorios y transformaciones puras. Documentar responsabilidades; no crear un segundo runtime.
- Esta entrega guarda y valida configuración. Prueba interactiva, publicación, rollback y autorizaciones efectivas de herramientas corresponden a C; sus botones siguen deshabilitados aquí.

## Review Focus

1. Dos administradores guardan la misma revisión: exactamente uno gana; el otro conserva su texto y puede comparar, sin reintento ciego (B2/B4).
2. Empresa con varias instancias y borrador heredado ambiguo: importación solo con instancia y revisión explícitas; nunca escoger primera fila (B3).
3. Cambia la información compartida mientras se edita un agente: mostrar revisión de empresa pendiente y exigir incorporación explícita (B2/B4).
4. Fallo después de escribir configuración pero antes de auditar: rollback de toda la operación; ningún cambio silencioso (B2).
5. Configuración incompleta o proveedor no implementado: guardar borrador sin prometer ejecución; validación precisa y ausencia de secretos en auditoría/errores (B2/B4).

## Decisiones a revisar antes de implementar

1. Dos tablas aditivas: `company_profiles` y `agent_configuration_drafts`. No duplicar mensajes, credenciales, versiones publicadas ni conexión de WhatsApp.
2. El borrador de edición no es `agent_spec_versions.state=DRAFT`: permite datos incompletos. C convertirá una revisión exacta en candidato compilado mediante los controles existentes.
3. Datos compartidos se incorporan como snapshot al borrador. Modificar empresa no actualiza automáticamente borradores ni versiones publicadas.
4. No extraer tono/propósito interpretando instrucciones antiguas. Importar solamente configuración estructurada existente y mostrar procedencia; si no existe, comenzar manualmente sin inventar campos.
5. El editor permite identidad, propósito, saludo, tono/formalidad, idiomas, instrucciones, vocabulario, conocimiento manual con referencia/revisión, políticas, operación y modelos ya habilitados. No incluye ingestión automática de PDF/URL ni nuevos parámetros del modelo.
6. Capacidades e integraciones se muestran con disponibilidad real y permanecen de solo lectura hasta C. Guardarlas como preferencias no debe dar a entender que están conectadas.

## Inventario verificado y mapa de archivos

`modules/tenants/onboarding.py` contiene los modelos estructurados y la revisión por empresa. `agent_factory/onboarding_projection.py` convierte configuración validada a AgentSpec; `publication_service.py` prepara candidatos desde el asistente anterior. `AgentSpecRepository.create_instance()` crea identidad sin canal. `AuditService.record()` permite registrar cambios dentro de la transacción actual. No sustituir estos flujos productivos en B.

Backend, bajo `apps/backend/src/agents_factory/modules/agent_factory/`:
- Crear `configuration_models.py`: contratos de perfiles/borradores, reutilizando validadores existentes de onboarding mediante composición.
- Crear `configuration_repository.py`: persistencia tenant-scoped y compare-and-swap, sin lógica HTTP.
- Crear `configuration_service.py`: creación, edición, validación y auditoría transaccional.
- Crear `configuration_import.py`: importación explícita del legado y procedencia; no heurísticas ni SQL en rutas.
- Crear `configuration_router.py`: rutas PlatformAdmin, TransactionSession; registrar en `main.py`.
- Modificar `workspace_service.py`, `workspace_repository.py`, `workspace_models.py` y `workspace_projection.py`: mostrar nombre/propósito del borrador nuevo con procedencia y revisión; mantener snapshot activo separado.
- Crear `tests/integration/test_agent_configuration.py`, `test_agent_configuration_import.py`; ampliar `test_agent_workspace.py`.
- Migración: crear con `supabase migration new agent_configuration_drafts` al ejecutar B1, no inventar timestamp ahora. No modificar migraciones antiguas.

Frontend, bajo `apps/control-plane/`:
- Crear `lib/agent-configuration.ts`: contratos y cliente server-side, validación de respuestas.
- Crear `components/agent-workspace/configuration-actions.ts`: acciones servidor autenticadas.
- Crear `company-profile-form.tsx`, `agent-configuration-form.tsx`, `configuration-conflict.tsx` en ese directorio: formularios accesibles y comparación de conflictos, sin SQL ni tokens.
- Crear páginas `app/(authenticated)/tenants/new/page.tsx`, `tenants/[tenantId]/settings/page.tsx`, `tenants/[tenantId]/agents/new/page.tsx`, `tenants/[tenantId]/agents/[agentId]/edit/page.tsx`.
- Modificar tarjetas y ficha para enlazar creación/edición; conservar rutas anteriores y publicación deshabilitada.
- Crear `tests/unit/agent-configuration.test.ts`, `tests/e2e/agent-configuration.spec.ts`; ampliar fixture local `fake-agent-workspace.mjs`.
- Ampliar `docs/backend-guide.md`; crear `docs/panel-operativo-entrega-b.md`.

## Persistencia y contratos propuestos

`company_profiles`: tenant_id PK/FK tenants, revision entero >0, configuration JSON object (`CompanyConfiguration`), created_at, updated_at. Índice PK suficiente para acceso por tenant. Nombre de tarjeta empresarial sigue `tenants.name`; al actualizar commercial_name se actualiza explícitamente ese nombre en la misma transacción.

`agent_configuration_drafts`: PK(tenant_id,agent_instance_id), FK compuesta a agent_instances(tenant_id,id), revision >0, company_revision >0, company_snapshot JSON object, configuration JSON object, provenance JSON object, created_at, updated_at. FK tenant a company_profiles. No apuntar company_revision a fila mutable ni almacenar tokens. El perfil no se elimina en esta entrega.

Ambas: ENABLE y FORCE RLS; políticas para `agents_factory_admin` con tenant_id igual al contexto transaccional en USING y WITH CHECK; SELECT/INSERT/UPDATE solamente. Revocar a public/anon/authenticated/service_role/app; no conceder permisos al runtime que no consume estas tablas. Sin SECURITY DEFINER ni bypassrls. Pruebas con roles reales, no solo propietario.

`AgentEditableConfiguration`: schema_version Literal[1], purpose:str max2000 default vacío, agent:AgentConfiguration, knowledge:KnowledgeConfiguration, policies_identity:PoliciesIdentityConfiguration, human_operations:HumanOperationsConfiguration, approval_routes:ApprovalRoutesConfiguration; capabilities/integrations preservados para importar, pero no editables por PUT en B. `extra=forbid`. Límites y enums originales se reutilizan; no ampliar modelos disponibles por este trabajo.

`DraftView`: tenant_id, agent_instance_id, revision, company_revision, current_company_revision, company_update_available, company_snapshot, configuration, provenance, validation_issues:list[{field,code,message}], updated_at. `CompanyProfileView`: tenant_id, revision, configuration, updated_at. GET sin fila devuelve404 con código específico, nunca crea datos.

Servicio `AgentConfigurationService(session,principal)`:
- `create_company(*,name:str,slug:str)->CompanyProfileView`: TenantRepository con modelo Tenant existente y perfil revision1; sin agentes/canales.
- `get_company(*,tenant_id:UUID)->CompanyProfileView`.
- `save_company(*,tenant_id:UUID,expected_revision:int,configuration:CompanyConfiguration)->CompanyProfileView`: expected_revision=0 crea perfil ausente con INSERT ON CONFLICT DO NOTHING; >0 actualiza solo revisión coincidente. Empresa debe existir; ninguna creación ocurre en GET.
- `create_agent(*,tenant_id:UUID,name:str)->DraftView`: instancia y borrador revision1, snapshot actual del perfil, configuración vacía segura con nombre indicado; sin versiones/canales.
- `get_draft(*,tenant_id:UUID,agent_id:UUID)->DraftView`.
- `save_draft(*,tenant_id:UUID,agent_id:UUID,expected_revision:int,configuration:AgentEditableConfiguration)->DraftView`: no modificar secciones de capacidades/integraciones importadas (comparar con persistido y rechazar diferencias con422); SQL UPDATE revision esperada, incrementa solo al guardar con éxito. Si cambia contenido/procedencia del conocimiento, review_confirmed vuelve a false salvo confirmación explícita de revisión de ese mismo contenido en la solicitud; nunca heredar aprobación antigua por defecto.
- `refresh_company(*,tenant_id:UUID,agent_id:UUID,expected_revision:int,expected_company_revision:int)->DraftView`: copia perfil exacto actual, incrementa revisión del borrador; sin alterar conocimiento ni instrucciones.

`LegacyConfigurationImportService.import_draft(*,tenant_id:UUID,agent_id:UUID,expected_legacy_revision:int,expected_company_revision:int)->DraftView`: POST explícito solo si no existe borrador; perfil ausente puede crearse desde empresa heredada con expected_company_revision=0. Si existe perfil no coincidente, devolver409 sin sobrescribir ni mezclar. Agente debe pertenecer al tenant y tener evidencia inequívoca de asociación al legado en panel_agent_candidates→agent_spec_versions; sin ella,409 requiere selección/conciliación fuera de este flujo. Copia una vez; repetición misma procedencia devuelve existente sin nueva auditoría/revisión; distinto origen o borrador editado devuelve409. Guardar origen, revisión heredada y digest canónico, no datos completos en auditoría.

Rutas `/admin/agent-workspace`, siempre PlatformAdmin:
- POST `/companies` {name,slug}; GET/PUT `/companies/{tenant}/profile` (PUT {expected_revision,configuration}).
- POST `/companies/{tenant}/agents` {name}.
- GET/PUT `/companies/{tenant}/agents/{agent}/configuration` (PUT {expected_revision,configuration}).
- POST `/companies/{tenant}/agents/{agent}/configuration/refresh-company` {expected_revision,expected_company_revision}.
- POST `/companies/{tenant}/agents/{agent}/configuration/import-legacy` {expected_legacy_revision,expected_company_revision}.

Errores:401/403 no admin,404 tenant/agente ajeno o ausente,409 revisión obsoleta/importación ambigua,422 contrato inválido. Error409 devuelve solo código y revisiones actuales, no configuración; comparación recarga mediante GET autorizado. Auditoría: entity_id empresa/agente, revisiones antes/después y nombres de secciones modificadas, nunca instrucciones/conocimiento/correos/secretos. Cada mutación y auditoría en una transacción sin llamadas externas.

## Task 1: B1 — Almacenamiento aditivo y aislamiento

**Interfaces:** produce tablas descritas y `ConfigurationRepository(session,context)` con `read_company`, `insert_company`, `update_company`, `read_draft`, `insert_draft`, `update_draft`; actualizaciones reciben revisión y retornan fila o None, nunca commit propio.

- [ ] Escribir tests `test_company_and_agent_draft_rls`, `test_draft_fk_rejects_other_tenant`, `test_draft_compare_and_swap`: tenant A/B, admin scoped A no lee/escribe B, app/anon sin acceso, mismo revision solo un UPDATE exitoso, rollback preserva estado.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_configuration.py -v` en base desechable y observar RED por contrato/tabla ausente, no por preparación del entorno.
- [ ] Consultar changelog/docs Supabase actuales; descubrir CLI con --help. Crear migración aditiva y repositorio; constraints JSON/revision, FK, grants/RLS anteriores. No efectuar backfill automático ni cambiar tablas existentes.
- [ ] Ejecutar tests anteriores: PASS; inspeccionar políticas y privilegios reales, advisors locales disponibles y ensayo de migraciones desde cero en proyecto desechable. Registrar limitaciones de entorno; no reiniciar otros proyectos.
- [ ] Commit acotado `feat: add isolated per-agent configuration storage`.

## Task 2: B2 — Servicios administrativos y concurrencia

**Interfaces:** consume B1; produce modelos, servicio y rutas definidos arriba. Validación pura reporta campos incompletos y blockers de `onboarding_projection.projection_blockers`, no compila ni congela conocimiento.

- [ ] Añadir tests `test_agents_keep_independent_drafts`, `test_save_does_not_change_published_snapshot`, `test_concurrent_save_returns_conflict`, `test_company_refresh_is_explicit`, `test_audit_failure_rolls_back_save`, `test_invalid_model_and_extra_fields_rejected`, `test_read_never_creates_draft`, `test_existing_company_profile_created_with_revision_zero`, `test_knowledge_edit_requires_fresh_review`, `test_tools_cannot_be_enabled_through_draft_put` y creación empresa/agente sin bindings. Assert tenant/agente correctos, snapshot/digest/binding intactos, revisión una vez, eventos sin texto sensible y errores seguros.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_configuration.py -v`: observar RED de rutas/servicios faltantes.
- [ ] Implementar módulos y registro de router; validar pertenencia antes de mutar, crear instancia con repositorio actual, aplicar compare-and-swap y auditoría. Errores de unicidad slug se traducen a409 sin SQL. No permitir escritura de secciones de herramientas desde B.
- [ ] Repetir tests: PASS. Ampliar proyecciones del workspace con datos estructurados del borrador y revisión propia; no mezclar con versión publicada. Leer sin fila conserva comportamiento de A. Datos compartidos se actualizan mediante acción explícita.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_workspace.py apps/backend/tests/integration/test_agent_configuration.py -v`: PASS; commit `feat: expose revisioned agent configuration services`.

## Task 3: B3 — Importación explícita del borrador heredado

**Interfaces:** consume B1/B2 y OnboardingRepository.read(); produce LegacyConfigurationImportService y ruta anterior. La configuración del asistente viejo permanece intacta y continúa su propia revisión; después de importar, sus cambios no se reflejan automáticamente en el borrador nuevo.

- [ ] Escribir tests `test_import_targets_only_selected_instance`, `test_ambiguous_import_is_rejected`, `test_repeated_import_is_idempotent`, `test_import_rejects_stale_source_and_profile`, `test_import_preserves_legacy_and_published_data`, `test_import_never_overwrites_edited_draft`. Fixtures con dos agentes, candidatos vinculados/desvinculados, revisiones y perfiles diferentes. Assert solo una fila destino y ningún binding/candidato/publicación nuevo.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_configuration_import.py -v`: RED por importador ausente.
- [ ] Implementar transacción breve con locks en orden legado→perfil→borrador, verificar revisión/origen/destino y asociación exacta. Campos nuevos sin origen quedan vacíos, no parsear prompt. Conflictos no pierden ediciones ni producen auditoría de éxito.
- [ ] Repetir tests: PASS; ensayar importación, segundo intento y rollback transaccional en base desechable. Documentar recuperación: deshabilitar nuevo editor y volver al antiguo; conservar datos importados, no generar un DROP como rollback.
- [ ] Commit `feat: import legacy configuration into an explicit agent draft`.

## Task 4: B4 — Editor visual por empresa y agente

**Interfaces:** consume HTTP B2/B3; produce formularios y acciones autenticadas. `saveAgentConfiguration(previousState,formData)->ConfigurationActionState`; estado discriminado success/validation/conflict/error, conserva valores locales ante fallo. Comparación obtiene GET vigente sin sobrescribir el formulario.

- [ ] Escribir unit tests `configuration_actions_preserve_input_on_conflict`, `configuration_contract_rejects_unknown_models`, `configuration_forms_keep_active_and_draft_separate`, `configuration_tools_remain_unavailable`; añadir E2E dos agentes y revisión de empresa pendiente. Validar contratos desconocidos, no casteo ciego de JSON.
- [ ] Ejecutar Vitest de `agent-configuration` y el E2E nuevo: observar RED por editor ausente. Leer documentación instalada de Next para páginas/acciones/formularios antes de escribir TSX.
- [ ] Implementar editor oscuro/morado con secciones progresivas: Identidad, Conocimiento, Operación y Modelo; herramientas de solo lectura con motivo. Acciones servidor reutilizan callAuthenticatedBackend, validación UUID/revisión y autorización; no exponer tokens. Guardado explícito, no autosave ni navegación con pérdida silenciosa de texto.
- [ ] Habilitar Nueva empresa/Nuevo agente/Editar; ofrecer Importar configuración anterior solo como acción confirmada con instancia/origen visibles. GET no importa. Si falta perfil, guiar a crear/completar o importar, no generar por conveniencia.
- [ ] Implementar conflicto409 con aviso, conservar texto, Recargar para comparar y nueva revisión solo tras decisión explícita del usuario. Actualización de empresa muestra antes/después y confirmación antes de incorporar snapshot.
- [ ] Ejecutar unit/E2E: PASS; verificar teclado, foco, móvil390/desktop1440, nombres largos, fallo de guardado y recarga persistida. No llamada Meta/OpenAI real ni botón publicar activo.
- [ ] Commit `feat: add company and agent draft editors`.

## Task 5: B5 — Ensayo completo y documentación

**Interfaces:** integra B1–B4 y produce evidencia local/revisión; no autoriza instalación productiva.

- [ ] Añadir E2E `two_agents_edit_without_changing_live_version`, `conflict_keeps_unsaved_text`, `legacy_import_is_explicit`, `company_update_requires_acceptance`; probar reinicio/recarga con estado persistido backend en integración. No confundir fixture HTTP con ensayo de migración real.
- [ ] Ejecutar backend de configuración/importación/workspace/publicación/aislamiento en base desechable; ejecutar suite completa y registrar resultados íntegros. Separar fallos históricos ya conocidos de A; no llamar verde a una selección filtrada.
- [ ] Ejecutar frontend typecheck, lint, test:unit, test:e2e y build con pnpm fijado; Ruff y Mypy de módulos nuevos. Inspeccionar capturas del editor y comprobar estados de error accesibles.
- [ ] Actualizar guía backend con mapa, flujo guardar/validar y diferencia borrador/candidato/activo; registrar pruebas, RLS, importación y recuperación en `docs/panel-operativo-entrega-b.md`.
- [ ] Solicitar una revisión independiente del cambio completo conforme executing-plans; resolver importantes con test RED→GREEN y deferir menores explícitamente. No mezclar código sucio anterior.
- [ ] Presentar editor local para aprobación. Producción exige propuesta de migración respaldada, ensayo de recuperación y autorización vigente separada. Plan C se redacta tras aceptación de B; no abrir publicación desde el editor nuevo todavía.

## Autorrevisión y puerta de ejecución

Cobertura de B: identidad compartida e independiente→B1/B2; concurrencia/auditoría→B2/B4; migración explícita y recuperación→B3; UI editable→B4; pruebas y aceptación→B5. Capacidades, integraciones operables, test interactivo y publicación siguen en C; no se omiten del producto ni se prometen aquí. Interfaces usan siempre tenant/instancia/revisión; el runtime sigue leyendo AgentSpec publicado, no estas tablas.

Estado: plan preparado para revisión de Daniel. No se ha implementado B ni aplicado esta migración. Conservar método nativo ya elegido; esperar aprobación de este plan antes de programar.
