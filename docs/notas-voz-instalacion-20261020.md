# Notas de voz — instalación productiva

Daniel autorizó la subida a Git y la instalación en producción el2026-10-20.
La instalación quedó sana. No se ejecutó ninguna transcripción pagada ni se
reprocesaron audios anteriores; falta aceptación con una nota nueva de WhatsApp.

## Fuente e imágenes

- Rama: `codex/whatsapp-coexistence`, subida sin force-push. Fuente instalada:
  `f12019ae0f3b8023ce9e26ca2796207284bb7325`, paquete generado con `git archive`.
  Los seis documentos pendientes de otras entregas no se incluyeron.
- Se compararon161 archivos del runtime instalado con la base `cf184f3`:
  ninguna diferencia, antes de sustituirlo.
- Imagen AMD64: `aiworkers-coex-runtime:voice-f12019a`,
  `sha256:2362976c8958f98186e6a6e2ad65703ee673ae66a3ea6d1ecc76e706614a0ccd`.
- Panel: `aiworkers-coex-dashboard:voice-f12019a`,
  `sha256:90d365fde72a865eeb850ba30bc54f361d5d4bb008ff00f5b60c9c9b358a61d3`.
- Procedencia del código:
  `4744a46fb0c5e3f640334fcc927b3bfccf44045bbf81e85ebd96da1dfae1d3da`.
  Manifiesto de fuentes, lockfile e imagen base guardado dentro de la imagen.
  ffmpeg fijado y probado en AMD64 con un tono sintético; no basta la prueba ARM64.
- Las pruebas anteriores de la misma fuente:978 backend,154 unitarias del panel,
  45 Chromium, compilación/tipos/lint y control oficial de seguridad aprobados.

## Respaldo y preservación

Ubicación privada en el VPS: `/opt/aiworkers/.voice-20261020-f12019a`, directorio
0700, configuración y datos0600. Incluye inspecciones previas, schema dump,
datos de24 tablas relevantes, manifiestos de las imágenes y composición anterior.
Se restauraron esquema pre-data y filas en PostgreSQL aislado sin red; las filas
restauradas coincidieron semánticamente. No se ensayaron allí las restricciones
post-data; estas se cubrieron con el ensayo aditivo y controles SQL locales.

La base usa el pooler de sesión en puerto5432, no el pooler transaccional6543.
No se alteraron claves OpenAI/Meta, APP_MASTER_KEY, conexiones de WhatsApp,
conocimiento, instrucciones ni snapshots. La selección real del runtime devuelve
exactamente la versión `01a156e2-e40b-77e8-a08a-4d5d56c08cba`, GPT-6 Luna,
binding revisión5, sin llamadas al modelo. La compatibilidad incluye esa versión
exacta y su digest previo; no se desactivó la validación de integridad.

## Migración

Supabase aplicó `whatsapp_audio_transcriptions` con identificador UTC
`20261021014333`. El archivo local se renombró desde `20261020205147` para
coincidir con la historia real. El SQL no cambió; SHA-256:
`4db4039eeb0b960c74824a20245fc0258020856401ce2c18e64a89893345a774`.
No aplicar otra vez el nombre anterior ni usar un reset contra producción.

La tabla nueva quedó inicialmente vacía, con RLS activada y forzada;
anon/authenticated no pueden leerla; el administrador no puede actualizarla.
El rol de aplicación conserva solo la lectura/inserción y actualizaciones
por columna previstas. No hay SECURITY DEFINER nuevo.

El advisor de seguridad no informó problemas nuevos de RLS. Mantiene la
advertencia preexistente de
[protección de contraseñas filtradas deshabilitada](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
No se cambió la configuración de Auth como parte de esta entrega.

## Cambio y verificaciones productivas

La cola no tenía trabajos pendientes o ejecutándose. Se detuvieron ordenadamente
scheduler y agente, y se actualizaron backend, panel, agente y scheduler con las
imágenes nuevas. Outbound, knowledge y Redis conservaron sus contenedores exactos.

- Backend: `/health/ready` indica PostgreSQL/Redis disponibles.
- Panel interno y público:200. Web `www.zuvel.ai`:200.
- Ambos servicios web sanos; agente/scheduler ejecutándose con la imagen nueva.
- Salud ARQ del agente: ningún trabajo fallido/pendiente/en ejecución al cierre.
- `WHATSAPP_AUDIO_ENABLED` resuelve true por defecto para clientes actuales/futuros.
- La versión, revisión, modelo, configuración y credenciales previas se comprobaron
  iguales; se guardó `activation.json` en el respaldo privado.
- Cero filas de audio y cero trabajos nuevos de voz al cierre: no se reprodujeron
  notas anteriores ni se fabricaron conversaciones para simular aceptación.

GitHub no respondía directamente desde la conexión local; se verificó primero
que la rama no existía y se usó un túnel SSH temporal por el VPS para la subida.
La autenticación permaneció local; no se copiaron credenciales Git al servidor.

## Recuperación

Se conservaron las imágenes anteriores y los archivos privados
`compose.recovery-web.json` y `compose.recovery-workers.json`, con sus entornos
exactos. El procedimiento privado `voice-release-20261020.py` preparó estos
manifiestos antes del cambio y contempla recuperación si falla la activación.
La recuperación no fue ejecutada porque las verificaciones pasaron.

Para desactivar solo voz, usar `WHATSAPP_AUDIO_ENABLED=false` y reiniciar el
trabajador compatible; se conserva texto y se evitan nuevas llamadas de voz.
Antes de una recuperación completa, detener el scheduler, drenar trabajos de
voz con código compatible y comprobar que ninguna publicación posterior requiere
otro runtime. No restaurar un worker antiguo debajo de un snapshot incompatible.
Mantener tabla, transcripciones y ledger; no borrar Redis ni reintentar UNCERTAIN.

## Aceptación aún pendiente

El control de seguridad bloqueó la prueba pagada de una frase artificial porque
la autorización de despliegue no incluía explícitamente ese cobro. Se solicitó
autorización aparte; no se eludió el bloqueo ni se repitió la llamada.
Una frase sintética local está preparada, sin datos personales, pero no se envió
a OpenAI. No afirmar disponibilidad real ni recepción al celular hasta probarlas.

Daniel debe enviar una nota nueva al WhatsApp conectado. Verificar entrada,
descarga Meta, READY, transcripción visible, respuesta de marca y entrega real.
Una tabla vacía o un endpoint sano no prueban ese recorrido.
