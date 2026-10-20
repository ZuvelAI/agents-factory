# Entrega compartida de notas de voz

Fecha: 2026-10-20. Estado: implementación local; cierre de verificación y revisión en curso.
No instalada en producción. Proveedores reales no comprobados en esta entrega.

## Qué cambia

Todos los clientes actuales y futuros tienen soporte de entrada de voz por
defecto, siempre que su cuenta y agente ya estén activos. No requiere publicar
una capacidad nueva. Una nota OGG/Opus de hasta 300 segundos y 10 000 000 bytes se
descarga desde Meta, se inspecciona, se transcribe y entra al agente como contenido
del usuario. El agente responde por texto con su modelo, marca y versión asignados.

Se conserva la clave OpenAI existente, sin modificarla. El transcriptor está
fijado a `gpt-4o-mini-transcribe-2025-12-15`, JSON, timeout60 y max_retries0. Su
disponibilidad real con esa cuenta aún debe comprobarse con autorización de costo.
No se ha recuperado ni reenviado ningún audio histórico.

## Límites y recuperación

- Dos preparaciones simultáneas globales, una por empresa; slots PostgreSQL de
  sesión AUTOCOMMIT. Se comprueba pérdida de sesión durante IO y se cancela el
  trabajo local. Cancelar una petición no garantiza ausencia de cobro externo.
- Espera inicial180 segundos; procesamiento120 desde el primer claim; lease45
  en preparación y hasta65 al iniciar proveedor. Las renovaciones no extienden
  el deadline. Dos descargas máximas con contador duradero entre recuperaciones.
- HTTPS443 al host exacto `lookaside.fbsbx.com`; IP pública validada y usada en
  el TCP real, con TLS/SNI original, sin redirects/proxies de entorno ni destinos
  privados, reservados o multicast. Hash y bytes reales comprobados.
- ffprobe5 segundos, salida64KiB, contenedor OGG/códec Opus. Binario fijado a
  ffmpeg `7:7.1.5-0+deb13u1` de Debian trixie, probado sin privilegios en imagen local.
- Texto no vacío de máximo25 000 caracteres; no truncar silenciosamente. No se
  conserva una copia permanente del binario: directorio temporal0700 y archivo0600,
  limpieza en salida/error/cancelación. Esta regla no elimina el medio de Meta.
- READY es inmutable. Resultado externo incierto → UNCERTAIN, sin repetición
  pagada automática. FAILED/CANCELLED/UNCERTAIN liberan barreras de preparación;
  también las libera el plazo máximo, aunque haya caído un proceso.
- Fallos técnicos usan texto fijo, una respuesta idempotente por nota, sin modelo
  ni prospecto. Se respetan control humano, cuenta, agente activo y ventana24h;
  encolado/aceptado no equivale a entrega al celular.

## Datos y panel

Una migración nueva: `20261020205147_whatsapp_audio_transcriptions.sql`. Su única
tabla pública nueva es empresarial, con RLS forzada, referencias compuestas,
grants mínimos, transiciones y presupuesto monotónico. No amplía Data API ni usa
security-definer. Los roles administrativos solo leen la transcripción.

Los mensajes y eventos firmados no se reescriben. Las dos vistas muestran tipo,
estado y etiqueta de transcripción automática, sin reproductor o media URL.
Un fallo de consulta no se convierte en «sin transcripción». Texto HTML se escapa.

Capturar prospectos sigue requiriendo herramientas publicadas. El servidor
recarga citas literales y registra message_id, transcription_id y SHA-256 exactos
en `changes.transcription_sources`, no en argumentos elegidos por el modelo.
El panel distingue fuente escrita de audio automático. Una negativa inequívoca
puede conservar la supresión existente incluso bajo control humano, sin inventar
un evento comercial atribuido a un agente. No implica consentimiento de marketing.

Las transcripciones deben incluirse en los procedimientos de acceso y eliminación
del historial privado. No hay una nueva política de retención o borrado automático;
esta entrega no autoriza borrar historial ni afirma cumplimiento legal por sí sola.

## Evidencia de verificación

- Base anterior:860 pruebas backend. T1:884; T3:928; T4:951; T5:966.
- T5 panel:154 pruebas unitarias/26 archivos; 3 pruebas Chromium de audio para ambas
  rutas, móvil, teclado, escape y fallo de consulta. Tipos y lint sin errores.
- Seguridad oficial con migración final:72 pruebas de seguridad iniciales,
  51 de aislamiento tras reset; pgTAP434+115; lint SQL sin errores. Advisors
  conservan avisos de rendimiento (índices/legacy policies), no exclusiones nuevas.
- Imagen local: un tono sintético de1s producido con ffmpeg e inspeccionado por
  el ffprobe instalado (OGG/Opus,1.0065s,9391bytes). Ninguna voz de clientes en Git.
- Cierre: resultados completos de fuente guardada, ensayo aditivo y revisión
  independiente se añadirán al terminar. No confundir mocks con disponibilidad real.

## Instalación futura: requiere autorización separada

1. Preparar respaldo productivo y verificar recuperación antes de mutar la base.
   Registrar imágenes, digest y versiones/bindings activos; no imprimir secretos.
2. Confirmar versión ffmpeg para la arquitectura productiva y conexiones de
   sesión directas. Probar disponibilidad del transcriptor con fixture sintética,
   la clave ya existente y un costo explícitamente autorizado.
3. Aplicar primero la migración aditiva; ensayar compatibilidad con datos previos.
   Detener/dejar drenar trabajos viejos según runbook; no borrar colas o dead letters.
4. Actualizar backend, scheduler y agent-worker compatibles, además del panel.
   Mantener snapshots/bindings; certificar el digest nuevo y enumerar exactamente
   las versiones anteriores compatibles, sin desactivar su validación de integridad.
5. Comprobar salud, roles y nueva nota de aceptación de Daniel: entrada → READY →
   turno → envío → recepción comprobada. Revisar ambas vistas y atribución comercial.

Recuperación: `WHATSAPP_AUDIO_ENABLED=false` y reinicio de workers impiden nuevas
llamadas de voz, sin apagar texto. Conservar tabla/resultados; restaurar imágenes
compatibles sin migración destructiva. No borrar registros ni reintentar UNCERTAIN
como si fuera gratuito; cualquier recuperación pagada necesita acción explícita.
