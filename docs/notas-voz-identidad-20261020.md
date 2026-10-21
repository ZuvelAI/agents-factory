# Voz: corrección de identidad interna y verificación productiva

Daniel autorizó corregir y desplegar el fallo descubierto en la primera nota
real posterior a la instalación. No se autorizaron cambios de credenciales,
permisos, conexión de WhatsApp ni reprocesamiento del audio anterior.

## Causa y alcance

El audio entró correctamente, pero su descarga falló antes de llamar a OpenAI.
`MetaAudioDownloader` creaba un contexto de sistema con `actor_id=None`.
`SecretVault._require_context` denegó correctamente ese acceso anónimo. El código
lo convirtió en `audio_download_failed` y envió un aviso técnico, cuya entrega
fue confirmada por WhatsApp. No era una respuesta generada a partir del audio.

La corrección asigna una identidad de servicio estable por empresa, derivada
internamente con UUIDv5, sin identidad proporcionada por el cliente. La identidad
solo identifica el proceso en la auditoría: el tenant, cuenta, propósito de la
credencial, cifrado y RLS siguen autorizando la lectura. No se modificó el almacén
de credenciales ni se admitió el acceso anónimo.

Un único archivo productivo cambió: `modules/audio_ingestion/media.py`.
No hay nuevas dependencias, migraciones, servicios o cambios del modelo GPT-6 Luna.

## Pruebas

- Se reprodujo primero el error exacto `audio_download_failed` con una credencial
  ficticia cifrada y el resolver/almacén real, simulando solo las conexiones HTTP.
- La misma prueba pasa después del ajuste y sigue rechazando una lectura anónima.
  Comprueba descarga, contenido y auditoría con un actor de sistema no anónimo.
- Suite completa desde copia Git:979 pruebas backend aprobadas,75.96 segundos.
- Ruff y mypy estricto de14 archivos de audio sin errores.
- Control oficial de seguridad:72+51 pruebas Python,434+115 pgTAP, lint/advisors
  locales sin errores; no se excluyeron pruebas ni se ampliaron permisos.

La prueba sintética real autorizada previamente de OpenAI también pasó: una sola
llamada a `gpt-4o-mini-transcribe-2025-12-15`, audio artificial de4.074958 segundos,
texto «Hola, quiero información sobre los agentes de inteligencia artificial.».
Evidencia privada: `.voice-20261020-f12019a/provider-probe.verified.json` en el VPS.
No se repitió esta llamada durante la corrección.

## Instalación

Fuente: `3c438186da37ac3c7090363943081aef0177150d`, rama
`codex/whatsapp-coexistence`, subida a GitHub sin force-push.
Se compararon175 archivos con la fuente previa: ninguna diferencia antes del
cambio. Se respaldaron25 tablas, incluida la fila de audio fallida, y se ensayó
la restauración en PostgreSQL aislado; todas las filas coincidieron.

Recuperación privada: `/opt/aiworkers/.voice-identity-20261020-3c43818`,0700,
artefactos privados0600. Conserva imágenes/entornos anteriores, respaldo,
verificación de restauración y manifiestos `compose.recovery-*.json`.
La imagen nueva reutiliza las dependencias previas y copia solo el archivo
corregido y el manifiesto de procedencia. El proceso de aplicación sigue sin root.

- Runtime: `aiworkers-coex-runtime:voice-identity-3c43818`,
  `sha256:475b939bb9573750fa2ec09e3a80ce91ae59174eddfbf37d37cbd98f690ed05a`.
- Digest de código:
  `e90b8139200ca02732e77d69250f03ac73cda16f9a95aedbf7ac3d31dd478a93`.
- Panel sin reconstruir:
  `sha256:90d365fde72a865eeb850ba30bc54f361d5d4bb008ff00f5b60c9c9b358a61d3`.

Se drenó la cola y detuvieron ordenadamente scheduler/agente. Se actualizaron
los componentes del runtime conservando la configuración previa. No se alteraron
outbound, knowledge ni Redis. La activación verificó claves/entornos preservados,
snapshot publicado exacto y selección GPT-6 Luna, sin invocar el modelo.

Backend/panel sanos; panel público y web Zuvel200. Salud ARQ sin trabajos fallidos,
pendientes o en ejecución al cierre.

## Verificación real sin repetir el audio

Se ejercitó el `MetaAudioDownloader` corregido con el resolver y almacén productivos.
La petición autenticada de metadatos devolvió HTTP200 e identificador coincidente.
La comprobación se detuvo expresamente antes de descargar el binario: ninguna
transcripción nueva, respuesta al cliente o modificación del ledger del audio.
La auditoría normal de lectura de credenciales sí permanece registrada.

La fila fallida anterior conserva su estado terminal y el aviso enviado; no se
reseteó para simular éxito. La aceptación completa requiere una nota nueva:
entrada → descarga → READY → agente → envío → entrega al teléfono.
