# Entrega compartida de notas de voz

Fecha: 2026-10-20. Estado: instalada en producción con autorización de Daniel.
Proveedor real y recepción de una nota nueva aún pendientes. Ver
`notas-voz-instalacion-20261020.md` para respaldo, imágenes y comprobaciones.

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
  en preparación, renovado durante IO saludable, y hasta65 al iniciar proveedor.
  Las renovaciones no extienden
  el deadline. Dos descargas máximas con contador duradero entre recuperaciones.
- El dispatcher recupera solo trabajos de audio que llevan150 segundos en
  `processing`, más que el plazo máximo del procesamiento. Cada despacho de audio
  usa una identidad Redis nueva; el ledger SQL conserva el bloqueo y el número
  de intento. Una caída abrupta tras iniciar proveedor termina en UNCERTAIN,
  sin nueva llamada pagada. El aviso de recuperación puede demorarse150 segundos.
- Si se pierde la conexión que reserva capacidad, ese trabajador no contesta:
  guarda el estado terminal y un trabajo idempotente de finalización en la misma
  transacción. El siguiente trabajador recarga el estado y verifica autoridad
  antes del aviso; no descarga ni transcribe otra vez.
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

Una migración nueva: `20261021014333_whatsapp_audio_transcriptions.sql`. Su única
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
- Cierre con las tres correcciones importantes:978 pruebas backend pasaron87.14s.
  Cada caso nuevo falló antes de corregirlo: recuperación real vía dispatcher,
  aviso durable tras pérdida de capacidad y renovación de preparación lenta.
- Fuente guardada `215dd31`: copia Git limpia sin superponer fuentes,975 pruebas
  backend84.26s. Panel154 pruebas unitarias/26 archivos,45 Chromium43.2s,
  tipos/lint/build sin errores. Incluye audio en ambas rutas, móvil, teclado,
  escape y fallo de consulta. Las correcciones posteriores solo cambian backend.
  Las dependencias generadas se materializaron dentro de la copia temporal:
  Turbopack rechaza enlaces que salen de su raíz; no se cambió ninguna versión.
- Seguridad oficial con migración final:72 pruebas de seguridad iniciales,
  51 de aislamiento tras reset; pgTAP434+115; lint SQL sin errores. Advisors
  conservan avisos de rendimiento (índices/legacy policies), no exclusiones nuevas.
- Imagen local: un tono sintético de1s producido con ffmpeg e inspeccionado por
  el ffprobe instalado (OGG/Opus,1.0065s,9391bytes). Ninguna voz de clientes en Git.
  Imagen final de la fuente guardada `b261c52`, arquitectura local ARM64:
  `aiworkers-voice-runtime:verified-b261c52`, identificador local
  `sha256:5452e0309ea482645df8f55facaa3923d47199e12ba2a6f3caada51d50979202`.
  Este identificador no es un digest publicado ni certifica AMD64 productivo.
- Ensayo aditivo en copia Git `b261c52`: reset local hasta la migración anterior,
  cuatro registros ficticios (empresa, cuenta, conversación, mensaje) y aplicación
  con `supabase migration up --local`. Sus cuatro huellas completas quedaron
  iguales; la tabla nueva quedó vacía con RLS activada y forzada (`t|t|0`).
  Solo se cambió el project_id del entorno temporal para usar la base local.
- Una revisión independiente del conjunto no encontró críticos y señaló tres
  importantes, corregidos con pruebas RED→GREEN y suite completa. No se realizó
  una segunda revisión. Pendiente menor: un audio mayor de cinco minutos puede
  recibir el aviso genérico de reenvío, en lugar de explicar el límite específico;
  sigue rechazándose antes de la llamada pagada.
- Meta/OpenAI y entrega al celular no se comprobaron. Las pruebas de adaptadores
  son simuladas; la inspección ffprobe sí usa un archivo sintético real. No
  confundir estos resultados con disponibilidad del proveedor o aceptación final.

## Decisiones de ejecución y riesgos conservados

1. Validación de origen en `source.py`, no dentro del repositorio: frontera
   enfocada; coste si se reconsidera, mantener/reubicar un archivo adicional.
2. La ruta pgTAP propuesta no existía: se amplió `rls_matrix_test.sql`, que es
   el control real; ninguna prueba omitida ni excepción de seguridad.
3. La admisión conserva la reserva de capacidad durante todo el handler: una
   comprobación que la liberase antes introduciría una carrera. Coste: contrato
   genérico adicional de contexto asíncrono, sin servicio nuevo.
4. Autorización compartida en `authorization.py` para evitar reglas distintas
   entre audio y aviso fijo; coste: otro archivo, sin permisos ampliados.
5. Descubrimiento Vitest ampliado de `.test.ts` a incluir `.test.tsx`: las nuevas
   pruebas de interfaz deben ejecutarse. Coste: descubrimiento más amplio, sin
   excluir las existentes.
6. Contador duradero de dos descargas dentro de la única migración aún inédita:
   impide reiniciar presupuesto al recuperar un claim. Un crash antes de IO
   puede consumir conservadoramente un intento reservado.
7. Proveedor y celular no se juzgaron con mocks: requieren autorización aparte;
   coste: disponibilidad y aceptación real siguen pendientes.
8. Recuperación de `processing` limitada a audio después de150 segundos y una
   identidad Redis por despacho: permite alcanzar el estado incierto tras SIGKILL
   sin repetir pago. Coste: demora del aviso y posibles entregas Redis duplicadas,
   neutralizadas por el ledger SQL; otros tipos de trabajo no cambian.

Pendiente menor aplazado: conservar el código específico de duración al traducir
el error del inspector para mejorar el aviso de cinco minutos. No se ocultó ni
se convirtió en excepción para obtener suites verdes.

## Procedimiento de instalación y recuperación

La instalación descrita fue autorizada y completada. La prueba de API con costo
requiere aprobación específica adicional; no se ejecutó. Los pasos se conservan
como referencia para instalaciones futuras.

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
