# Guía del backend de AI Workers

Esta guía describe el código, no certifica el estado actual del servidor.
El panel operativo nuevo sigue siendo una entrega local, sin instalar.

## Configuración editable: entrega B

La configuración nueva sigue dentro del mismo backend, en `modules/agent_factory`:

- `configuration_router.py`: autenticación y contratos HTTP; no contiene SQL.
- `configuration_models.py`: modelos estrictos y límites de campos.
- `configuration_repository.py`: consultas con contexto de empresa y revisión.
- `configuration_service.py`: creación, guardado, validación y auditoría.
- `configuration_import.py`: copia dirigida y verificable del asistente anterior.
- `configuration_errors.py`: errores de petición seguros, sin devolver valores rechazados.

Flujo: panel o cliente administrativo autorizado → servicio → actualización con
revisión esperada → auditoría → commit transaccional. Si la revisión ya cambió,
devuelve409 y el panel conserva el texto. Si falla auditoría, se revierte el guardado.

`company_profiles` contiene información compartida. Cada fila de
`agent_configuration_drafts` pertenece a una instancia y guarda el snapshot de
empresa incorporado explícitamente. Editar uno no modifica otros agentes.

Un borrador incompleto NO es una versión ejecutable. La ejecución sigue leyendo
el AgentSpec publicado y fijado a la cuenta, no estas tablas. Las rutas antiguas
no leen automáticamente estos borradores. La adaptación del flujo de pruebas y
publicación está implementada localmente en la entrega C; ver
`docs/panel-operativo-entrega-c.md`. No está instalada en producción.

## Pruebas y publicación por agente: entrega C

```text
Perfil incorporado + borrador de instancia y revisión exactas
  -> proyección pura -> candidato compilado y conocimiento congelado
  -> prueba en outbox -> resultado inmutable -> revisión humana explícita
  -> gate vigente -> confirmación del número -> binding con revisión esperada
```

- `configuration_projection.py`: snapshot canónico y adaptación pura al compilador.
- `publication_source.py`: diferencia LEGACY de AGENT_CONFIGURATION; valida
  revisiones y digest sin confundir dos agentes con el mismo número de revisión.
- `workspace_publication_repository.py`: SQL acotado, locks y procedencia.
- `workspace_publication_service.py`: preparación, lectura, publicación y rollback.
- `workspace_publication_gate.py`: exige evidencia vigente, completa y aprobada.
- `workspace_publication_models.py` / `workspace_publication_views.py`: comandos
  estrictos y contratos de lectura separados.
- `workspace_publication_router.py`: autorización y rutas administrativas por
  empresa/instancia; no SQL ni llamadas al modelo.
- `publication_evidence.py`: solicitudes/revisiones y persistencia de evidencia;
  el worker reutiliza `publication_jobs.py`, con integridad pero sin acceso a borradores.
- `publication_preview.py`: conversación sintética aislada, sin herramientas,
  mensajes de clientes ni envío WhatsApp; fallo seguro, nunca respuesta de respaldo.

Hay una sola tabla nueva de procedencia: `workspace_agent_candidates`.
Se amplían los runs existentes con origen/tipo/revisiones y clave de solicitud.
Versiones, conocimiento, resultados, revisiones, outbox, auditoría y bindings se
reutilizan. No hay un segundo backend ni un segundo motor de respuesta.

Guardar, preparar, probar, aprobar y publicar son operaciones distintas. Solo la
última modifica la asignación del número, con control de concurrencia y auditoría.
Un cambio de empresa o borrador invalida pruebas antiguas para publicar, pero no
borra sus resultados. Rollback recupera una versión publicada compatible de la
misma instancia y no sobrescribe el borrador editable.

La cobertura de aislamiento mantiene dos contratos explícitos: matriz de DML del
runtime y contratos de tablas de publicación/edición en
`tests/security/agent_table_contracts.py`. Los perfiles y borradores no se abren al
runtime para acomodar una prueba. El catálogo falla si aparece una tabla de empresa
sin cobertura registrada. La suite completa de cierre B pasa709 pruebas en un
proyecto local Supabase independiente con el puerto canónico.

## Las piezas y sus responsabilidades

- `apps/backend`: API Python/FastAPI. Autentica administradores, recibe eventos,
  valida reglas y coordina servicios. Entrada: `src/agents_factory/main.py`.
- `workers/agent-worker`: ejecuta turnos del agente fuera de las peticiones web.
- `workers/outbound-worker`: envía las respuestas y gestiona sus intentos.
- `workers/knowledge-worker`: tareas de conocimiento implementadas; no implica
  que toda fuente/URL/PDF ya se ingiera automáticamente.
- `workers/scheduler`: coordinación de trabajos programados existentes.
- `apps/control-plane`: panel Next.js. Consume la API; no es el motor del agente.
- PostgreSQL/Supabase: persistencia duradera de empresas, mensajes, configuraciones,
  versiones, publicaciones, trabajos y auditoría. Redis coordina trabajo temporal;
  no sustituye esa persistencia.
- `openai-agents`: biblioteca instalada en el backend/worker. La biblioteca no
  aloja el producto ni es la base de datos. El modelo se ejecuta mediante la API.

## Recorrido de una respuesta

```text
Mensaje de WhatsApp → evento de Meta → webhook del backend
  → trabajo persistido / cola → agent-worker
  → versión asignada a la cuenta → AgentTurnService → adaptador OpenAI
  → respuesta persistida → outbound-worker → API de Meta
  → eventos de entrega → estado guardado del mensaje
```

Archivos para seguirlo, en ese orden:

1. `apps/backend/src/agents_factory/modules/whatsapp/webhook.py`.
2. `workers/agent-worker/src/agent_worker/jobs.py`.
3. `modules/agent_factory/channel_provider.py`: elige la versión fijada por cuenta.
4. `modules/runtime/turn_service.py`: reglas y persistencia del turno.
5. `modules/runtime/openai_adapter.py`: frontera con el modelo.
6. `modules/whatsapp/outbound_service.py` y
   `workers/outbound-worker/src/outbound_worker/jobs.py`: preparación y envío.

Los mensajes no toman sus instrucciones del historial de este chat de Codex.
Usan el snapshot publicado y asignado en la base de datos. Un borrador nuevo no
altera ese snapshot. Un número puede conservar una versión anterior, por lo que
la publicación más reciente y la versión asignada se muestran por separado.
El indicador de cambios pendientes compara las revisiones exactas del borrador y
su empresa con la procedencia de esa publicación; no toma la mera existencia del
borrador como cambio. `pending_configuration_changes` en `workspace_projection.py`
es la regla pura compartida por resumen/listado/detalle. Un número puede conservar
otra versión intencionadamente sin convertir por eso el borrador en pendiente.

## Estructura de los módulos nuevos de lectura

Todos están en `apps/backend/src/agents_factory/modules/agent_factory/`:

| Archivo | Responsabilidad | No debe hacer |
|---|---|---|
| `workspace_router.py` | Rutas HTTP, autorización y validación de entrada | SQL o lógica de publicación |
| `workspace_models.py` | Contratos de empresas, agentes, canales y versiones | Consultar servicios externos |
| `workspace_conversation_models.py` | Contratos de conversaciones y mensajes | Exponer payloads/credenciales |
| `workspace_service.py` | Coordinar lecturas y contexto por empresa | Compilar o publicar borradores |
| `workspace_conversations.py` | Alcance, filtros, selección y paginación | Atribuir mensajes por el binding actual |
| `workspace_repository.py` | Consultas de resumen y detalle | Cambiar datos o llamar proveedores |
| `workspace_conversation_repository.py` | Consultas de mensajes y actividad | Enviar mensajes |
| `workspace_projection.py` | Transformaciones puras y campos permitidos | Inventar salud o ejecutar consultas |
| `workspace_cursor.py` | Cursores opacos y validación | Autorizar acceso por sí solo |

El flujo de dependencia es ruta → servicio → repositorio → base de datos;
servicio → proyección → contrato de salida. Los repositorios no dependen de
las rutas ni de componentes visuales. Los modelos no dependen de SQL.

## Conceptos que no deben mezclarse

- Empresa: frontera de aislamiento, identificada por tenant_id.
- Instancia de agente: identidad estable dentro de una empresa.
- Versión: configuración inmutable que puede probarse/publicarse.
- Binding: asignación de una cuenta de WhatsApp a una instancia y versión.
- Conversación: hilo por cuenta/contacto. Sus respuestas conservan la versión
  realmente utilizada; no se reetiquetan al cambiar el binding.
- Entregado: evento de entrega persistido. Aceptado por Meta no significa entregado.
- Salud de conexión: última comprobación de la cuenta, con fecha. No demuestra
  que el worker esté respondiendo ni que el agente esté bien configurado.

## Reglas para mantenerlo entendible

Agregar contratos explícitos antes de una ruta; dejar SQL en repositorios y
reglas en servicios; usar funciones puras para proyecciones; probar primero el
comportamiento. Evitar duplicar motores de publicación, ampliar permisos para
sortear errores o crear tablas sin un consumidor identificado.

Las pantallas y Codex deben invocar los mismos servicios autorizados. Nunca
considerar editar filas directamente como API administrativa. No registrar
tokens, claves ni entornos completos. Mantener comentarios que expliquen una
restricción real, no que repitan cada línea de código.

## Verificar un cambio

Pruebas nuevas: `apps/backend/tests/integration/test_agent_workspace.py`.
Requieren PostgreSQL/Redis locales desechables; no apuntarlas a producción.
Ejecutar además la regresión del proyecto, Ruff y Mypy; documentar expresamente
los errores de entorno existentes. La evidencia concreta está en
`docs/panel-operativo-entrega-a.md`.

No borrar tablas solo por su cantidad: antes identificar consumidores, claves,
políticas, trabajos e historial. Cualquier migración productiva necesita ensayo,
respaldo y autorización separados del rediseño de la interfaz.

## Notas de voz: entrada compartida, no otro agente

`modules/audio_ingestion/` prepara las notas nuevas antes del runtime existente.
El webhook conserva identidad y metadatos firmados; no descarga ni transcribe.
El outbox envía `whatsapp.audio.transcribe` al agent-worker existente. Una vez
guardado READY, se programa el turno habitual con su snapshot y herramientas.

Responsabilidades: `source.py` valida procedencia; `repository.py` conserva estado
y presupuestos; `capacity.py` limita concurrencia entre workers; `media.py`,
`inspection.py` y `transcriber.py` son adaptadores sin SQL; `authorization.py`
comparte controles; `service.py` coordina; `preflight.py` aplaza antes de consumir
intentos; `projection.py` distingue texto escrito de transcripción; `fallback.py`
solo emite orientación técnica, sin modelo ni captura comercial.

Solo hay una tabla nueva: `whatsapp_audio_transcriptions`, aislada por empresa.
No guarda archivos de audio ni URLs temporales. Los mensajes originales siguen
siendo de tipo audio. Conversaciones y evidencias leen una misma proyección.

`WHATSAPP_AUDIO_ENABLED` vale true por defecto para clientes actuales y futuros;
false detiene nuevas llamadas de voz tras reiniciar los workers. No cambia el
modelo conversacional, la clave OpenAI, los snapshots ni los bindings. El
transcriptor fijo se configura en código y reutiliza `OPENAI_API_KEY` del proceso.
La imagen instala `ffmpeg=7:7.1.5-0+deb13u1`; ffprobe se ejecuta sin privilegios,
sin shell y limitado a archivos OGG locales. Los locks de capacidad requieren
conexiones PostgreSQL con afinidad de sesión, no un pool de transacciones.

Estados inciertos no se reintentan de pago automáticamente; leer una conversación
no reprocesa notas antiguas. Ver límites, pruebas y procedimiento de instalación
en `docs/notas-voz-entrega.md`. Desarrollo local no equivale a despliegue.
