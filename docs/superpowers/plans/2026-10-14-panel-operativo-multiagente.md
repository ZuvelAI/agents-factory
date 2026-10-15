# Panel operativo multiagente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir el recorrido técnico por un panel operativo legible por empresa y agente, preservando el agente de Zuvel y sus conversaciones.

**Architecture:** Tres entregas separan lectura/presentación, configuración independiente por agente y operación/publicación. Se conservan servicios y controles existentes; no se reconstruye el runtime ni se migra de hosting. Este documento define la secuencia y el plan ejecutable de la primera entrega; las siguientes tienen límites y criterios, pero requieren sus propios planes antes de programarse.

**Tech Stack:** Next.js/React/TypeScript, FastAPI/Python, PostgreSQL/Supabase, workers y Redis existentes; Vitest, Playwright y pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-panel-operativo-multiagente-design.md` (aprobado por Daniel).

## Global Constraints

- El panel es interno para Daniel y administradores autorizados en esta entrega.
- Empresa contiene agentes; cada agente tiene identidad estable, borrador propio, versiones, pruebas y publicaciones.
- Para esta primera entrega un número de WhatsApp tiene un único agente responsable activo.
- Guardar borrador conserva cambios sin afectar producción.
- Panel y operaciones realizadas con Codex usan los mismos servicios de aplicación, permisos, revisión esperada y auditoría.
- Las capacidades no implementadas aparecen como no disponibles, con motivo.
- No hay eliminación definitiva en esta entrega.
- Migración Railway, portal de clientes, nuevos conectores arbitrarios y orquestación multiagente sobre un número quedan fuera de alcance.
- No repetir Embedded Signup, regenerar credenciales ni cambiar el enlace de Zuvel durante tareas de presentación.
- Mantener dependencias bloqueadas: Node >=22, pnpm11.24.0 y Supabase CLI2.115.0 según manifiestos actuales. No instalar dependencias nuevas sin justificar necesidad.
- Preservar cambios previos sin mezclar commits. Trabajar en checkout aislado verificado; no crear otro por defecto.

## Review Focus

1. Un número sano sin mensajes no equivale a desconectado: prueba de estado independiente del contador en A1.
2. Borrador renombrado frente a versión publicada: probar etiquetas inequívocas y datos separados en A1/A3.
3. Mensajes históricos sin agente conocido: probar atribución desconocida sin asignarlos al agente actual en A4.
4. Clientes o agentes con nombres iguales: probar navegación por UUID y rechazo de acceso cruzado en A1/A2.
5. Uso móvil, teclado y fallo parcial del backend: probar foco, diseño adaptable y estados de error sin conteos ficticios en A2/A5.

## Secuencia y límites de autorización

### Entrega A — Panel de lectura y navegación (plan ejecutable aquí)

Empresas, agentes, ficha resumida y conversaciones. Datos reales, estados honestos,
tema aprobado y detalle progresivo. No cambia esquemas, configuración ni runtime.
Acciones de edición que aún no estén implementadas no se presentan como activas;
se conserva un acceso explícito a la administración anterior para recuperación.

### Entrega B — Configuración independiente por agente (plan posterior)

Crear borrador por instancia; identidad compartida de empresa y configuración
propia del agente; edición de nombre, tono, instrucciones, conocimiento, políticas
y modelo. Contratos identifican siempre tenant_id y agent_instance_id. Cambios
simultáneos requieren expected_revision y devuelven conflicto, no última escritura.
Migración aditiva, idempotente y recuperable del borrador heredado hacia la instancia
correcta; ensayo en base desechable y aprobación de migración productiva aparte.
No copiar la configuración heredada a todos los agentes. No borrar tablas.

Salida verificable: dos agentes del mismo tenant pueden editarse y probarse sin
afectarse ni modificar el snapshot activo. Configuración publicada y borrador
tienen proyecciones y versiones distintas. La creación de empresas/agentes usa
servicios autorizados, nunca crea conexiones o publica de forma implícita.

### Entrega C — Herramientas, publicación y operación (plan posterior)

Adaptar evidencia, pruebas y publicación al borrador por instancia; editor de
capacidades/consentimientos de conexiones realmente soportadas; prueba interactiva
sin efectos externos y marcada como simulada cuando corresponda. Confirmación de
número destino; revisión exacta y rollback validado; pausa/archivo con control de
trabajo en curso; auditoría visible y ajuste de navegación final.

Salida verificable: flujo editar→probar→revisar→publicar para dos agentes; un agente
por número, conexión existente preservada; permisos por agente sobre conexiones
compartidas; pruebas vencidas o de otro agente rechazadas. Un catálogo vacío se
muestra vacío. Conectores pendientes no se implementan bajo esta entrega sin un
diseño específico adicional. No afirmar costo total sin medición de sus fuentes.

No se ejecuta B/C con este documento únicamente: antes se redacta y revisa el
plan técnico específico de cada entrega, incorporando lo aprendido en A.

## Mapa de archivos de la entrega A

Backend, módulo `apps/backend/src/agents_factory/modules/agent_factory/`:
- Crear `workspace_models.py`: contratos exclusivamente de lectura.
- Crear `workspace_service.py`: proyección autorizada de empresas, agentes y estado.
- Crear `workspace_router.py`: endpoints PlatformAdmin, registrados en el montaje existente.
- Modificar el archivo real de ensamblado de routers tras identificarlo en A1.
- Modificar `modules/tenants/admin_router.py` solo si su lectura de conversaciones
  necesita filtros/paginación que no existan; conservar sus cambios previos.

Frontend `apps/control-plane/`:
- Crear `lib/agent-workspace.ts`: tipos y acceso server-side de lectura.
- Crear `components/agent-workspace/{company-card,agent-card,status-summary,agent-overview}.tsx`.
- Modificar `components/control-plane-navigation.tsx` y estilos existentes.
- Modificar `app/(authenticated)/page.tsx`, `tenants/page.tsx`, `conversations/page.tsx`.
- Crear `app/(authenticated)/tenants/[tenantId]/page.tsx` y
  `tenants/[tenantId]/agents/[agentId]/page.tsx`.
- Crear `tests/unit/agent-workspace.test.ts` y `tests/e2e/agent-workspace.spec.ts`.
- Crear backend `tests/integration/test_agent_workspace.py`.

## Contratos de lectura propuestos para A

Prefijo `/admin/agent-workspace`, protegido con PlatformAdmin. Paginación por
cursor opaco validado, limit1..50 (default20). UUID reales, no nombres como claves.

- GET `/companies?cursor=&limit=&query=` → `CompanyPage(items,next_cursor)`.
- GET `/companies/{tenant_id}/agents?cursor=&limit=` → `AgentPage(items,next_cursor)`.
- GET `/companies/{tenant_id}/agents/{agent_id}` → `AgentOverview` o404.

Modelos en workspace_models.py:
- `CompanySummary`: id:UUID, name:str, agent_count:int, agents:list[AgentSummary].
  agents es una vista previa limitada a3; agent_count es total real y no supone
  que esa vista previa sea el conjunto completo.
- `AgentSummary`: id:UUID, tenant_id:UUID, display_name:str,
  published_name:str|None, purpose:str|None, published_version_id:UUID|None,
  draft_version_id:UUID|None, has_pending_changes:bool|None,
  execution_status:Literal['unknown','unassigned','error','paused','serving'],
  status_checked_at:datetime|None, channel_accounts:list[ChannelSummary].
- `ChannelSummary`: account_id:UUID, display_number:str|None,
  connection_status:Literal['unknown','connected','disconnected','review_required'],
  checked_at:datetime|None. No inferir serving de PRODUCTION o HEALTHY solamente.
- `AgentOverview`: summary:AgentSummary, published:AgentConfigurationView|None,
  draft:AgentConfigurationView|None, unavailable_sections:list[str].
- `AgentConfigurationView`: name:str, purpose:str|None, tone:str|None,
  instructions:str|None, model:str|None, knowledge_summary:str|None,
  capabilities:list[FeatureSummary], integrations:list[FeatureSummary].
- `FeatureSummary`: key:str, label:str, availability:Literal['available','unavailable','unknown'],
  enabled:bool, reason:str|None. availability/enabled son distintos.
- `CompanyPage`/`AgentPage`: items:list[CompanySummary]/list[AgentSummary],
  next_cursor:str|None. Proyección nunca incluye secretos ni payloads de credenciales.

Servicio `AgentWorkspaceService(session, principal)` produce:
`list_companies(*,query:str|None,cursor:str|None,limit:int)->CompanyPage`,
`list_agents(*,tenant_id:UUID,cursor:str|None,limit:int)->AgentPage`,
`get_agent(*,tenant_id:UUID,agent_id:UUID)->AgentOverview`.
Usar TenantContext y repositorios existentes por tenant; no ampliar grants para
facilitar consultas. Leer snapshots y versiones exactas, no compilar borradores
ni crear instancias durante GET. Sin datos fiables, devolver None/unknown.

## Task A1: Lectura administrativa verificable

**Interfaces:** produce contratos anteriores; consume AgentSpecRepository,
AccountAgentBindingRepository y TenantRepository existentes.

- [ ] Identificar ensamblado real de routers y permisos existentes; registrar
  rutas/tablas usadas y riesgos en `docs/panel-operativo-inventory.md`, sin secretos.
- [ ] Escribir `test_agent_workspace.py`: fixtures dos tenants, nombres iguales,
  empresa0/1/4agentes; assert len(preview)==3 y agent_count==4; cuenta sana0mensajes
  no desconectada; versión publicada y borrador con nombres distintos conservados;
  get_agent(tenantB,agentA) devuelve404 y usuario no admin recibe401/403; GET no muta.
- [ ] Ejecutar `pytest apps/backend/tests/integration/test_agent_workspace.py -v`
  con TEST_DATABASE_URL/TEST_REDIS_URL de base desechable; comprobar fallo por
  contratos ausentes y no por entorno. Nunca apuntar pruebas a producción.
- [ ] Implementar modelos, servicio y router anteriores; registrar router usando
  el patrón actual. Estado serving solo si existe evidencia operacional suficiente;
  de lo contrario unknown. Listas paginadas y salida sin campos sensibles.
- [ ] Repetir comando: PASS; comprobar que token/secret/rawcredential no aparecen
  en JSON incluso con fixtures que los contengan. No añadir dependencias.
- [ ] Commit solo archivos de esta tarea: `feat: add read-only agent workspace`.

## Task A2: Empresas y navegación visual

**Interfaces:** consume CompanyPage/AgentPage; produce componentes
`CompanyCard({company:CompanySummary})` y `AgentCard({agent:AgentSummary})`.

- [ ] Escribir `agent-workspace.test.ts`: enlaces contienen UUID,0/1/varios agentes,
  faltan métricas→no se inventa0, texto español, nombres largos no rompen tarjetas.
- [ ] Ejecutar `pnpm --filter @agents-factory/control-plane test:unit -- agent-workspace`:
  fallo esperado por módulo ausente.
- [ ] Implementar `lib/agent-workspace.ts` sobre el cliente autenticado existente,
  tarjetas y rutas empresa/lista. Navegación de5entradas del diseño, rutas viejas
  conservadas con acceso avanzado explícito; ninguna redirección inicia signup.
- [ ] Implementar tema reutilizando fuentes/brand locales: oscuro/morado, foco
  visible y estados loading/error/vacío. No incluir crear/publicar como botón
  operativo hasta que B/C tengan contrato; explicar disponibilidad.
- [ ] Repetir Vitest: PASS; crear Playwright para fallo parcial, teclado, ancho
  390/1440px y enlace de dos empresas homónimas; ejecutar ese spec: PASS.
- [ ] Commit acotado: `feat: simplify company and agent navigation`.

## Task A3: Ficha del agente con activo y borrador separados

**Interfaces:** consume AgentOverview; produce
`AgentOverviewPanel({overview:AgentOverview})` en agent-overview.tsx.

- [ ] Añadir tests unitarios: instrucciones vacías, sin versión activa, cambio
  pendiente, capacidades vacías, integración UNAVAILABLE con reason. Assert campos
  publicados nunca toman texto del borrador y un conector futuro no se marca activo.
- [ ] Ejecutar Vitest filtrado y comprobar RED por nueva vista ausente.
- [ ] Implementar ficha y secciones desplegables: identidad, conocimiento,
  capacidades, integraciones, operación/modelo. Etiquetas de procedencia/versiones;
  sin botones falsos, secretos ni promesas de ingestión de PDF/URL automática.
- [ ] Ejecutar Vitest y Playwright de ficha: PASS, teclado y foco conservados al
  abrir/cerrar secciones, URL tenant/agente ajeno denegada por servidor.
- [ ] Commit acotado: `feat: show published agent overview and pending changes`.

## Task A4: Conversaciones filtradas y atribución honesta

**Interfaces:** reutiliza lectura administrativa actual; filtros tenant_id,
agent_id, account_id, cursor y limit. Un filtro de agente usa evidencia persistida
de selección/versión del mensaje, nunca el binding actual como atribución histórica.

- [ ] Añadir backend tests en `test_conversation_read_admin.py`: historial sin
  selección→unknown, cambio de binding no cambia atribución vieja, filtro tenant
  cruzado rechazado, paginación sin mensajes repetidos; filtros no mutan historial.
- [ ] Ejecutar pytest de ese archivo y registrar RED del filtro/atribución faltante.
- [ ] Ampliar lectura existente sin reemplazar cambios previos. Si la atribución
  actual no es recuperable, devolver unknown y no incluirla en filtro de agente.
- [ ] Añadir pruebas frontend en `tests/unit/conversations.test.ts`: enlaces
  conservan filtros; vacío distinto de desconectado; sin envío manual inexistente.
- [ ] Implementar lista/detalle con fechas, dirección, entrega y contexto autorizado;
  polling acotado con cancelación al navegar, sin descargar todo el historial.
- [ ] Ejecutar pytest/Vitest anteriores y Playwright flujo empresa→agente→conversación:
  PASS. Confirmar que otra empresa no aparece en respuesta ni DOM.
- [ ] Commit acotado: `feat: scope conversation views to company and agent`.

## Task A5: Verificación integrada y entrega sin producción

**Interfaces:** integra A1–A4; produce evidencia y guía de revisión de la entrega A.

- [ ] Añadir Playwright:0/1/varios agentes; API caída/reintento; nombres largos;
  móvil/desktop; volver y filtros; vista publicada/borrador; deep links históricos.
- [ ] Ejecutar primero el caso nuevo y demostrar RED ante una regresión controlada
  del fixture, restaurarla y comprobar GREEN. No romper producto para simular RED.
- [ ] Ejecutar `pnpm --filter @agents-factory/control-plane typecheck`, `lint`,
  `test:unit` y `test:e2e`; pytest de workspace/conversaciones/publicación y
  aislamiento en base desechable. Registrar fallos históricos separados, no
  presentar una selección filtrada como suite completa.
- [ ] Revisar captura real del navegador frente a referencia visual. Verificar
  contraste/foco y no depender solo de screenshots para controles interactivos.
- [ ] Preparar revisión independiente según método de ejecución elegido y resolver
  hallazgos antes de afirmar completitud. Registrar resultados reales y archivos
  en `docs/panel-operativo-entrega-a.md` y commit acotado de evidencia.
- [ ] Presentar la entrega local/preview para aprobación. No desplegar ni migrar
  datos. Solo tras aceptación escribir planes B/C con rutas, esquema y ensayos
  exactos; conservar recuperable el panel actual durante transición.

## Autorrevisión y puerta de ejecución

Cobertura: spec1–4→A1–A4; spec5–6→B/C; spec7→A1/A5 y operación enC;
spec8→secuencia/recuperaciónB/C; spec9→pruebas por entrega. A no pretende completar
el diseño entero. Los campos no soportados no se rellenan con configuración
heredada de otro agente. Cinco riesgos de Review Focus tienen casos explícitos.

Este plan no cambia la aprobación del diseño ni autoriza producción. Daniel
revisará el plan y elegirá ejecución directa o por subagentes antes de iniciar A.
