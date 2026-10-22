# Pausa de agentes — instalación en producción

Daniel autorizó actualizar la copia local, subir la rama e instalar en producción.
La instalación finalizó el 2026-10-22. No se pausó Zuvel, no se volvió a conectar
WhatsApp y no se enviaron mensajes ni llamadas pagas de prueba.

## Código y sincronización

- Fuente ejecutable: `56312d009c259006f8f1d0a2f20b04399ca31461`.
- Rama remota: `codex/whatsapp-coexistence`, subida sin force-push.
- La carpeta principal `/Users/daniel/Zuvel/Agents Factory` avanzó mediante
  fast-forward desde `4e85b3d`; se conserva su rama local `codex/zuvel-pilot-staging`.
- Los seis documentos pendientes de otras entregas en el worktree no se incluyeron.
- Se repitió el backend completo antes de subir: 1.024 pruebas aprobadas en 87,72 s.
  Evidencia previa de esa misma fuente: 161 unitarias del panel, 49 Chromium,
  tipos/lint/build y seguridad local aprobados.

## Imágenes y procedencia

- Runtime AMD64: `aiworkers-coex-runtime:pause-56312d0`, imagen
  `sha256:3d7bb62deddaaf075b1adabff19103185092567a51748a60b388e0c019759a51`.
- Panel: `aiworkers-coex-dashboard:pause-56312d0`, imagen
  `sha256:7700749bb9fd4a6efc3f9b355c92a7948b5a27e06cdaacbb6dd0f956bd9acfc3`.
- Digest del manifiesto de código:
  `e87cd47e656304b786e59232800b57f484d6bef1384d37caab6c38f176c874d7`.
- El paquete provino de `git archive`, sin archivos privados ni cambios sin commit.
- Se verificaron los 172 elementos del baseline instalado. El primer control
  detectó que la receta Docker no se distribuye dentro de la imagen. El control
  automático rechazó retirar ese elemento del baseline: no se cambió el archivo
  ni se borró el informe original. Se verificó su SHA contra el manifiesto existente
  y el hash de ese manifiesto contra la etiqueta de imagen; todos los elementos
  quedaron comprobados sin diferencias. No se redujo el alcance de la verificación.
- ffmpeg se comprobó en AMD64 con audio sintético, sin API de transcripción.

## Respaldo y recuperación

Directorio privado del VPS: `/opt/aiworkers/.agent-pause-20261021-56312d0`.
Configuraciones y datos permanecen en el servidor, con permisos privados; no se
copiaron secretos a Git ni a esta documentación.

Antes del cambio se respaldaron y restauraron 43 tablas del tenant, con igualdad
semántica de filas. El 2026-10-22 se exportó de nuevo el estado actual, incluidas
las dos tablas nuevas: 45 tablas restauradas y comparadas en un contenedor sin red.
El registro está en `recovery-current-20261022/backup.restore-verified.json`.

El primer inicio de este ensayo fresco encontró un nombre de contenedor ocupado
por el ensayo anterior. Se conservaron exportación e informes y se terminó la
restauración en un contenedor con nombre nuevo; no se repitió ninguna mutación
productiva ni se borró el contenedor anterior.

Se ensayaron esquema pre-data y filas. No se restauraron restricciones post-data
en ese contenedor: sus comprobaciones están cubiertas por las pruebas locales y
las consultas productivas de permisos/RLS, no por ese ensayo de restauración.

La recuperación nunca debe arrancar emisores antiguos que ignoren las pausas.
Mantener las migraciones aditivas y recuperar con código compatible. Si la
activación fallaba, el procedimiento dejaba detenidos los emisores, sin volver
automáticamente a imágenes antiguas. Imágenes y configuración anteriores se
conservan para diagnóstico y recuperación controlada.

## Migraciones

No se renombraron ni reescribieron las migraciones locales aplicadas. Supabase
asignó identificadores UTC propios; se registra su correspondencia para no
aplicar el SQL por segunda vez:

| Archivo local original | Identificador productivo | Nombre |
| --- | --- | --- |
| `20261021142146_agent_operations.sql` | `20261021211741` | `agent_operations` |
| `20261021143242_agent_message_admissions.sql` | `20261021211754` | `agent_message_admissions` |

Los archivos conservan SHA-256:

- Operación: `05aa382d63e34fe747301596b012913819a87ddd046d6e7f705b4a4f48fd292b`.
- Admisiones: `c89d65b8c48570347645564dc52a8ec82fed636f1acb47d6c93b23837fad462e`.

También se comparó el SQL completo guardado en el historial productivo con cada
archivo local: sus MD5 coinciden, respectivamente
`0c2877afe8768d0ad5ebb064672e88ef` y `4c5923dde41b81955c3b528c608bf6bd`.

Ambas tablas tienen RLS activada y forzada. Anon/authenticated no pueden leer;
el rol runtime no puede actualizar ninguna de las dos. La revisión de seguridad
de Supabase no señaló problemas nuevos; persiste el aviso previo de protección
contra contraseñas filtradas deshabilitada. No se cambió Auth como parte de esta entrega.

## Activación y preservación

Se actualizaron backend, panel, agent-worker, outbound-worker y scheduler.
Knowledge-worker y Redis conservaron sus contenedores exactos. Primero se
detuvieron los emisores antiguos; después se instalaron trabajadores protegidos,
backend/panel y scheduler. Los controles permanecieron apagados hasta verificar
que todos los emisores usaban la imagen compatible.

El primer intento de activación se detuvo antes de sustituir procesos por un
UNCERTAIN histórico del 2026-09-09. Se comprobó que permanecía idéntico al respaldo,
en estado terminal sin reintentos, sin trabajos activos ni envíos SENDING. No se
marcó entregado, no se borró y no se reenviará para resolver la incertidumbre.
Después se continuó la instalación conservando esa cuarentena.

La pausa administrativa quedó habilitada con
`AGENT_OPERATION_CONTROLS_ENABLED=true` solo después de los controles.

Se compararon credenciales y las demás variables previas; únicamente variaron
digest, compatibilidad explícita y habilitación del control. Se preservaron:

- Versión publicada: `01a156e2-e40b-77e8-a08a-4d5d56c08cba`.
- Binding revisión 5; modelo `gpt-6-luna`.
- Cuenta WhatsApp, tokens, claves OpenAI/Meta y APP_MASTER_KEY.
- Configuración, instrucciones, conocimiento e historial de asignación.

No se republicó el agente ni se amplió genéricamente la compatibilidad: se conserva
el mapa explícito de versiones anteriores y sus digests exactos.

## Verificación final

- Backend: 200, PostgreSQL y Redis disponibles.
- Panel interno y público: 200. Web `www.zuvel.ai`: 200.
- Agente, outbound y scheduler: latidos ARQ correctos, sin fallos ni reintentos.
  Los trabajos periódicos normales del scheduler no se confunden con una cola vacía.
- Selección del snapshot exacto, sin fallback ni llamada al modelo.
- Lectura real del servicio de operación: controles disponibles; Zuvel habilitado,
  revisión 1, sin corte de reactivación. Consulta sin escrituras.
- Endpoint administrativo sin token: 401.
- Comparación final de imágenes, configuración publicada y credenciales correcta.

El registro privado final es `post-release-verification.json`. No se probó el botón
pausando un agente real ni se afirma una prueba visual autenticada del panel a
partir de estas comprobaciones. La prueba funcional de pausa/reactivación sigue
cubierta por la suite local; la instalación ya expone los controles para uso real.
