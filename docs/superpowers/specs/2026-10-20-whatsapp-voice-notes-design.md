# Notas de voz de WhatsApp — diseño compartido de AI Workers

Fecha: 2026-10-20, America/Bogota. Estado: especificación escrita aprobada por Daniel; plan de implementación pendiente de revisión. No implementada ni desplegada.

## 1. Intención acordada

El cliente envía una nota de voz por WhatsApp y el agente entiende su contenido y responde **por texto**, con su propia marca, instrucciones, conocimiento y modelo publicados. Se reutiliza la clave OpenAI existente, sin modificarla. Daniel corrigió expresamente el alcance: debe quedar habilitado por defecto para **todos los clientes actuales y futuros**, no solo Zuvel.

Éxito: audio recibido → texto transcrito vinculado al mismo mensaje → respuesta contextual visible en WhatsApp y panel. Una petición comercial puede guardar un prospecto cuando el agente ya tiene esa capacidad publicada; escuchar audios no habilita por sí mismo captura comercial ni otras herramientas. Un fallo de audio produce una orientación clara para escribir, no silencio ni contenido inventado, siempre que el agente pueda responder en ese canal.

Se mantienen los límites propuestos en la conversación: hasta cinco minutos y 10 MB por nota. No se crea una copia permanente adicional del archivo de voz. La transcripción queda identificada en el historial. No se prometen transcripciones infalibles ni facturación externa exactamente una vez.

## 2. Contexto verificado y alternativas

El audio de prueba llegó como mensaje entrante `audio`, sin texto, con conversación AI_ACTIVE. Su trabajo agotó cinco intentos y quedó en dead letter con `agent_runtime_error`. Ese código genérico **no demuestra cuál fue la excepción interna**. El código actual confirma dos carencias independientes: `_normalized_content` conserva texto, pero descarta el contenido normalizado del audio; `_turn_message` reemplaza mensajes sin texto por una etiqueta, sin transcripción. No existe un servicio de descarga/transcripción de voz.

Se elige **transcripción separada antes del turno normal**: conserva los modelos e instrucciones existentes y permite persistir/reutilizar el resultado sin repetir automáticamente el costo cuando falla una respuesta posterior. La alternativa de enviar audio directamente a un nuevo modelo multimodal ampliaría el cambio de modelo, contexto y evidencias. Procesar medios en el webhook se descarta porque prolonga la respuesta a Meta y mezcla recepción con llamadas externas.

## 3. Alcance y compatibilidad

- Función transversal de normalización de entrada, habilitada por defecto; sin alta manual por empresa, nueva capacidad del modelo ni republicación individual de agentes.
- Aplica a notas nuevas de clientes en cuentas activas API_ONLY y COEXISTENCE que ya tengan un agente activo y autorización para responder. No activa agentes apagados, recupera cuentas revocadas ni convierte conversaciones humanas en automáticas.
- Cada cuenta usa su credencial Meta existente, resuelta con contexto de empresa/cuenta desde el vault. La transcripción usa la clave OpenAI actual del despliegue, sin mostrarla ni copiarla al panel.
- El modelo conversacional no cambia. Tampoco saludo inicial, tono, conocimiento, conexiones, webhooks, routing BSUID o herramientas publicadas.
- Un interruptor técnico global de emergencia permite detener nuevo procesamiento de voz; el valor normal es habilitado. No se añade un paso de configuración por cliente.
- No incluye llamadas telefónicas, streaming, mensajes de voz salientes, reproducción de audio en el panel, análisis de imágenes/video/documentos, traducción automática, carga retrospectiva ni reintento masivo de trabajos viejos.
- Primera versión: notas OGG con códec Opus, el formato de voz objetivo de esta entrega. Otros contenedores o códecs quedan explícitamente no admitidos y reciben orientación por texto, no se renombra un archivo para fingir compatibilidad.

## 4. Flujo y responsabilidades

```text
Webhook firmado → identidad/cuenta/mensaje originales persistidos
                       ↓
Audio nuevo autorizado → trabajo whatsapp.audio.transcribe en outbox existente
                       ↓
Claim duradero → descarga Meta → validación local → transcripción OpenAI
                       ↓
Resultado duradero + trabajo agent.turn → versión activa de esa cuenta
                       ↓
Respuesta + prospectos autorizados + outbox → envío de texto existente
```

Se reutilizan scheduler, outbox y agent-worker; no se crea otro servicio desplegable ni otro motor de conversación. El webhook no descarga ni llama al modelo. Texto mantiene su flujo actual. Audio no se envía al modelo conversacional antes de tener transcripción válida o un resultado terminal explícito.

Nuevo módulo enfocado `modules/audio_ingestion/`:

| Unidad | Responsabilidad |
| --- | --- |
| `models.py` | Límites, estados, metadatos y resultados tipados; sin IO. |
| `repository.py` | Claim/lease, estado, transcripción y trabajos con ámbito de empresa; sin red. |
| `media.py` | Obtener metadatos y bytes de Meta con credencial de la cuenta; límites e integridad. |
| `inspection.py` | Inspección local acotada de contenedor, códec y duración. |
| `transcriber.py` | Adaptador del SDK OpenAI para voz a texto; sin conversaciones ni SQL. |
| `service.py` | Coordinar etapas, autorización, costos/reintentos y finalización. |
| `projection.py` | Texto efectivo y procedencia comunes a runtime, lectores y evidencia. |

La normalización de WhatsApp conserva únicamente media ID, MIME y hash de la nota identificada dentro del evento firmado; no acepta una URL arbitraria del remitente. El worker recibe IDs internos, carga los datos desde la base y comprueba empresa, cuenta, conversación, mensaje y evento. No confía en identidades que vengan como argumentos de trabajo.

## 5. Descarga y límites de recursos

- Tamaño máximo **10 000 000 bytes**; duración máxima **300 segundos**; texto máximo **25 000 caracteres**. No truncar silenciosamente. Rechazar tamaño/duración desconocidos o no verificables y respuestas vacías; si el proveedor indica truncamiento, tratarlo como fallo. El límite no garantiza reconocimiento completo o correcto.
- Resolver media ID con la API Meta configurada y credencial de esa cuenta. Derivarlo exclusivamente del evento firmado y exigir igualdad de empresa, cuenta, WABA, teléfono, remitente y provider message ID con el mensaje persistido. El ID devuelto por los metadatos debe coincidir con el solicitado; no aceptar otro ID o un medio aportado por argumentos del trabajo.
- Descargar solo HTTPS del host exacto `lookaside.fbsbx.com`, sin redirecciones, usuario/contraseña, puertos alternos o direcciones IP literales. Rechazar resolución a loopback, redes privadas, link-local o reservadas; impedir que una segunda resolución cambie ese destino. Ninguna credencial se reenvía a otro origen. Si la API devuelve otro host, fallo cerrado y revisión técnica, no ampliación automática de la lista.
- Validar Content-Length cuando exista y contar bytes reales durante streaming; Content-Length no sustituye el límite. Contrastar SHA-256 real con los hashes disponibles del evento/metadatos, con codificación validada. No deducir tipo ni integridad del nombre del archivo.
- Inspector local `ffprobe`, sin shell, usuario sin privilegios, solo protocolo de archivo local, sin listas de reproducción ni accesos de red. Dependencia fijada en la imagen y registrada en manifiesto; invocación con timeout de cinco segundos y salida máxima de 64 KiB. Si falta el inspector, no llamar al proveedor para saltarse el límite de duración.
- Timeout de metadatos/descarga de quince segundos por solicitud; transcripción de sesenta segundos; plazo total del trabajo de ciento veinte segundos desde su primer claim. Espera máxima antes de ese primer claim: ciento ochenta segundos desde la creación del trabajo; superarla termina con error sin llamada de pago. Los plazos vencen aunque cambie el worker. Máximo dos procesamientos de voz simultáneos en el despliegue y uno por empresa, mediante leases duraderos compartidos entre workers. Las demás empresas no deben quedar bloqueadas por una nota lenta.
- Solo archivo temporal privado 0600, directorio 0700 y nombre generado por servidor. Borrado en finally tras inspección/transcripción, también ante cancelación o error. Los bytes no entran en PostgreSQL, Redis, logs, Git o almacenamiento de objetos adicional. Esta regla no borra el medio original de WhatsApp/Meta.

## 6. Transcripción y costos

Adaptador inicial: OpenAI `audio.transcriptions.create`, modelo fijado **`gpt-4o-mini-transcribe-2025-12-15`**, respuesta JSON, sin traducción ni herramientas. Verificar disponibilidad con la clave existente antes de habilitar el despliegue; no sustituir modelo o clave automáticamente si falta acceso. El modelo transcriptor es independiente del modelo conversacional y no lo reemplaza.

Una nota usa un resultado de transcripción almacenado. Se desactivan los reintentos automáticos del SDK para esta llamada. Hay hasta dos intentos totales de descarga para fallos de transporte antes de la llamada de pago, dentro del plazo total; los fallos definitivos no se reintentan. Un timeout, pérdida de conexión o caída después de comenzar la llamada al transcriptor puede haber generado costo aunque no exista resultado: marcar **UNCERTAIN**, no repetirla automáticamente. Su recuperación exige una acción administrativa explícita y aviso de posible nuevo cargo. No se promete exactamente una llamada facturada por nota.

Persistir el resultado antes de programar el turno conversacional. Reintentar generación o envío de respuesta no repite una transcripción READY. Nunca compartir caché por hash entre empresas, contactos o mensajes diferentes. Las métricas guardan modelo, duración, bytes, intentos, tiempos y usage disponible, no un precio inventado; distinguir medición del proveedor de estimaciones y no afirmar facturación exacta cuando no está disponible.

## 7. Persistencia, aislamiento y procedencia

Una tabla nueva compartida: `whatsapp_audio_transcriptions`; no tablas por cliente. Clave única `(tenant_id, inbound_message_id)`, referencias empresariales al mensaje, conversación, cuenta y evento originales. Campos: IDs originales, media ID/hash/MIME, duración/tamaño, estado, fase, lease/intento, marcas de tiempo, texto y digest de transcripción READY, modelo y usage, error técnico seguro. No URL temporal, token, binario ni respuesta cruda del proveedor.

Estados: **QUEUED → PROCESSING → READY / FAILED / CANCELLED / UNCERTAIN**. Claim y cambios por comparación de lease y estado; READY es inmutable y no admite sobrescritura de texto. Un lease vencido antes de iniciar la llamada de pago admite recuperación acotada; después de iniciarla pasa a UNCERTAIN. Resultado + programación de `agent.turn` se confirman en la misma transacción y con claves idempotentes. No mantener una transacción SQL abierta durante descarga, inspección o OpenAI.

RLS habilitado y forzado, contexto explícito de empresa y permisos de actualización limitados por columna. Runtime: solo las lecturas/escrituras operativas necesarias; administración: lectura por empresa. Sin grants de Data API a `anon`/`authenticated`, sin función security-definer, sin UPDATE de IDs de ámbito. Pruebas de roles y catálogo deben incluir la tabla nueva, sin excluirla para conseguir verificaciones verdes.

El mensaje original continúa siendo `audio`; no se reescribe como texto ni se altera su raw_payload firmado. Proyección común devuelve texto efectivo READY y procedencia. El runtime usa esa proyección tanto para el mensaje actual como para el historial. La transcripción es contenido del usuario, nunca una instrucción de sistema ni conocimiento verificado.

## 8. Orden, control humano y errores visibles

Antes de descargar y antes de llamar al transcriptor, comprobar de nuevo cuenta activa, agente asignado y control de conversación. Si una persona tomó el control antes de la llamada, cancelar el trabajo sin llamar al modelo. Si cambia durante una llamada ya iniciada, puede conservarse el resultado, pero no autoriza respuesta automática, captura comercial ni reactivación. La negativa a captura inequívoca extraída del texto puede aplicar la preferencia de supresión existente, que ya permite negativas sin atribuirlas a un agente inventado.

Las notas pendientes forman una barrera de preparación para turnos posteriores de la misma conversación: no responder a un texto nuevo como si una nota anterior lista para procesamiento no existiera. Al vencer el plazo o terminar con error se libera la barrera. No cambiar arrival_sequence ni usar mensajes futuros como contexto. La barrera solo cubre filas nuevas del flujo de voz; los dead letters históricos no bloquean chats nuevos.

Un fallo terminal genera como máximo una respuesta técnica por mensaje mediante el outbox y controles de envío existentes, sin llamada conversacional ni captura de prospecto. No se envía si hay control humano, cuenta revocada, agente inactivo o ventana de mensajería no válida. Los errores de la propia entrega mantienen la semántica actual: aceptación no equivale a recepción en el celular.

Mensajes iniciales en español:

- Excede límites: «Puedo procesar notas de voz de hasta 5 minutos y 10 MB. Envíame una nota más corta o escríbeme tu consulta.»
- Formato no admitido: «Todavía no puedo procesar este formato de audio. Envíame una nota de voz de WhatsApp o escríbeme tu consulta.»
- Vacío, no inteligible, fallo o resultado incierto: «No pude procesar tu nota de voz. ¿Puedes enviarla de nuevo o escribirme tu consulta?»

No afirmar que se escuchó o entendió un audio fallido. Errores operativos deben distinguir descarga, formato/límite, transcripción, incertidumbre y respuesta del agente; no exponer medios ni credenciales. La calidad del reconocimiento puede fallar aun con un resultado READY: el agente debe pedir aclaración cuando no tenga información suficiente.

## 9. Prospectos, privacidad y panel

La captura de prospectos sigue dependiendo de la versión publicada que permite `lead_capture`. La evidencia de audio utiliza citas literales del texto transcrito persistido del mismo mensaje/conversación/empresa; identidad y alias siguen verificándose desde el evento Meta original. El servicio vuelve a cargar esa transcripción al confirmar, no confía en lo que copie el modelo. Si cambia su digest o no está READY, rechazar la propuesta, no sustituirla por texto inventado.

El servidor registra referencias a transcripción y digest en la procedencia del evento comercial y los expone mediante contratos administrativos compatibles. El detalle diferencia **«Fuente: transcripción automática de audio»** de una cita textual escrita por la persona. El modelo no elige el tipo de origen ni sus IDs. La interfaz no ofrece reproducción de un archivo que deliberadamente no se conserva.

Conversaciones nuevas y heredadas muestran tipo audio, estado y transcripción cuando esté READY; escapes de HTML, paginación y límites conservados. No sustituyen un fallo de consulta por «audio no disponible». Sin edición manual de transcripciones ni exposición de media URL. Las conversaciones conservan su historial de nombres/identidad y versión realmente usada.

Texto transcrito tiene la misma sensibilidad y acceso que una conversación; no se replica en logs. No se agrega retención independiente indefinida ni borrado automático de historial: debe incluirse en el procedimiento administrativo de privacidad existente. Una negativa a captura no significa eliminar conversaciones ni transcripciones históricas. No se afirma consentimiento de marketing derivado de enviar audio.

## 10. Verificación y entrega

Pruebas antes del código: nota OGG/Opus válida, MIME/hash falsos, tamaño y duración en límite/fuera de límite, tamaño o duración ausentes, stream excesivo, archivo dañado, silencio, falta de inspector, SSRF/redirección/DNS cambiante y token que nunca cruza orígenes. Validar cero llamadas de pago para medios rechazados.

Pruebas integradas: dos empresas con media ID igual; cuenta/evento ajenos; duplicación de webhook/job; pérdida de lease antes y después del punto de pago; dos workers; resultado READY reutilizado si falla respuesta; texto posterior y dos notas en orden; handoff/desconexión durante descarga/transcripción; negativa hablada; prospecto con cita de transcripción y atribución exacta; comportamiento de un agente sin captura; estados del panel en ambas vistas; error de envío que no se confunde con éxito. Cubrir imagen/video/documento para asegurar que no entran accidentalmente al flujo de voz.

Ejecutar suites completas backend, panel, navegador, seguridad/roles/pgTAP y compilación desde fuente guardada. Revisar dependencias del inspector y manifiestos. Una prueba real acotada de voz con la clave actual debe confirmar soporte OGG y resultado, previa a afirmar compatibilidad real. No reintentar el audio histórico o todos los dead letters por defecto; para la aceptación, Daniel envía una nota nueva después de la instalación autorizada.

Implementar y validar localmente no autoriza desplegar. La instalación futura requiere autorización expresa de esta entrega, respaldo restaurado/verificado, migración aditiva y actualización compatible de backend, agent-worker/scheduler y panel. Mantener snapshots de agentes y bindings intactos; el soporte global de entrada no los republica. El nuevo digest del código requiere certificar y enumerar las versiones activas compatibles, no deshabilitar sus controles.

Recuperación: detener nuevas llamadas de voz con el interruptor técnico, conservar resultados y filas, recuperar imágenes compatibles sin borrar tablas. Desbloquear trabajos solo según su estado y lease, no reejecutar los inciertos como si fueran gratuitos. No cambiar claves, hosting, conexiones, conocimiento o las herramientas de los agentes durante esta entrega.

## Referencias de diseño

- [OpenAI: creación de transcripciones](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create): endpoint de archivos, formatos y modelos admitidos. La disponibilidad de la cuenta y la compatibilidad del audio real se verifican antes de habilitar, no se deducen de la documentación.
- [Meta: colección oficial de medios](https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ecb27be5-4d27-4763-bbee-6a8002c04bf3): separación entre obtener metadatos y descargar un medio con autorización. Las restricciones de host de esta especificación son una decisión de seguridad del producto, no una promesa de estabilidad de Meta.
- [Supabase: Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security): combinar permisos de tabla y políticas; la autorización administrativa del backend no equivale a abrir tablas al navegador.
- Código actual: `whatsapp/meta_provider.py`, `conversations/service.py`, `runtime/turn_service.py`, `leads/repository.py` y ambos lectores administrativos de conversaciones.
