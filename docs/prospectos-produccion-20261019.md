# Prospectos — instalación y activación de Zuvel

Fecha local: 19 de octubre de 2026. Daniel autorizó guardar por separado los prerrequisitos pendientes, instalar en producción y activar prospectos. No se migró hosting, cambió clave/modelo ni repitió la conexión de WhatsApp.

## Código reproducible

Fuente desplegada: `6245ef86a96c4605f16034ff08753c36a3bf2c72`, rama `codex/whatsapp-coexistence`. Archivo construido desde `git archive`, sin fuentes sueltas, dependencias locales ni credenciales. SHA-256 del archivo: `d83605c762e7007e5cda340a2e64b7b440bf611628fb6ba73982be6b75399d0d`.

Prerrequisitos preservados mediante commits separados:

- `d0d2894`: envío BSUID y estados alternativos de entrega; 57 contratos Meta pasaron en conjunto.
- `9878796`: plazo de Embedded Signup de treinta minutos y respeto de la expiración del servidor en el panel.
- `6245ef8`: lector administrativo heredado de conversaciones, con identidad de contactos.

Verificación completa de la fuente guardada en copia aislada: **860 pruebas backend, 145 unidades de panel y 42 pruebas de navegador aprobadas**. Tipos del panel aprobados. El primer intento desde el worktree encontró bloqueo del sandbox para conexiones locales; el siguiente expuso configuración de cifrado ausente y dejó el marcador de una prueba de reconstrucción. Se usó el entorno de verificación ya configurado, se reconstruyó exclusivamente la base local desechable y se repitió toda la suite: 860/860, sin exclusiones ni relajación de comprobaciones.

## Respaldo y despliegue

Artefactos privados en VPS: `/opt/aiworkers/.prospects-20261019` (directorio 0700, respaldos/manifiestos/entornos 0600). No copiar sus contenidos a Git, informes ni conversaciones.

Se respaldaron estructura y filas de veinte tablas acotadas a Zuvel, incluida configuración, versiones, bindings, conocimiento aprobado, evidencias, contactos, perfiles, conversaciones, mensajes y eventos entrantes. La lectura de datos usó una transacción `REPEATABLE READ` con el rol administrativo y contexto de empresa. Se restauraron estructura pre-data y datos en PostgreSQL aislado sin red; las filas decodificadas coincidieron semánticamente en las veinte tablas. Se detuvo el contenedor de ensayo conservándolo. No es respaldo integral de toda la base, otras empresas, colas o secretos; no se ensayaron restricciones post-data en esta restauración. El esquema completo con restricciones y permisos se reconstruyó en las pruebas locales previas.

Migración aditiva `lead_capture` aplicada al proyecto existente `tjtduugvgmfkudnanqrz`. Supabase registró la versión **`20261020011546`**, equivalente al SQL local `20261018211730_lead_capture.sql`; no aplicar ambas como migraciones distintas ni interpretar la diferencia de identificadores como ausencia de esquema. Las cuatro tablas tienen RLS habilitado y forzado; `anon` y `authenticated` no tienen SELECT. Ningún DROP, cambio de Auth ni ampliación de permisos para facilitar respaldo.

Imágenes instaladas:

- Runtime: `aiworkers-coex-runtime:prospects-20261019`, ID `sha256:70cb9a6f440c63498c6704fe76a51f800c3ddd87376a8c00e768ac0812cfe109`.
- Panel: `aiworkers-coex-dashboard:prospects-20261019`, ID `sha256:99b540ebd6cb09eb0dcf011f33dc29b4526d9e83d22013eee6fe2b14be50b11a`.
- Digest de código: `56280747bed0839ad08c928f5c968fb74e4c13737637c3a2118e4fdd5c614cfc`.

Se actualizaron backend, panel, agent-worker y scheduler. Outbound, knowledge y Redis conservaron sus contenedores. Dependencias Python comparadas contra la imagen anterior; panel compilado con dependencias fijadas y exclusivamente argumentos públicos. Solo variaron digest de código y mapa de versiones compatibles en el entorno de backend/agente/scheduler; las demás variables, incluidas credenciales, se compararon por nombre/valor y permanecieron intactas. Se conservaron imágenes y configuraciones de recuperación.

Antes de publicar se preservó la versión activa anterior `01a14c5f-7506-7657-a0ae-247b1b96115a`, binding revisión4. La compatibilidad del nuevo código autoriza versiones exactas previamente certificadas, no una excepción genérica de digest.

## Activación por el flujo normal

Empresa: Zuvel `c5cd8d04-01f2-49be-aa27-1075520a2a20`; agente `01a1382a-5154-7de4-b052-232e56724593`.

`AgentConfigurationService.save_draft` cambió exclusivamente `lead_capture.enabled=true` con revisión esperada2: borrador3 y empresa1. Se comparó el resto del borrador y de la configuración proyectada con la versión publicada anterior: nombre, propósito, saludo, instrucciones, conocimiento, tono, modelo y herramientas anteriores se conservaron. GPT-6 Luna, esfuerzo low; misma clave existente. Se agregó la capacidad interna `lead_capture@1.0.0` y sus herramientas `lead_capture.propose` / `lead_capture.suppress`.

Candidato exacto: **`01a156e2-e40b-77e8-a08a-4d5d56c08cba`**. Evidencia: **`5ec59983-cd3f-4ca9-9174-6022864dda89`**. Se solicitó una sola batería con clave de petición determinista. Nueve escenarios v2 completos: ocho turnos reales de modelo más control humano local; las iteraciones de herramientas pueden producir más solicitudes API y costo variable. No se calculó un importe facturado ni se hicieron reintentos de baterías.

Revisión de respuestas: marca/saludo conservados; no inventa el precio inexistente; rechaza tareas ajenas y extracción de instrucciones/claves. Cotización produce CAPTURE con cita literal, sin inventar nombre/empresa; saludo/agradecimiento no producen captura; negativa produce SUPPRESS. Todas las propuestas de prueba son simuladas. Cero fichas/eventos/subjects reales creados por las pruebas, sin mensajes enviados a clientes.

Tras revisar esas respuestas, `WorkspacePublicationEvidenceService.review` aprobó la evidencia vigente y `WorkspacePublicationService.publish` publicó el candidato con revisión esperada del binding4. Resultado: **binding revisión5**, versión en estado **PRODUCTION**, únicamente en la cuenta existente `01a132b4-c3f5-75b4-b1dd-21eaa076f291` (+573124009568). WABA `1572027171232643`, phone ID `1342213852302971`, modo COEXISTENCE conservados. No se usó UPDATE directo de flags/bindings para saltar controles.

## Comprobaciones y uso

- Backend/panel saludables; readiness HTTP200. Login público y web corporativa HTTP200. El nuevo endpoint administrativo sin autenticación responde HTTP401.
- El trabajador instalado seleccionó el nuevo snapshot exacto y su digest, con GPT-6 Luna y sin fallback. Esa transacción diagnóstica se revirtió; no llamó al modelo ni envió mensajes.
- Lector instalado de prospectos comprobado con el rol administrativo real y contexto de Zuvel. Panel disponible en https://aiworkers.zuvel.ai/prospects. No se afirma inspección visual autenticada en el navegador productivo.
- Advisor de seguridad antes/después: únicamente la advertencia preexistente de [protección de contraseñas filtradas deshabilitada](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection); no se modificó Auth.

La captura aplica a **mensajes nuevos con interés comercial**, también de un contacto existente; no importa retroactivamente conversaciones ni convierte cada saludo en prospecto. La bienvenida completa continúa reservada para contactos nuevos. Una negativa impide nuevas capturas; no equivale a eliminar mensajes o datos históricos. El primer prospecto real y su recepción en teléfono requieren un nuevo mensaje natural de prueba del usuario; no se fabricó una ficha para simular éxito.

## Recuperación preparada, no ejecutada

Procedimientos operativos privados: `/opt/aiworkers/leads-release-20261019.py` y `/opt/aiworkers/leads-candidate-20261019.py`. Sintaxis verificada. `rollback-agent` usa el servicio normal para volver a la versión anterior únicamente si sigue vigente el candidato publicado y binding5; se detiene ante una publicación posterior. No elimina prospectos ni evidencia.

Solo después de volver a esa versión anterior puede usarse `rollback-code`, que exige binding4 o6 con esa versión exacta y restaura imágenes/entornos originales de web y agent/scheduler. Nunca restaurar trabajadores antiguos debajo del nuevo snapshot. Las tablas aditivas se conservan: no DROP, no restauración indiscriminada de conversaciones sobre mensajes nuevos. Los procedimientos no se ejecutaron sobre la instalación saludable para ensayar una reversión artificial.

Los cambios ajenos de documentación que ya estaban pendientes permanecen sin incluir. No merge, push, PR, borrado de ramas, imágenes, datos ni servicios.
