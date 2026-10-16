# Pruebas y publicación por agente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Método nativo conservado de A/B; una revisión independiente final.

**Goal:** Probar y revisar una revisión exacta del borrador de cada agente y publicar o recuperar una versión mediante confirmación explícita del número destino.

**Architecture:** Un backend y el runtime existente. Un adaptador de origen distingue el asistente heredado de los borradores por instancia; versiones compiladas, conocimiento congelado, outbox, resultados, revisiones y bindings se reutilizan. La preparación, prueba, revisión y publicación son operaciones independientes y auditadas; ninguna guarda configuración en el chat de Codex.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, PostgreSQL/Supabase, worker existente, Next.js/React/TypeScript, pytest/Vitest/Playwright. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-14-panel-operativo-multiagente-design.md`. Antecedentes implementados localmente: `docs/panel-operativo-entrega-a.md`, `docs/panel-operativo-entrega-b.md`; HEAD previo `bbc54fd`.

## Global Constraints

- El panel es interno para Daniel y administradores autorizados en esta entrega.
- Empresa contiene agentes; cada agente tiene identidad estable, borrador propio, versiones, pruebas y publicaciones.
- Guardar borrador conserva cambios sin afectar producción.
- Panel y operaciones realizadas con Codex usan los mismos servicios de aplicación, permisos, revisión esperada y auditoría.
- Un número de WhatsApp tiene un único agente responsable activo. No repetir Embedded Signup ni modificar credenciales, webhooks o coexistencia.
- La prueba interactiva no envía mensajes a WhatsApp ni ejecuta herramientas con efectos externos. En C no se habilitan herramientas; la UI lo explica.
- Conservar aislamiento, inmutabilidad, evidencia de digests y rollback validado. No elegir agente, cuenta o candidato por primera fila.
- No hay eliminación definitiva en esta entrega. Conservar panel anterior y cambios ajenos ya presentes.
- No desplegar ni aplicar migraciones productivas. No migrar Railway ni limpiar tablas.
- Node >=22, pnpm11.24.0, Supabase CLI2.115.0. No actualizar herramientas.
- Backend organizado en contratos, rutas delgadas, servicios, repositorios SQL y proyecciones puras. No crear un segundo servidor/runtime.
- Daniel autorizó reutilizar la misma clave de OpenAI que utiliza Zuvel, sin modificarla ni crear proyecto/clave nuevos. No imprimirla, copiarla a Git ni reemplazar configuración productiva. Las verificaciones automatizadas usan runtime falso; ensayo con API real se propone aparte con alcance y consumo limitados.

## Review Focus

1. Se edita agente o empresa mientras termina una prueba: conservar resultado histórico, pero impedir aprobar/publicar evidencia obsoleta (C2/C3).
2. Dos agentes comparten revisión numérica o conocimiento: nunca reutilizar candidatos, pruebas o aprobación del otro agente (C1/C3).
3. Doble clic, timeout o reentrega del worker: un resultado persistido por solicitud; no repetir escrituras ni afirmar que hay exactamente una llamada externa tras una caída (C2/C4).
4. Reasignación concurrente de un número: CAS de binding y confirmación del agente reemplazado; perdedor devuelve409 sin publicación parcial (C3/C4).
5. Resultado incompleto, preview o fallo del modelo: no satisface quality gate, no se presenta como prueba aprobada ni dispara fallback genérico (C2/C3).

## Alcance y decisiones para revisión

C incluye preparación por instancia, escenarios existentes, conversación de prueba aislada, revisión humana, publicación y rollback. Capacidades/conectores nuevos, habilitación efectiva de integraciones, pausa global/archivo y envío humano desde el panel son entregas posteriores con sus propios planes. Sus controles siguen deshabilitados con motivo; C no los declara terminados.

Los datos compartidos deben estar incorporados antes de preparar, aprobar o publicar. Si cambió `company_profiles.revision`, devolver409 `company_snapshot_stale`; no incorporar automáticamente ni publicar un snapshot empresarial antiguo por accidente.

Una prueba interactiva ayuda a evaluar respuestas, pero **no sustituye** los seis escenarios actuales y la aprobación humana. Los chequeos actuales son técnicos; no demuestran por sí solos corrección factual, tono ni ausencia de alucinaciones. La persona revisa las respuestas exactas.

No se cambia el catálogo de modelos ni sus parámetros. Se usa el modelo guardado en el candidato, no el modelo de este chat. Se conservan GPT-5.6 Luna/GPT-6 Luna y razonamiento low ya soportados por el proyecto.

## Inventario verificado y mapa de archivos

Actualmente `PanelPublicationService.prepare_candidate()` elige instancia desde candidatos por empresa; `PublicationEvidenceService` y `PersistedPanelQualityGate` comparan revisiones de `tenant_onboarding_configs`. No conectar el editor nuevo directamente a esas rutas sin adaptar el origen.

La preparación reutiliza `ApprovedKnowledgeRepository.freeze`, `project_onboarding`, `AgentSpecRepository.create_draft`, compilación/promoción y lifecycle. La creación inicial usa la instancia existente, con `based_on_version_id=None`, que el repositorio ya soporta; no crear otra identidad.

Backend, bajo `apps/backend/src/agents_factory/modules/agent_factory/`:
- Crear `publication_source.py`: contratos y resolución tipada LEGACY/AGENT_CONFIGURATION, actualidad y locks del origen; sin proveedor.
- Crear `workspace_publication_models.py`, `workspace_publication_repository.py`, `workspace_publication_service.py`, `workspace_publication_router.py`: contratos, SQL, coordinación y rutas por instancia respectivamente.
- Crear `configuration_projection.py`: conversión pura de snapshot empresarial y configuración editable a AgentSpec; propósito incluido explícitamente en instrucciones del candidato.
- Crear `publication_preview.py`: validación de conversación sintética y ejecución sin herramientas mediante AgentRuntime.
- Modificar `publication_evidence.py`: alojar WorkspacePublicationEvidenceService, delegar actualidad al origen y distinguir SCENARIOS/PREVIEW antes de interpretar resultados o aprobar.
- Modificar `publication_service.py` y `publication_router.py`: mantener contratos heredados; excluir pruebas/candidatos nuevos de sus listados y decisiones por defecto.
- Modificar `main.py`: registrar nuevas rutas con PlatformAdmin y errores422 sanitizados.
- Modificar `workers/agent-worker/src/agent_worker/publication_jobs.py`: seleccionar suite o preview por tipo persistido, comprobar integridad y guardar resultado del tipo correcto.
- Ampliar `workspace_repository.py`/`workspace_projection.py`: versión activa por cuenta, candidato y cambios pendientes sin confundirlos.

Frontend, bajo `apps/control-plane/`:
- Crear `lib/workspace-publication.ts`: contratos estrictos y lecturas autenticadas server-side.
- Crear `components/agent-workspace/publication-actions.ts`, `agent-testing-panel.tsx`, `agent-preview.tsx`, `agent-publication-confirmation.tsx`.
- Crear `app/(authenticated)/tenants/[tenantId]/agents/[agentId]/test/page.tsx`.
- Modificar `agent-configuration-form.tsx` y `agent-overview.tsx`: enlaces a prueba de borrador guardado e historial; conservar protección de cambios sin guardar.
- Crear pruebas unitarias y E2E de publicación por instancia con fixture HTTP sintética separada del ensayo real de DB/worker.

## Persistencia aditiva

Crear migración mediante `supabase migration new workspace_agent_publication` al ejecutar C1, sin inventar timestamp ni modificar migraciones previas.

Una tabla nueva `workspace_agent_candidates`: tenant_id, agent_instance_id, draft_revision>0, company_revision>0, source_digest, code_digest, version_id, created_at. PK(tenant_id,agent_instance_id,draft_revision,code_digest); UNIQUE(tenant_id,version_id) y UNIQUE(tenant_id,version_id,agent_instance_id,draft_revision,company_revision,code_digest) para FK exacta de runs; FK compuesta a instancia y versión, incluyendo correspondencia de instancia. source_digest es SHA256 canónico de schema_version, purpose, configuración y snapshot de empresa; no contiene secretos ni texto adicional.

La revisión guardada incluye su snapshot empresarial; el candidato no referencia una fila mutable como si fuera histórica. El AgentSpec y el conocimiento congelado existentes conservan los contenidos exactos; no duplicar todo el borrador en la tabla nueva. Candidato append-only, trigger impide UPDATE/DELETE. FORCE RLS; admin SELECT/INSERT scoped; app SELECT scoped para worker; sin acceso anon/authenticated/service_role/PUBLIC. No conceder al runtime acceso a perfiles/borradores.

Extender `agent_publication_test_runs` sin reescribir evidencia antigua:
- `source_kind` LEGACY/AGENT_CONFIGURATION, default LEGACY.
- `agent_instance_id`, `draft_revision`, `company_revision` opcionales solo para origen nuevo; `onboarding_revision` pasa a admitir null únicamente con origen nuevo.
- `run_kind` SCENARIOS/PREVIEW default SCENARIOS; `input_messages` JSON array solo PREVIEW.
- `requested_by` UUID y `request_key` UUID, null en histórico; UNIQUE(tenant_id,requested_by,request_key) para nuevos comandos.
- CHECK exige exactamente los campos de cada origen y tipo; FK compuesta del origen nuevo al candidato exacto, incluida versión/revisiones/código. No asignar revisiones ficticias al legado.

Reutilizar resultados inmutables en `agent_publication_test_results`, validando por run_kind: SCENARIOS -> CandidateTestResult existente; PREVIEW -> PreviewResult. Reviews solo admiten SCENARIOS. `PersistedPanelQualityGate` filtra explícitamente tipo, origen, run_id y actualidad. Mantener TTL actual24h; índices por tenant/agente/fecha para historial y límites. Actualizar matriz explícita de roles/tabla; un test de catálogo no puede relajarse para ocultar tablas nuevas.

## Contratos y operaciones

Base `/admin/agent-workspace/companies/{tenant_id}/agents/{agent_id}/publication`, siempre PlatformAdmin y alcance por instancia:
- GET vacío -> `WorkspacePublicationState`: draft_revision, company_revision, blockers, candidates, runs, accounts, bindings, rollback_targets; listas paginadas por cursor, límite20, máximo100. Ausencia de datos no crea candidato.
- POST `/candidates` `{expected_revision,expected_company_revision}` -> `WorkspaceCandidateView` con version, source metadata/digest. Preparación idempotente para mismo agente/revisión/código.
- POST `/candidates/{version_id}/tests` `{expected_revision,request_key}` ->202 `WorkspaceRunView` SCENARIOS.
- POST `/candidates/{version_id}/preview` `{expected_revision,request_key,messages}` ->202 WorkspaceRunView PREVIEW. messages:1..20 roles user/assistant alternados, primero/último user, cada texto1..2000 caracteres, total<=20000; sin tools/system/client-selected model.
- GET `/tests/{run_id}` -> WorkspaceRunView con source_kind, run_kind, revisión, digests, expiración, pending/completed/failed/expired, is_current y resultado tipado.
- POST `/tests/{run_id}/review` `{expected_revision,approved,confirm_review}` -> WorkspaceRunView; confirm_review=true obligatorio para aprobar, fallo/incompleto/preview no aprobable.
- POST `/publish` `{expected_revision,version_id,test_run_id,whatsapp_account_id,expected_binding_revision,expected_current_agent_id,confirm_publish:true}` -> AccountAgentBinding. expected_current_agent_id null solo si cuenta sin binding.
- POST `/rollback` `{whatsapp_account_id,target_version_id,expected_binding_revision,confirm_rollback:true}` -> AccountAgentBinding; destino previamente publicado de la misma instancia y compatible con código, nunca elegir por número de versión ambiguo.

Todos los comandos: extra=forbid, UUID/revisiones tipados, auditoría sin prompts/respuestas, request correlation preservada.404 para agente/versión/run/cuenta fuera de alcance;409 para revisiones, origen o binding obsoletos;422 contrato seguro;429 límite de solicitudes con Retry-After. No hacer reintento ciego de publicación en frontend.

Servicios nuevos:
- `WorkspacePublicationService(session,context,code_digest,compatible_versions)` expone `read_state(agent_id,cursor,limit)`, `prepare(agent_id,expected_revision,expected_company_revision)`, `publish(agent_id,**PublishWorkspaceRequest)`, `rollback(agent_id,**RollbackWorkspaceRequest)`.
- `PublicationSourceResolver(session,context).resolve(version_id,lock=False)->PublicationSource` y `.require_current(source,expected_revision)`; devuelve revisiones exactas por origen, no busca la primera fila. El worker recibe integridad del candidato, no permisos para leer el borrador actual.
- `WorkspacePublicationEvidenceService(session,context,code_digest)` expone `request(agent_id,version_id,request)`, `read(agent_id,run_id)`, `review(agent_id,run_id,request)`; `request` discriminado SCENARIOS/PREVIEW y único request_key. Clave repetida con contenido distinto409.
- `run_candidate_preview(spec:AgentSpec,messages:tuple[TurnMessage,...],runtime:AgentRuntime)->PreviewResult` usa snapshot compilado, tools=(), metadatos sintéticos; salida<=8000, tool_calls no vacías -> fallo seguro. No invocar AgentTurnService ni tablas de conversaciones/mensajes reales.

Lock order nuevo: perfil -> borrador -> cuenta destino -> versión/instancia. Preparar/bind/revisar y auditar en transacciones cortas sin llamadas externas. Revalidar origen después de adquirir locks; no usar is_current calculado antes del lock. Los servicios no hacen commit propio.

Tests en cola: mismo topic existente `agent.publication.test`; request persiste run y outbox atómicamente. Worker comprueba payload/tenant/run/digests/tipo antes de llamar modelo. Su lectura usa `read_run(run_id,check_current=False)`: no consulta perfiles/borradores ni calcula actualidad editable; esa opción solo es interna, nunca parámetro HTTP. Aprobación/publicación siempre recalculan actualidad con rol administrativo. Mantener exclusión de ejecución existente por run; no introducir llamadas en acciones Next. Límite por tenant/agente, bajo lock transaccional:30 previews y6 suites por hora; solicitudes duplicadas no consumen cupo. Máximo una solicitud pendiente por tipo/candidato; mostrar y reutilizar run pendiente, no esconder timeout con otro trabajo. TTL permite volver a solicitar si expiró; no reclamar exactamente-una-vez para consumo externo tras caída.

## Task 1: C1 — Origen y preparación exacta

**Interfaces:** produce PublicationSource, WorkspaceCandidateView, WorkspacePublicationRepository y prepare; consume ConfigurationRepository, ApprovedKnowledgeRepository y AgentSpecRepository existentes.

- [ ] Añadir `tests/integration/test_workspace_publication_candidates.py`: dos agentes con revision1 generan candidatos de su propia instancia; misma solicitud repite mismo version_id; primer candidato conserva instancia y base=None; propósito llega al snapshot; borrar/editar candidato falla; RLS A/B/app y FK cruzadas fallan. Preparar no cambia binding ni legado.
- [ ] Ejecutar tests en base desechable, observar RED por contratos faltantes. Consultar changelog/docs Supabase y CLI help antes de la migración.
- [ ] Implementar migración, repositorio y resolución por origen, proyección pura y prepare. Reusar validación B más requisitos del compilador, incluido código verificable; conocimiento congelado una vez. Borrador incompleto -> bloqueadores seguros, no candidato parcial.
- [ ] Ejecutar casos anteriores y regresiones de importación/publicación heredada, incluyendo preparación concurrente y auditoría fallida -> rollback total; rutas heredadas rechazan fuente nueva aunque coincidan revisiones numéricas. PASS. Commit acotado `feat: prepare exact per-agent publication candidates`.

## Task 2: C2 — Evidencia y prueba interactiva aislada

**Interfaces:** produce WorkspaceRunView y PreviewResult `{response:str|null,error_code:str|null}` validado; servicio evidence y run_candidate_preview arriba. Consume candidato C1 y worker/runtime existentes.

- [ ] Añadir `tests/integration/test_workspace_publication_evidence.py`, `tests/unit/test_publication_preview.py` y `workers/agent-worker/tests/test_workspace_publication_jobs.py`: suite6 escenarios; preview no aprobable; cambios durante ejecución conservan resultado pero invalidan actualidad; error/tipo incorrecto no satisface gate; historial ajeno404; request_key duplicado mismo run, contenido distinto409; límites30/6 y expiración.
- [ ] Ejecutar y observar RED; implementar expansión de runs y adaptadores con resultado discriminado. No cambiar semántica de respuestas legacy ni conceder lectura de borradores al worker. Validar vigencia bajo lock al aprobar y exigir revisión explícita de respuestas.
- [ ] Probar worker con runtime falso que registra tools y metadatos: tools vacío, tenant/agente/version exactos, sin filas de mensajes/outbound/bindings. Reentrega después de resultado no llama de nuevo al runtime; fallo de auditoría no deja revisión aprobada.
- [ ] Ejecutar suite de publicación antigua/nueva y worker: PASS; commit `feat: test agent candidates without external tool effects`.

## Task 3: C3 — Publicación y rollback por instancia

**Interfaces:** produce nuevas rutas GET/POST y publish/rollback; consume C1/C2 y AccountAgentBindingRepository/AgentSpecLifecycleService. Reutilizar gate persistido, no saltarlo.

- [ ] Añadir `tests/integration/test_workspace_agent_publication.py`: publicar exige suite vigente aprobada del candidato exacto; previews, otro agente, otra revisión, evidencia vencida, código/digest distinto y cuenta ajena se rechazan. Empresa cambiada requiere incorporar/pruebas nuevas.
- [ ] Observar RED; implementar state y operaciones con confirmaciones backend, binding_revision y expected_current_agent_id. Mostrar reemplazo explícito cuando número atiende con otra instancia; no reasignación implícita.
- [ ] Añadir tests concurrentes reales: dos publicaciones al mismo número -> una gana, otra409; dos reviews -> una decisión inmutable; falla auditoría -> versión/binding/historial íntegramente revertidos. Rollback solo a versión publicada de la misma instancia/código compatible y revisión vigente. No restaurar el borrador al hacer rollback.
- [ ] Ejecutar C1–C3 y regresiones de lifecycle/provider/tenant isolation: PASS; commit `feat: publish reviewed per-agent versions with validated rollback`.

## Task 4: C4 — Panel de pruebas, confirmación e historial

**Interfaces:** consume rutas C3; produce página /test y acciones autenticadas por tenant/agente. Formularios con estado pending/success/conflict/error; datos guardados y activos diferenciados.

- [ ] Añadir `tests/unit/workspace-publication.test.ts`, `workspace-publication-actions.test.ts`, `tests/e2e/workspace-publication.spec.ts`: contratos tipados, conservación del texto, dos agentes independientes, edición invalida prueba, permisos/conflictos, sin selección automática de cuenta. Observar RED antes del TSX.
- [ ] Leer guías Next instaladas; implementar secciones progresivas Preparar -> Probar -> Revisar -> Publicar. Vista previa rotulada «Prueba aislada · no envía WhatsApp · consume API»; escenarios muestran5 llamadas al modelo más control humano local, sin prometer costo monetario exacto.
- [ ] Preparar requiere borrador guardado; cambios locales disparan guard de B y no se publican implícitamente. Preview limpia historial al cambiar candidato. Pending protege botones; polling cada2s solo visible y pendiente, máximo2min, luego botón Consultar estado; no reiniciar trabajo al agotarse espera.
- [ ] Confirmación muestra empresa, agente, número, versión destino y versión/agente reemplazados; checkbox obligatorio sin preselección. Publicación no automática al aprobar. Historial permite comparar snapshot activo/destino y confirmar rollback con revisión exacta.
- [ ] Ejecutar unit y E2E completos, teclado/móvil390/desktop1440, errores y estado pendiente recuperable; PASS. Commit `feat: add isolated agent testing and explicit publication controls`.

## Task 5: C5 — Cierre y aceptación local

**Interfaces:** integra C1–C4; produce evidencia y documentación, no autorización de despliegue ni de llamadas de pago.

- [ ] Ensayar migración desde cero y upgrade de base sintética con datos legacy; verificar todos sus digests/resultados/bindings intactos. Reversión operacional desactiva nueva UI/rutas; no DROP ni eliminación de historial.
- [ ] Ejecutar backend completo y workers en entorno desechable, sin exclusiones; matriz de roles nueva y advisors locales disponibles. Registrar warnings/fallos reales, no extrapolar suites parciales.
- [ ] Ejecutar frontend test:unit, test:e2e, lint, typecheck, build; Ruff/Mypy de módulos nuevos. Capturas reales con datos sintéticos y verificación visual. Ninguna API externa en estas suites.
- [ ] Actualizar `docs/backend-guide.md` y crear `docs/panel-operativo-entrega-c.md`: mapa de origen->candidato->evidencia->revisión->binding, límites, recuperación y funciones aún no implementadas.
- [ ] Una revisión independiente final siguiendo método nativo; resolver hallazgos importantes con RED->GREEN, conservar cambios previos ajenos y presentar resultado a Daniel.
- [ ] Proponer por separado ensayo API real limitado con clave existente y acceso seguro disponible; informar máximo de llamadas antes de pedir autorización. No fabricar resultados si no hay credencial accesible. Producción exige instalación/migraciones respaldadas y aprobación expresa aparte.

## Autorrevisión y puerta de ejecución

Cobertura: múltiples agentes/candidatos exactos C1; pruebas aisladas y errores C2; aprobación, confirmación, concurrencia y rollback C3; claridad visual, preview y prevención de pérdida C4; compatibilidad y recuperación C5. Integraciones operables y pausa/archivo quedan explícitamente fuera de C, no fuera del producto. No se reutiliza la revisión empresarial como identificador de un borrador por agente.

Estado: plan preparado para revisión de Daniel. No implementado, sin migración creada/aplicada ni llamadas API efectuadas. Se conserva ejecución nativa; esperar aprobación de este plan antes de programar.
