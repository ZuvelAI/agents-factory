# Incidente de respuesta de Zuvel — 2026-11-07

Un mensaje de las 06:45 en Bogotá entró por WhatsApp y completó la ingestión.
El turno agotó cinco intentos y no generó ningún trabajo de envío. El agente
estaba activo. La clave y GPT-6 Luna respondían desde el trabajador.

## Causa y cambio

En el turno exacto, OpenAI devolvió una llamada de captura de prospecto que
citaba mensajes anteriores, sin incluir el entrante actual. La validación
rechazó la propuesta correctamente, pero el SDK propagó el error de herramienta
y abortó el turno completo. El registro de trabajos solo mostraba el error
genérico del runtime.

El código `75951fbeaa985232fd269014781313b8e01e65a7` devuelve un rechazo
estructurado para esa propuesta opcional y no la incluye entre los efectos a
persistir. El agente recibe la indicación de responder sin registrar el prospecto.
No se relajan la evidencia, la identidad ni los controles de pausa.

## Despliegue y verificación

- Regresión reproducida antes del cambio y resuelta después. 527 pruebas
  unitarias y de contratos aprobadas en la copia local limpia.
- Imagen `aiworkers-coex-runtime:lead-reply-75951fb`, ID
  `sha256:2fa4606c294eea4f71b27244d7f5bd301e6232cccc6fc687c3575db401fd30c1`.
- Digest de código `bb7a29af56a4aca9bbad67b92b90ca01c7474ae251934b089d23ad3e0f19e2fa`.
- Se actualizaron backend, agente y scheduler. Se preservaron WhatsApp,
  credenciales, publicación y GPT-6 Luna. Panel, envío, knowledge y Redis
  conservaron sus contenedores; no hubo migraciones ni reejecución de trabajos.
- En el VPS, el turno exacto volvió a generar texto en una comprobación de
  diagnóstico sin persistir ni enviar el resultado y sin preparar un prospecto.
  La validación de entrega real requiere un mensaje nuevo de prueba.
- Backend y panel sanos, con latidos de agente y envío correctos. El scheduler
  registró un error aislado al serializar un resultado al iniciar; continuó
  despachando y su contador de errores no aumentó en la comprobación posterior.
- Configuración anterior y manifiestos privados en
  `/opt/aiworkers/.lead-reply-hotfix-20261107-75951fb`. La imagen previa
  conserva las guardas de pausa; no se restauró ni se reenviaron mensajes.
