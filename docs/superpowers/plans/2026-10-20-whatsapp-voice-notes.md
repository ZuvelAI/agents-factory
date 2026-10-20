# Shared WhatsApp Voice Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Native/inline execution is recommended; execution choice remains with Daniel.

**Goal:** Todos los clientes actuales y futuros pueden enviar notas de voz y recibir respuestas de sus agentes por texto, con transcripciones visibles y aislamiento por empresa.

**Architecture:** Normalizar audio antes del turno conversacional mediante el outbox, scheduler y agent-worker existentes. Separar persistencia/claims, descarga segura, inspección, transcripción y proyección; reutilizar modelo, conexión, controles de conversación y captura de prospectos ya publicados. No llamar a Meta/OpenAI desde el webhook ni mantener transacciones abiertas durante IO externo.

**Tech Stack:** Python 3.12+, FastAPI/SQLAlchemy/asyncpg, PostgreSQL 17/Supabase, ARQ/Redis, httpx/httpcore y SDK OpenAI fijados en `uv.lock`, ffprobe en imagen Linux, Next.js/React/TypeScript y pruebas pytest/Vitest/Playwright existentes.

**Spec:** `docs/superpowers/specs/2026-10-20-whatsapp-voice-notes-design.md`, aprobada por Daniel el 20 de octubre de 2026. El plan no amplía autorización de despliegue, llamadas de pago o recuperación de mensajes antiguos.

## Global Constraints

- «Debe quedar habilitado por defecto para todos los clientes actuales y futuros, no solo Zuvel». Es normalización de plataforma, sin nueva capacidad del modelo ni republicación individual.
- Clave OpenAI actual, sin modificarla; modelo conversacional, marca, instrucciones, conocimiento, bindings, cuentas Meta y routing BSUID intactos. Transcriptor `gpt-4o-mini-transcribe-2025-12-15`, JSON y reintentos SDK desactivados.
- OGG/Opus exclusivamente en esta versión; máximo 10 000 000 bytes, 300 segundos y 25 000 caracteres; sin truncamiento silencioso.
- Descarga HTTPS solo `lookaside.fbsbx.com`, sin redirecciones, IP literal, puertos alternos o destino privado/reservado; conexión a la IP pública validada, conservando TLS/SNI del host. Nada de aceptar enlaces aportados por el usuario.
- Quince segundos por solicitud Meta; sesenta para transcribir; cinco para ffprobe y 64 KiB de salida. Máximo 180 segundos hasta primer claim y 120 desde ese claim, conservados entre procesos.
- Dos audios simultáneos globales, uno por empresa. Resultado READY reutilizable e inmutable; llamada iniciada sin resultado cierto → UNCERTAIN, nunca reintento de pago automático. Hasta dos intentos de descarga antes de iniciar transcripción.
- Binarios solo temporales privados, limpieza en finally. Sin binarios/tokens/URL temporal en base, cola, logs, Git o panel; transcripciones tienen el acceso privado del historial.
- Una tabla nueva empresarial, RLS forzada y grants mínimos; no security-definer ni ampliación de permisos para satisfacer pruebas.
- Respetar control humano/revocación/ventana de envío y no crear prospectos desde respuestas técnicas. Texto escrito mantiene su ruta y las herramientas del agente no cambian.
- Preservar los documentos ajenos pendientes del worktree. No `git add .`, push, merge, limpieza de datos o despliegue implícito.

## Review Focus

1. Un cliente nuevo o versión publicada antigua no necesita un flag nuevo para escuchar audio; un agente apagado no se activa: pruebas en T4.
2. Audio seguido inmediatamente de texto, o dos audios seguidos, no pierden contexto ni agotan reintentos mientras esperan: T3/T4.
3. Caída tras enviar audio a OpenAI no vuelve a cobrar automáticamente ni finge resultado: T1/T3.
4. Media ID repetido en otra empresa, DNS cambiante y metadata de cuenta ajena no permiten acceso cruzado o fuga de tokens: T1/T2/T3.
5. Negativa o instrucciones maliciosas habladas no eluden control humano, autorización de herramientas o procedencia de evidencia: T4/T5.

## Mapa de unidades e interfaces

Base `B = apps/backend/src/agents_factory/modules/audio_ingestion/`. Crear `__init__.py`, `models.py`, `repository.py`, `capacity.py`, `media.py`, `inspection.py`, `transcriber.py`, `service.py`, `projection.py`, `fallback.py` y `jobs.py`. Cada uno conserva la responsabilidad que indica la especificación; `capacity.py` solo coordina slots, `jobs.py` solo adapta sobres ARQ, `fallback.py` solo finaliza respuestas técnicas sin modelo.

En las listas siguientes `P = apps/backend/src/agents_factory/`, `BT = apps/backend/tests/` y `CP = apps/control-plane/`; expandir estos prefijos, no buscar otros módulos homónimos. `B/preflight.py` contiene la lectura de barreras y su adaptación al runner; no hace llamadas externas.

Contratos públicos (tipos inmutables salvo filas internas):

- `AudioSource`: IDs de tenant/account/conversation/message/event, provider_message_id, media_id, MIME/hash firmados y arrival_sequence; siempre cargado por servidor.
- `AudioClaim`: source, lease_id, fase PREFLIGHT/PROVIDER_STARTED, first_claim_at/deadline y estado; `AudioTranscript`: texto, digest SHA-256 UTF-8, modelo y usage opcional; `AudioInspection`: contenedor/códec/duración/tamaño.
- `AudioRepository(session, context)`: `enqueue(message_id: UUID) -> UUID`, `claim(message_id: UUID, owner_id: UUID, now: datetime) -> AudioClaim | None`, `start_provider(claim: AudioClaim, now: datetime) -> bool`, `complete(claim: AudioClaim, transcript: AudioTranscript) -> bool`, `finish(claim: AudioClaim, status: AudioTerminalState, error_code: str) -> bool`, `read_ready(message_ids: tuple[UUID, ...]) -> dict[UUID, AudioTranscript]`, `blocked_until(conversation_id: UUID, before_sequence: int, now: datetime) -> datetime | None`. Las mutaciones participan en la transacción del llamador.
- `AudioCapacityGuard(session_factory).hold(tenant_id: UUID)` es async context manager y devuelve permiso o falta de capacidad. Coordina dos slots globales y exclusión de empresa con advisory locks de sesión en conexiones reservadas AUTOCOMMIT, no transacciones largas ni lecturas de otras empresas. El claim/lease empresarial sigue siendo duradero y autoritativo. Pérdida de conexión cancela el trabajo local y no autoriza repetir una llamada externa incierta.
- `MetaAudioDownloader.download(source: AudioSource, destination: Path) -> AudioDownload`: usa resolver Meta existente y transporte inyectable; no acepta URLs del cliente. `AudioDownload` contiene hash/tamaño/MIME, no credencial.
- `AudioInspector.inspect(path: Path) -> AudioInspection`; `OpenAIAudioTranscriber.transcribe(path: Path, inspection: AudioInspection) -> AudioTranscript`. Ninguno importa SQL.
- `AudioIngestionService.process(envelope: JobEnvelope) -> None`: transacciones cortas antes/después de cada etapa. `AudioJobPreflight.check(envelope: JobEnvelope) -> JobDeferral | None`: comprobación de barrera/plazo antes de consumir un intento.
- `projection.effective_message(row, transcript) -> EffectiveAudioMessage(text, source_kind, transcription_id, digest, state)`, pura. `text` opcional, `source_kind = TEXT | AUDIO_TRANSCRIPT | None`, `state` usa estado de la fila o None si no existe. Campos nuevos de lectura opcionales con valores de reserva para mensajes antiguos; un audio histórico sin fila muestra «Sin transcripción», no crea trabajos por leerse.

Los detalles de campos SQL se derivan de estos contratos y de la especificación. No introducir otra tabla de cuotas globales ni mezclar la transcripción en `messages.content.text`.

## Preparación de ejecución y comandos

Verificar/reutilizar el worktree `codex/whatsapp-coexistence`; abrir ledger propio de este plan usando el helper de executing-plans. Registrar base y cambios pendientes; la especificación ya está guardada en `e6af9af`. Ninguna tarea empieza hasta que Daniel revise este plan y elija ejecución.

Los comandos siguientes parten de la raíz. Usar `uv==0.12.5`, Node/pnpm fijados por el proyecto y entorno de prueba **sin claves OpenAI/Meta reales**. PostgreSQL y Redis deben ser locales, aislados y desechables. Si se reutiliza la copia de verificación anterior, comprobar project_id, puertos y ausencia de trabajos concurrentes antes de recrearla; no tocar bases productivas. Una falla de infraestructura no es RED válido de una función.

Comando backend `uv run --all-packages pytest ...`; comprobación completa `uv run --all-packages pytest` sin exclusiones. Panel `pnpm --filter @agents-factory/control-plane test:unit`, `typecheck`, `lint`, `test:e2e`; compilación `pnpm --filter @agents-factory/control-plane exec next build`. Seguridad `sh infrastructure/scripts/check_repository_security.sh`. Registrar comandos/resultados reales; no ejecutar `verify_repository.sh` como sustituto de estas suites porque exige main/remote limpio y no verifica el comportamiento del producto.

### Task 1: Estado duradero, aislamiento, leases y capacidad

**Files:** crear `B/models.py`, `B/repository.py`, `B/capacity.py`; generar migración con `supabase migration new whatsapp_audio_transcriptions` (no inventar timestamp); crear `BT/unit/test_audio_models.py`, `BT/integration/test_audio_repository.py` y `BT/security/audio_table_contracts.py`. Extender `BT/security/test_tenant_isolation_matrix.py` y `supabase/tests/task3_tenant_isolation.test.sql`.

**Interfaces:** produce modelos, `AudioRepository` y `AudioCapacityGuard` definidos arriba; consume DB/context/outbox existentes. `AudioTerminalState = FAILED | CANCELLED | UNCERTAIN`; READY solo se obtiene mediante `complete`.

- [ ] **1. RED:** `test_audio_claim_is_tenant_scoped_and_deduplicated` exige misma fila/trabajo para dos enqueue del mismo mensaje, distinto ámbito para media ID igual en otra empresa y rechazo de mensaje/cuenta/evento ajenos. `test_audio_ready_is_immutable` exige que completar dos veces o cambiar tenant/texto no sobrescriba READY. `test_audio_expired_provider_claim_becomes_uncertain` exige cero claim nuevo de pago después de PROVIDER_STARTED. `test_audio_slots_bound_two_global_one_tenant` usa conexiones independientes y comprueba límites 2/1, liberación y error por pérdida de conexión. Aserciones sobre estado/filas/locks reales, no solo mocks.
- [ ] **2. Verificar RED:** `uv run --all-packages pytest -q apps/backend/tests/unit/test_audio_models.py apps/backend/tests/integration/test_audio_repository.py`; fallos por módulo/función ausente, no por Docker/red.
- [ ] **3. Implementar:** tabla única descrita en spec, índice para pendientes/plazos, grants por columna, transiciones CAS y límites en modelos. Cargar/revalidar AudioSource desde mensaje y evento firmado en cada claim. `complete` inserta exactamente un `agent.turn` en la misma transacción. Claves `whatsapp.audio.transcribe:{message_id}` y `agent.turn:{message_id}`; no cambian por intento. Recuperar claims PREFLIGHT expirados solo dentro del deadline; PROVIDER_STARTED expirado se conserva como UNCERTAIN. El lease tiene renovación acotada al deadline, no extiende los 120 segundos. Coordinar slots sin bypass RLS.
- [ ] **4. GREEN:** ejecutar los archivos anteriores más matriz real de roles y pgTAP. Añadir contrato explícito de la tabla al inventario completo: app opera su tenant/columnas permitidas, admin solo lee, públicos no acceden. Cero exclusiones de catálogo, cero privilegios sobre otra empresa. Probar espera inicial 180 segundos y duración de procesamiento 120 con reloj inyectado.
- [ ] **5. Commit:** solo archivos T1 y migración generada; mensaje `feat: persist tenant scoped voice note processing`.

### Task 2: Descarga segura, inspección y transcriptor desacoplado

**Files:** crear `B/media.py`, `B/inspection.py`, `B/transcriber.py`; crear `apps/backend/tests/contract/test_meta_audio_media.py`, `apps/backend/tests/unit/test_audio_inspection.py`, `apps/backend/tests/contract/test_audio_transcription.py`; modificar `infrastructure/Dockerfile.runtime` y su variante de prueba si requiere el mismo inspector. Fixtures generadas localmente y sintéticas, sin voces de clientes en Git.

**Interfaces:** consume AudioSource/AudioInspection/AudioTranscript de T1; produce los tres adaptadores definidos arriba. Reutiliza `SessionFactoryMetaAccessTokenResolver`, SDK OpenAI y clientes HTTP inyectables; cualquier dependencia directa nueva debe fijarse en manifiesto y lockfile.

- [ ] **1. RED:** `test_meta_audio_pins_validated_public_ip_and_tls_host` exige que la IP validada sea la usada al conectar con TLS/SNI original; simular DNS rebinding, privados IPv4/IPv6, URL con credenciales/IP/puerto alterno y redirect: todos fallan sin fuga de Authorization. `test_audio_rejects_stream_over_limit_and_hash_mismatch` exige rechazo aunque Content-Length mienta o falte. `test_inspector_requires_ogg_opus_finite_duration_and_available_binary` cubre 300/300.001 segundos, 10 000 000/10 000 001 bytes, duración ausente/NaN, binario ausente, proceso colgado y salida >64 KiB. `test_transcriber_uses_fixed_model_without_sdk_retries` exige snapshot fijado, JSON, timeout60 y max_retries0; vacío, >25k y truncamiento explícito fallan sin truncar. `test_silent_audio_with_empty_transcript_never_enters_agent_turn` comprueba el resultado vacío; no asume que el proveedor siempre identifica silencio o ruido correctamente.
- [ ] **2. Verificar RED:** ejecutar esos tres archivos con pytest; observar fallos antes de los adaptadores.
- [ ] **3. Implementar:** obtener metadata de media ID real con Graph API configurada, comparar ID devuelto y descargar solo host autorizado; resolver/pinear IP con transporte de conexión explícito (no confiar en una validación DNS separada del cliente). Streaming con conteo/hash. Inspeccionar por subprocess sin shell, sin red/playlists y con límites indicados. Resolver versión exacta de paquete ffmpeg/ffprobe disponible para la base trixie en la ejecución, registrar esa resolución y fijarla en el Dockerfile; no usar un paquete sin versión ni actualizar otros paquetes. No convertir/renombrar formatos no soportados. Preservar permisos temporales y limpieza en cualquier salida. Mapear errores del proveedor a clases seguras, sin contenido/credenciales.
- [ ] **4. GREEN:** repetir pruebas; demostrar que formatos rechazados, límites e inspector ausente no llaman al transcriptor. Construir imagen local fijada, generar OGG sintético con la herramienta instalada y probar inspección real, no solo stub. No llamadas externas pagadas en esta tarea.
- [ ] **5. Commit:** archivos T2 y locks si corresponden; `feat: add bounded secure voice transcription adapters`.

### Task 3: Orquestación, fallos y barreras sin quemar reintentos

**Files:** crear `B/service.py`, `B/jobs.py`, `B/fallback.py`, `B/preflight.py`; modificar `apps/backend/src/agents_factory/common/queue.py` solo para preflight/deferral explícitos; crear `apps/backend/tests/integration/test_audio_orchestration.py`, `apps/backend/tests/unit/test_audio_preflight.py`. Extender pruebas de cola existentes, sin debilitar su contabilidad.

**Interfaces:** consume T1/T2; produce `AudioIngestionService.process`, `AudioJobPreflight.check`, y `AudioFallbackService.finalize(message_id: UUID, error_code: str) -> None`. Añadir `JobDeferral(retry_after_seconds: float)` como resultado pre-start y callback opcional al runner; `JobRunResult` transporta ese aplazamiento hasta ARQ. El handler sigue devolviendo None.

- [ ] **1. RED:** `test_audio_crash_after_provider_start_never_retranscribes` comprueba UNCERTAIN, cero segunda llamada y una sola finalización técnica. `test_audio_ready_survives_failed_agent_turn` reutiliza texto y no vuelve a descargar/transcribir. `test_audio_preflight_defers_without_consuming_attempts` aplaza por capacidad/barrera y exige que attempt_count/job_attempts no cambien. `test_audio_two_workers_complete_only_current_lease` rechaza resultado de owner obsoleto. `test_audio_handoff_and_revocation_prevent_paid_work_or_reply` cambia autoridad antes y durante IO. `test_audio_wait_deadlines_release_following_text` usa reloj hasta 180/120 sin depender de sleeps.
- [ ] **2. Verificar RED:** ejecutar ambos archivos y los tests existentes de durable queue; fallos observados por comportamiento ausente.
- [ ] **3. Implementar:** claim y validación, capacidad, descarga/inspección, marcar PROVIDER_STARTED duraderamente **antes** de la llamada, guardar READY antes de programar turno; siempre cleanup y liberación de slots. No sesión SQL transaccional abierta en IO. Fallos previos a llamada tienen hasta dos descargas; un resultado externo incierto es terminal para automatización. Fallback fijo según spec mediante persistencia/outbox idempotente, no mediante modelo; conservar guardas de identidad, humanidad, cuenta y ventana del canal. Si se perdió autoridad, CANCELLED sin reply/captura. Resultado pagado ya iniciado puede persistirse sin autorizar efectos.
- [ ] **4. GREEN:** completar pruebas de carreras/rollback, registro de errores por fase y ausencia de secretos. El preflight corre antes de consumir intento y antes de bloquear la conversación; aplaza cinco segundos (o hasta deadline anterior), mantiene estado queued y usa Retry con defer correspondiente. Los 300 segundos máximos no deben agotar max_tries100 de ARQ; no elevar reintentos de pago ni reciclar números de job_attempts. Un trabajo terminal termina exitosamente como tarea gestionada, no reabre cinco veces el fallo conocido.
- [ ] **5. Commit:** `feat: orchestrate durable voice preparation and safe deferrals`.

### Task 4: Conectar entrada compartida, runtime y orden por conversación

**Files:** modificar `P/modules/whatsapp/meta_provider.py`, `P/modules/conversations/service.py`, `P/modules/runtime/turn_service.py`, `P/config.py`; crear `B/projection.py`; registrar handlers en `workers/agent-worker/src/agent_worker/jobs.py`, deferral en `workers/agent-worker/src/agent_worker/worker.py` y routing en `workers/scheduler/src/scheduler/worker.py`. Tests nuevos `BT/integration/test_audio_turns.py` y `BT/contract/test_audio_inbound.py`; extender pruebas de startup/settings y cola afectadas.

**Interfaces:** consume orquestación/preflight T3; produce proyección `EffectiveAudioMessage` común. Configuración técnica `WHATSAPP_AUDIO_ENABLED` default true, sin estado por cliente. Job nuevo `whatsapp.audio.transcribe` en cola agent y mismo aggregate_id de conversación. Registros de mensaje/nota solo se crean desde recepción viva, no desde archivo histórico.

- [ ] **1. RED:** `test_audio_default_supports_existing_and_new_tenants_without_republication` usa dos empresas/versiones anteriores/API_ONLY+COEXISTENCE sin nuevo flag de agente; debe encolar voz y seleccionar su snapshot original. `test_inactive_agent_and_human_chat_do_not_transcribe` exige cero pago/respuesta. `test_audio_then_text_preserves_preparation_order` y `test_two_audio_notes_preserve_sequence` impiden responder sin la nota previa, nunca incluyen mensajes futuros. `test_non_audio_and_legacy_dead_letters_do_not_enter_voice_pipeline` cubre texto, imágenes, video, documento, mobile echo y archivo histórico. `test_voice_kill_switch_stops_new_paid_work_without_affecting_text` preserva texto y da fallback seguro al audio nuevo permitido para responder.
- [ ] **2. Verificar RED:** pytest de esos dos archivos, antes de modificar recepción/runtime.
- [ ] **3. Implementar:** conservar media ID/MIME/hash del evento firmado en normalización, sin URL; ingest audio autorizado crea su registro/trabajo en vez del agent.turn prematuro. El worker carga fuente por IDs, inyecta adaptadores y consulta preflight. Runtime proyecta texto efectivo READY en actual/historial, mantiene rol user y procedencia; audio fallido no se transforma en petición inventada. Barrera solo por filas pendientes anteriores del hilo; al expirar o terminar se libera. Mantener fencing de control humano/revocación y compatibilidad de snapshots, sin recompilar clientes ni agregar herramientas a sus specs.
- [ ] **4. GREEN:** pruebas de T4 y regresión de inbound/identidad/primer contacto/handoff/publicación. Verificar un fallo técnico no se envía fuera de ventana ni crea prospecto; texto escrito no descarga medios ni llama al transcriptor. No prometer recepción si solo se creó/salió outbox.
- [ ] **5. Commit:** `feat: enable voice notes across existing customer agents`.

### Task 5: Evidencia de prospectos y lecturas de conversación

**Files:** modificar `P/modules/leads/repository.py`, `service.py`, `privacy.py`, `read_models.py`, `read_repository.py` en ese mismo directorio; ambas lecturas de mensajes `P/modules/agent_factory/workspace_conversation_models.py`, `P/modules/agent_factory/workspace_conversation_repository.py` y `P/modules/tenants/admin_router.py`. Panel: `CP/lib/conversation-workspace.ts`, `CP/lib/leads.ts`, `CP/app/(authenticated)/conversation-log/page.tsx`, `CP/app/(authenticated)/conversations/page.tsx`, `CP/components/leads/prospect-detail.tsx` y componente nuevo `CP/components/audio-transcription.tsx`. Crear `BT/integration/test_audio_leads.py`, `BT/unit/test_audio_projection.py`, unidades `CP/tests/unit/audio-transcription.test.tsx` y `CP/tests/e2e/audio-conversations.spec.ts`.

**Interfaces:** consume `projection.effective_message` de T4; lectores agregan `audio_state`, `transcription_id`, `transcription_digest` y `text_source` opcionales. Server guarda `changes.transcription_sources` en el evento comercial; extiende DTO de lectura sin alterar el esquema estricto de argumentos del modelo ni hacer pasar transcripción por cita escrita original.

- [ ] **1. RED:** `test_audio_lead_uses_persisted_transcript_and_original_sender` exige cita literal, origen AUDIO_TRANSCRIPT, versión/identidad del servidor y digest del READY exacto. `test_audio_transcript_from_other_tenant_or_future_message_is_rejected` falla ante fuente ajena/noREADY/digest distinto. `test_spoken_refusal_survives_human_takeover` aplica solo supresión permitida sin inventar atribución. `test_spoken_injection_cannot_enable_unpublished_tools` no amplía herramientas. UI debe mostrar estado/etiqueta de transcripción en ambas vistas, escapar `<script>` y distinguir fallo de consulta de nota no procesada; sin reproductor ni enlaces de media.
- [ ] **2. Verificar RED:** ejecutar tests backend de esta tarea y unidades nuevas del panel; observar fallo de proyección/contrato, no de entorno.
- [ ] **3. Implementar:** compartir texto efectivo verificado al validar evidencia y al preparar contexto, sin editar el evento/mensaje original. Aplicar negativa directa cuando corresponda, incluso si no se permite captura comercial; nunca saltar el gate de capacidades. Contratos compatibles para datos antiguos, fuentes paginadas y rutas autenticadas por empresa. Leer guía Next instalada antes de editar TSX; proyección/DTO escapados, un componente común para estados, sin insertar SQL en componentes.
- [ ] **4. GREEN:** backend T5, unidades completas del panel y navegador en ambas vistas, incluyendo móvil/teclado, prospecto sin audio y cita de texto antigua. Añadir permiso/cross-tenant/401 al endpoint existente, sin crear ruta pública para medios. No tests frágiles que comparen párrafos completos de copy en vez de estado/accesibilidad.
- [ ] **5. Commit:** `feat: expose attributed audio transcripts and prospect sources`.

### Task 6: Verificación completa y entrega reproducible

**Files:** crear `docs/notas-voz-entrega.md`; actualizar guía backend y documentación técnica de variables/imagen que realmente usa el proyecto. No modificar archivos de entregas antiguas pendientes para hacer parecer limpio el worktree.

**Interfaces:** consume todas las tareas; entrega fuente guardada, manifiesto de dependencias, matriz de pruebas y procedimiento de futura instalación/recuperación. No despliega, activa/republica agentes ni reejecuta notas antiguas.

- [ ] **1. Añadir regresiones finales:** `test_audio_ready_insert_and_agent_enqueue_rollback_together`, `test_audio_failure_reply_is_idempotent_and_never_a_lead`, `test_audio_waiting_does_not_starve_other_tenant_text`, `test_audio_lost_capacity_connection_cannot_commit_reply` en archivos dueños T1/T3/T4. Observar RED si descubren defecto y corregir una causa por ciclo, no declarar completos tests que pasaron antes de existir la función.
- [ ] **2. Ejecutar suites completas** backend, unidades/navegador/tipos/lint/build del panel y script oficial de seguridad. Registrar conteos y fallos por nombre, incluso preexistentes; sin exclusiones, permisos más amplios o excepciones para obtener verde. Ruff de módulos modificados y mypy del módulo audio/sus contratos, además de los gates existentes. Ensayar migración aditiva con datos ficticios anteriores y comparar tablas existentes.
- [ ] **3. Repetir desde fuente guardada** en copia limpia y dependencias fijadas: misma suite, no superponer fuentes sueltas. Documentar temporal project_id local y tipos generados si hacen falta. Verificar imagen con inspector y soporte del archivo sintético, sin claves reales. Prueba real acotada con audio sintético/fixture no personal y clave existente solo con autorización específica de costo; si no se hace, dejar explícito «proveedor real no comprobado», no atribuirle resultado de mocks.
- [ ] **4. Revisión final única** del conjunto, según ejecución elegida; corregir críticos/importantes con RED→GREEN y suite. Inspeccionar pérdida de autoridad, SSRF, leases/espera y costos inciertos. No despachar un revisor por tarea en ejecución nativa. Documentar límites/advertencias, proveedor probado o no, digest/dependencias y orden de compatibilidad.
- [ ] **5. Commit/handoff:** `docs: document verified shared voice note delivery`. Pedir autorización separada antes de respaldo/migración/instalación productiva. Futuro despliegue conserva snapshots/bindings y certificar versiones exactas en mapa compatible; aceptación con nueva nota del usuario. Recuperación no borra tablas/resultados ni reintenta UNCERTAIN gratuitamente.

## Auto-revisión del plan

- T1 cubre almacenamiento, aislamiento y límites concurrentes; T2 cubre medios, inspector y proveedor; T3 cubre máquina de estados/reintentos/fallback; T4 cubre habilitación global y orden; T5 cubre evidencia/UI; T6 cubre regresión y recuperación.
- Los cinco riesgos de Review Focus tienen pruebas concretas. La espera no usa excepciones genéricas que consuman los cinco intentos existentes ni aumenta intentos conversacionales pagados.
- El código nuevo no sustituye el modelo conversacional, cambia herramientas de versiones antiguas ni comparte cachés por hash entre clientes. Las pruebas reales y despliegue siguen fuera de la ejecución local sin su autorización específica.
- Interfaces consumidas mantienen nombres y tipos; no hay módulo de ejecución paralelo ni tabla global extra. Si un requisito de seguridad no puede cumplirse con estas interfaces, documentar el conflicto y detener esa parte antes de debilitarlo.
