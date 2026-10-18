# Captura de prospectos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, preserving the native method used in A/B/C. TDD per task and one independent final review. Steps use checkbox (`- [ ]`) syntax. Plan pending Daniel's review; no implementation authorization yet.

**Goal:** Registrar prospectos por interés comercial real, sin duplicados, habilitados por agente y visibles desde el panel y su conversación.

**Architecture:** Módulo `leads` dentro del backend existente. Herramientas internas preparan propuestas durante el turno; un servicio transaccional las valida y guarda junto con respuesta/outbox después de comprobar autoridad vigente. Perfiles WhatsApp, editor, publicación y workers existentes se reutilizan, sin CRM externo ni llamadas de clasificación adicionales.

**Tech Stack:** Python/SQLAlchemy, PostgreSQL17/Supabase RLS, runtime OpenAI Agents SDK existente, Next.js16/React19, pytest/Vitest/Playwright. Mantener dependencias fijadas; no instalar paquetes por esta función.

**Spec:** `docs/superpowers/specs/2026-10-18-captura-prospectos-design.md`, aprobada por Daniel, seguida de aprobación visual de lista/detalle. Referencia: `docs/design/prospectos-20261018.png`, maqueta ficticia, no producto instalado.

## Global Constraints

- «Un saludo no basta». «Los datos desconocidos quedan vacíos». Estado inicial único `NEW`, presentado como «Nuevo».
- Activación por agente, desactivada por defecto. Guardar/preparar/probar no publica.
- «No admite identificadores de otra empresa proporcionados por el modelo».
- «Nombre y usuario sirven para mostrar, no para fusionar registros ni autorizar acciones».
- «No se confirma “guardado” si la persistencia falló». Simulaciones nunca escriben prospectos reales.
- No tocar clave/modelo/conexión, borradores ajenos o publicaciones actuales; no ejecutar llamadas reales Meta/OpenAI en esta implementación local.
- No campaña, CRM, calendario, scoring, retrocaptura, Railway, eliminación o fusión destructiva.
- Checkout existente `codex/whatsapp-coexistence`: preservar todos los cambios sucios previos. Commits solo de archivos/hunks propios, nunca `git add .`.

## Review Focus

1. Teléfono y BSUID con mismos dígitos, alias que aparece después y dos capturas concurrentes: no mezcla ni duplicados (L1/L3).
2. Cita de asistente, mensaje de otro hilo, prompt injection o empresa inventada como evidencia: rechazo sin guardar ni confirmar (L1/L3).
3. Humano toma control o publicación cambia mientras responde el modelo: no captura ni confirmación obsoleta; reintento acotado (L3).
4. Negativa explícita seguida de interés desde otro agente/cuenta e historial truncado: supresión persistente y prevalente (L1/L3).
5. Modelo antiguo sin capacidad, evidencia de prueba heredada, error de API o un marcador simulado falsificado: compatibilidad sin habilitación ni aprobación indebidas (L2/L4).

## Inventario y decisiones cerradas

- `RuntimeToolRegistry` filtra por capacidad/permisos, pero el worker arranca vacío; no hay herramienta de prospectos implementada.
- `AgentTurnService` ejecuta el modelo y después vuelve a comprobar control antes de persistir respuesta; usar ese límite transaccional, no escribir dentro del handler SDK.
- `project_configuration` pasa por `OnboardingConfiguration`; el nuevo campo específico debe excluirse de esa validación heredada y proyectarse explícitamente después.
- `save_draft` rechaza cambios de herramientas; permitir solamente el campo nuevo, manteniendo el rechazo de conectores/capacidades anteriores.
- Preview rechaza todas las herramientas y suite exige seis resultados. Ampliar de forma versionada solo para simulación interna de esta capacidad, sin relajar controles de conectores.
- Contactos operativos existentes son perfil de canal, no un CRM ni identidad comprobada de persona. No modificar la semántica de agenda usada por la bienvenida.

## Persistencia mínima propuesta

Una migración aditiva generada durante L1 con CLI fijada (`supabase migration new lead_capture`), sin inventar timestamp. Cuatro tablas con responsabilidades distintas, no tablas por campo/servicio:

| Tabla | Responsabilidad y restricciones |
|---|---|
| `lead_subjects` | Identidad interna empresarial y `capture_suppressed`, fecha/referencia de negativa. Puede existir sin prospecto; no crear una oportunidad para guardar una negativa. UUID y `(tenant_id,id)` únicos. |
| `lead_subject_keys` | Alias PHONE o PROVIDER vinculados al subject. PHONE: teléfono E.164 explícito único por tenant; PROVIDER: ID opaco único por tenant/cuenta. FK compuesta a subject y cuenta; sin normalizar BSUID como teléfono. |
| `lead_prospects` | Ficha agregada, única `(tenant_id,subject_id)`, nombre/procedencia, empresa declarada opcional, intereses, resumen, NEW, conversación inicial/última y fechas. |
| `lead_capture_events` | Evidencia inmutable de captura/supresión/conflicto, mensaje/hilo/agente/versión, extractos acotados y cambios validados. Único `(tenant_id,inbound_message_id,operation)`; no transcript entero. Prospecto nullable en negativa/conflicto. |

FKs incluyen tenant y validan concordancia mensaje↔conversación↔cuenta y versión↔agente mediante servicio y relaciones existentes. Índices en FKs, `(tenant_id,updated_at,id)` de lista y `(tenant_id,agent_instance_id,...)` de atribución. Búsqueda acotada y parametrizada; sin extensiones nuevas inicialmente, medir con EXPLAIN en datos sintéticos antes de añadir índices de texto.

FORCE RLS en las cuatro tablas: contexto `app.tenant_id` y roles de aplicación/administración existentes. Revocar PUBLIC/anon/authenticated/service_role. SELECT/INSERT scoped; UPDATE solo campos mutables de subjects/prospects; keys/events append-only. No DELETE, reasignación de tenant, SECURITY DEFINER nuevo ni credencial privilegiada en runtime. Registrar las cuatro tablas en la matriz de aislamiento; no excluirlas de descubrimiento.

Resolución: adquirir locks consultivos de claves tipadas en orden lexical, dentro de la empresa. Una coincidencia de teléfono puede reutilizar subject entre cuentas. Un nuevo alias solo se vincula con evidencia explícita del proveedor del mensaje correspondiente; no basta nombre/usuario o teléfono propuesto por el modelo. Dos subjects ya existentes que entren en conflicto no se fusionan: devolver `IDENTITY_CONFLICT`, auditar y mostrar revisión pendiente. Ausencia de clave PHONE usa clave PROVIDER acotada a cuenta. Ausencia de ambas rechaza captura.

## Task 1: L1 — Persistencia, identidad y evidencia

**Files:** crear `apps/backend/src/agents_factory/modules/leads/{__init__,models,identity,repository,service}.py`; pruebas `apps/backend/tests/unit/test_lead_evidence.py`, `apps/backend/tests/integration/test_lead_capture.py`, ampliar `tests/security/test_tenant_isolation_matrix.py`; migración generada por CLI.

**Interfaces:**
- `LeadProposal`: extra forbid; `operation` CAPTURE/SUPPRESS; `evidence` 1–5 pares `{message_id:UUID,quote:str<=500}`; `service_interest:str|None<=300`, `need_summary:str|None<=2000`, `declared_name:str|None<=200`, `declared_company:str|None<=200`, `corrected_fields` subconjunto name/company/need_summary. SUPPRESS no admite datos comerciales.
- `TrustedLeadContext`: tenant, account, customer routing ref, conversación, inbound, agent/version y provider keys resueltos del servidor; no del argumento del modelo.
- `LeadCaptureService(session,context).apply(proposal, trusted, messages)->LeadCaptureOutcome`: RECORDED/SUPPRESSED/IDENTITY_CONFLICT/REJECTED; no commit propio.
- `LeadCaptureService.suppress(trusted,evidence)->LeadCaptureOutcome`; `LeadIdentityResolver.resolve(trusted)->LeadSubjectResolution`. Negativa ya persistida nunca se levanta por una propuesta CAPTURE.

- [ ] Escribir pruebas: `greeting_without_proposal_creates_nothing`, `two_messages_update_one_prospect`, `retry_does_not_repeat_event`, `two_accounts_same_phone_share_subject`, `numeric_bsuid_is_not_phone`, `alias_conflict_is_not_merged`, `foreign_tenant_and_message_rejected`, `assistant_quote_rejected`, `missing_values_preserved`, `explicit_correction_preserves_provenance`, `refusal_survives_later_capture`. Citas literales y expectativas independientes; concurrencia con dos transacciones reales. Observar RED antes de SQL/servicio.
- [ ] Ejecutar `pytest apps/backend/tests/unit/test_lead_evidence.py apps/backend/tests/integration/test_lead_capture.py -q` en base local aislada; debe fallar por función/esquema ausente.
- [ ] Implementar contratos, migración, repositorio y servicio. Resolver claves desde el evento original enlazado al mensaje, verificando cuenta/WABA/message_id; reutilizar normalización de perfil sin confiar en teléfonos inferidos. Datos explícitos exigen cita de usuario que contenga el valor, nombre de perfil solo como fallback. Resumen sintetizado se etiqueta como tal y conserva evidencia.
- [ ] En mismo timestamp, no sobrescribir dato explícito con perfil; intereses se acumulan. Clave idempotente depende de inbound/operación, no texto ni argumentos escogidos por el modelo. Máximo una captura por inbound; negativa prevalece si aparecen ambas operaciones.
- [ ] Reconstruir migraciones y ejecutar matriz completa, asesor de seguridad local, pruebas nuevas y suite backend completa: PASS sin exclusiones. Rechazo extranjero y fila inexistente deben ser indistinguibles.
- [ ] Commit local acotado: `feat: add tenant-scoped prospect capture persistence`.

## Task 2: L2 — Capacidad por agente, compilación y contratos compatibles

**Files:** crear `modules/leads/capability.py`; modificar `agent_factory/{configuration_models,configuration_service,configuration_projection,workspace_projection}.py`, `capabilities/{registry,service}.py`, `agent_factory/onboarding_projection.py` solo si la proyección lo necesita; pruebas `tests/unit/test_lead_capability.py`, `tests/integration/test_lead_configuration.py`.

**Interfaces:** `LeadCaptureConfiguration(enabled:bool=False)` opcional en el borrador, omitida del documento canónico si está desactivada y ausente antes. `LEAD_CAPTURE_MANIFEST` versión1.0.0; herramientas exactas `lead_capture.propose`, `lead_capture.suppress`. `lead_capture_enabled(snapshot)->bool` exige capacidad activa y ambas herramientas permitidas.

- [ ] Escribir RED: agente A habilitado/B apagado, guardar no publica, edición de conectores anteriores sigue422, configuración desconocida falla, JSON/digest de versiones heredadas permanece idéntico, operación interna ajena rechazada, capacidad activa sin permiso no obtiene herramientas.
- [ ] Ejecutar `pytest .../test_lead_capability.py .../test_lead_configuration.py -q`; observar fallos antes de contratos/proyección.
- [ ] Proyectar únicamente el flag al snapshot compilado: referencia manifest y dos permisos; no crear bindings CRM falsos. `CapabilityService` distingue un allowlist cerrado de operaciones internas de las operaciones de conectores; no eliminar validación general. Modelos y políticas existentes iguales.
- [ ] Mantener esquema heredado: excluir `lead_capture` antes de construir OnboardingConfiguration; aplicar adición explícita después. Diferenciar borrador habilitado de configuración publicada. Versiones nuevas cambian digest; versiones viejas no se reescriben.
- [ ] Ejecutar pruebas nuevas y existentes de configuración/publicación/compilación más suite completa: PASS; commit `feat: configure prospect capture per agent`.

## Task 3: L3 — Herramienta preparada y commit con autoridad vigente

**Files:** crear `modules/leads/{runtime_tools,turn_effects,privacy}.py`; modificar `runtime/{openai_adapter,turn_service}.py`, `workers/agent-worker/src/agent_worker/jobs.py`; `conversations/service.py` para la negativa en entrada, sin insertar prospectos; pruebas `tests/unit/test_lead_runtime_tools.py`, `tests/integration/runtime/test_lead_turn.py`.

**Interfaces:** `lead_tools_for_turn(turn:AgentTurnInput,simulation:bool)->tuple[RuntimeTool,...]` produce handlers puros: validan propuesta/evidencia en `turn.messages` y devuelven JSON PREPARED, sin repositorio. `LeadTurnEffects(session,context).apply(turn,result)->tuple[LeadCaptureOutcome,...]` solo interpreta operaciones propias autorizadas, nunca confía en un resultado SDK que diga «saved». `explicit_capture_refusal(text)->bool` es guard conservador de negativas directas, no clasificador de interés.

- [ ] RED con runtime falso: propuesta válida + respuesta + outbox + auditoría en una transacción; fallo de cualquiera revierte todo. Dos turnos simultáneos, reintento y takeover humano con barreras controladas. Cambio de binding durante modelo bloquea captura y confirmación; otro agente activo no hereda permiso. Ningún efecto se ejecuta dentro del handler SDK.
- [ ] RED de evidencia: incluir referencias de mensaje del servidor para esta capacidad en los items SDK, sin convertir texto del usuario en metadata. Rechazar citas falsas, UUID de otro hilo/assistant, valores inventados, más de5 citas, secretos, 2 capturas o herramienta no declarada. La misma clave no cambia por regenerar argumentos.
- [ ] RED privacidad: «No guardes mis datos como prospecto» persiste supresión aun sin crear prospecto; posterior interés desde otro agente con teléfono igual no la levanta. Una cita del asistente o ejemplo de esa frase no es negativa del contacto. Añadir variantes directas español/inglés y prueba con historial truncado. Mensajes ambiguos no habilitan captura por defecto.
- [ ] Ejecutar pruebas L3: deben fallar antes de conectar effects al turno.
- [ ] Construir herramientas por turno solo si L2 autoriza. No introducir sesiones globales mutables ni guardar handlers entre usuarios. Reusar SDK existente y su límite de llamadas; sin segundo clasificador. Instruir interés real, pedir datos opcionales naturalmente y no atribuir consentimiento de marketing.
- [ ] Después de la llamada del modelo adquirir orden estable: fence de dispatch existente → cuenta/binding (compatibles con publicación) → conversación → claves de subject. Releer permiso, versión exacta, control humano y negativa; solo entonces persistir efectos/respuesta/outbox. No mantener estos locks durante la llamada al modelo. Si cambia autoridad, abortar el turno y aplicar reintento limitado existente; no enviar una afirmación de captura descartada.
- [ ] Procesar negativas directas del mensaje entrante en la transacción de ingestión como preferencia de privacidad, no oportunidad comercial, y sin depender del historial LLM. Aplicar este guard cuando exista una versión publicada con lead_capture en la empresa o un subject histórico; no crear subjects en empresas que nunca usaron la función. No consultar borradores desde el runtime. El handler SUPPRESS cubre negativas semánticas cuando la capacidad está activa. Supresión gana a CAPTURE y no tiene reactivación automática ni borrado por el modelo.
- [ ] Evitar duplicar argumentos comerciales en trazas/auditorías genéricas: para estas herramientas, metadata registra operación/referencias/resultado, no todo el payload. Evidencia acotada vive en L1. No dar acceso al runtime a los borradores.
- [ ] Ejecutar suites completas, incluidos bienvenida, asteriscos, worker, reintentos y human-control: PASS; commit `feat: commit prospect capture atomically with agent turns`.

## Task 4: L4 — Simulación visible y evidencia de publicación

**Files:** modificar `apps/backend/src/agents_factory/modules/agent_factory/{publication_preview,publication_tests,publication_evidence}.py`, `workers/agent-worker/src/agent_worker/publication_jobs.py`, `apps/control-plane/components/agent-workspace/{agent-preview,agent-testing-panel}.tsx`; crear `apps/backend/tests/unit/test_lead_simulation.py`, `apps/backend/tests/integration/test_lead_publication.py`, `apps/control-plane/tests/unit/lead-simulation.test.ts`.

**Interfaces:** `SimulatedLeadProposal` con datos/evidencia validados y `simulated=True`; PreviewResult añade lista opcional `lead_proposals` sin romper respuestas anteriores. CandidateTestResult añade versión de resultado2 para candidatos con lead_capture y tres escenarios adicionales: `lead_interest`, `lead_no_interest`, `lead_refusal`. Resultado1/seis escenarios sigue representando versiones antiguas, no certifica una nueva capacidad.

- [ ] Escribir RED: preview positivo presenta propuesta sin tocar tablas; negativo no propone; solo herramientas internas permitidas, ningún conector externo. Retornar JSON `simulated=true` desde un handler no basta para autorizar writes. Un run viejo de seis escenarios no aprueba una versión habilitada; TTL/revisión/digest/código siguen siendo obligatorios.
- [ ] Implementar fábrica pura L3 en preview/suite, sin servicio/repositorio L1. Mantener límites, aislamiento y aprobación humana. Tres prompts: interés en cotizar una solución de la empresa (servicio específico puede quedar vacío), saludo sin intención de contratar, negativa explícita a registro. Las propuestas deben corresponder a mensajes reales del escenario.
- [ ] Nueve resultados al activar la capacidad: cinco escenarios actuales + tres comerciales + control humano. Esto implica ocho llamadas al modelo por suite real en vez de cinco; solo se ejecutarán con autorización posterior. Mostrar costo variable y simulación; mantener límites existentes de solicitudes/TTL. No ampliar automáticamente el presupuesto técnico del turno.
- [ ] Conservar resultados y previews heredados; controles de aprobación obtienen escenarios requeridos del snapshot congelado del run, no del borrador mutable. Fallos de generación no se presentan como ausencia de interés ni como verificación exitosa.
- [ ] Ejecutar tests locales con modelo falso y suite completa: PASS; commit `feat: preview and review simulated prospect capture`.

## Task 5: L5 — Panel aprobado y lecturas administrativas

**Files:** crear `modules/leads/{read_models,read_repository,admin_router}.py`; registrar router en `main.py`; crear `lib/leads.ts`, `app/(authenticated)/prospects/page.tsx`, `components/leads/{prospect-list,prospect-detail}.tsx`; modificar navegación, editor de agente, ficha de agente y conversation-log; crear `tests/integration/test_lead_reads.py`, `tests/unit/prospects.test.ts`, `tests/e2e/prospects.spec.ts`.

**Interfaces:** GET `/admin/agent-workspace/companies/{tenant}/prospects` con `agent_id`, `q`<=200, cursor y limit<=20; detalle `.../prospects/{id}`; relación de conversación `.../conversations/{id}/prospect` devuelve ficha mínima o null. Listar fuentes paginadas por prospecto, no todo su historial. Sin POST manual ni DELETE.

- [ ] RED de lecturas: auth401/403, scope404 para recurso/filtro/cursor extranjero, empresa seleccionada antes de buscar, mismo nombre en dos clientes, historial con dos agentes, búsqueda por nombre/teléfono/usuario/empresa declarada, selección fuera de primera página, datos corruptos/error no se convierten en lista vacía.
- [ ] RED UI: lista izquierda/detalle derecho, Nuevo, empresa declarada opcional, enlace exacto a conversación/filtros; no testimonios/métricas inventadas. Cadenas HTML escapadas, navegación teclado,390px/1440px, carga/error/vacío y aviso de identidad en conflicto/supresión. Fuentes históricas conservan agente/version originales.
- [ ] Implementar tarjeta «Guardar prospectos» en editor con L2: habilitar solo borrador, guardar con revisión esperada, advertir cambios sin guardar. Ficha publicada refleja snapshot, no interruptor optimista. Ningún botón desconecta canal ni publica al guardar.
- [ ] Implementar mockup aprobado reutilizando estilos/componentes, no un sistema visual nuevo. Fuente real desde endpoints, sin precargar dataset completo. Paginación keyset `(updated_at,id)`, cursores ligados al alcance/filtros; errores seguros y detalle incremental.
- [ ] Ejecutar Vitest completo, Playwright completo, lint, tipos y build; inspección de capturas ficticias móvil/desktop antes del cierre. PASS; commit `feat: add operational prospect list and detail`.

## Task 6: L6 — Verificación completa, revisión y preparación de entrega

**Files:** crear `docs/prospectos-entrega.md`; ampliar casos de prueba y registro de permisos pertinentes, sin cambios productivos.

- [ ] Ejecutar suite backend raíz completa (base/Redis aislados), unidades frontend completas, E2E, lint/tipos/build y seguridad. Ejecutar nueva migración desde cero y como upgrade del esquema instalado de contactos. Comparar datos existentes; pruebas no excluidas. Distinguir fallos previos de tipos/formato ya documentados de regresiones nuevas, con evidencia.
- [ ] Revisar una sola vez el cambio completo en contexto independiente; corregir críticos/importantes con RED→GREEN y repetir las suites afectadas/completas. No delegar tareas de implementación sin elección nueva del usuario; mantener método inline.
- [ ] Documentar diagramación simple del flujo, las cuatro responsabilidades de datos, límites del detector/modelo, errores, idempotencia, autorización, costos variables y qué no se ensayó. No prometer exactitud de facturación una vez.
- [ ] Preparar recuperación aditiva y orden de futura instalación: respaldo restaurado → migración → runtime/API/workers compatibles → panel, capacidad aún apagada; preservar snapshot activo y comprobar selección real. La publicación de una versión con captura necesitará revisión/evidencia nueva; nunca activar por un UPDATE directo.
- [ ] Entregar resultado local y solicitar autorización separada para instalar y, posteriormente, publicar. No enviar WhatsApp real, consumir API ni migrar hosting durante L1–L6.

## Autorrevisión y puerta de ejecución

Cobertura: cualificación/datos L1/L3; identidad/concurrencia L1/L3; editor/permisos/digests L2; transacción y humanos L3; pruebas/versiones heredadas L4; panel/contexto L5; seguridad/recuperación L6. La imagen de referencia es propuesta ficticia y no se usa como evidencia de funcionamiento.

No se diseñan acciones comerciales nuevas fuera de captura/supresión. Cuatro tablas separan identidad/privacidad, alias, ficha y evidencia inmutable; no se crean tablas por agente, empresa o servicio. La supresión no requiere inventar un prospecto ni una quinta tabla.

Estado: plan preparado para revisión de Daniel. Método nativo heredado: implementación en esta conversación con una revisión independiente final. Su aprobación permite comenzar localmente, no desplegar ni habilitar captura en Zuvel.
