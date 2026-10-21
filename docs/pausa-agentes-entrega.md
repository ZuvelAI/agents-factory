# Pausa y reactivación de agentes

Estado: implementación y revisión independiente completadas en local; instalación
en producción no realizada. Los controles permanecen deshabilitados por defecto.

## Uso

En Empresa → Agente → Operación del agente:

- Pausar exige confirmación. WhatsApp sigue conectado y conserva los mensajes.
- Reactivar exige confirmación y atiende únicamente mensajes nuevos. No recupera
  respuestas pendientes de antes de la pausa ni mensajes recibidos durante ella.
- Un envío ya iniciado hacia Meta puede llegar; la pausa no promete retirarlo.
- Publicación, borrador, modelo, clave de OpenAI y otros agentes no cambian.
- Recargar estado permite resolver conflictos sin repetir una operación incierta.

Un estado habilitado no acredita que el agente esté atendiendo: conexión,
publicación y operación se presentan por separado. Archivo e integraciones nuevas
siguen fuera de esta entrega.

## Estructura

`apps/backend/src/agents_factory/modules/agent_operations/`:

- `models.py`: contratos de estado y solicitudes estrictas.
- `repository.py`: estado persistente y claves de exclusión por agente.
- `service.py`: transición administrativa, revisión e historial de auditoría.
- `admission.py`: decisión inmutable al recibir el evento de WhatsApp.
- `runtime_guard.py`: comprobaciones de herramientas y cierre de respuesta.
- `delivery_guard.py`: exclusión del despacho y comprobación final de autoridad.
- `router.py`: API administrativa; no conecta proveedores ni publica versiones.

El panel usa `lib/agent-operations.ts` y los componentes/acciones de operación.
Panel y trabajadores comparten el mismo estado, sin configuraciones paralelas.

## Persistencia y seguridad

Migraciones aditivas:

1. `20261021142146_agent_operations.sql`: estado por empresa/agente; los agentes
   existentes se inicializan habilitados. Nuevas instancias se inicializan en el
   servicio de creación, no al leer la página.
2. `20261021143242_agent_message_admissions.sql`: admisión por evento entrante,
   con agente, revisión operativa y revisión de asignación. No se actualiza ni borra.

Ambas tablas tienen RLS forzada, claves compuestas y sin acceso público. El
trabajador puede leer estado e insertar admisiones; no puede cambiar una pausa.
La API exige administrador y revisión esperada. Repetir una transición idéntica
no mueve el corte temporal ni invalida mensajes nuevos innecesariamente.

El mensaje se crea después en otro trabajador, por eso la admisión referencia
`source_event_id`. Un webhook repetido conserva la decisión original. La ejecución
rechaza mensajes sin admisión, revisiones antiguas o asignaciones cambiadas.

Los mensajes antiguos entregados tarde no se vuelven nuevos por llegar después.
Las fechas de Meta se comparan estrictamente con el corte de reactivación; una
fecha con precisión de segundos dentro del mismo segundo del corte no acredita
que el mensaje sea posterior. Se conserva sin automatización.

Una fecha inválida o ausente en un mensaje vivo firmado se conserva con hora de
recepción, marca `_provider_timestamp_valid=false`, payload original y motivo
`invalid_timestamp`. Esa hora de recepción nunca habilita una respuesta ni actualiza
el perfil de contacto. Historial, mensajes humanos, identidad de origen y firma
conservan su validación estricta.

Los descartes dejan auditoría sin cuerpo de mensajes, credenciales o transcripciones.
Una transcripción ya pagada puede quedar READY aunque se pause durante su ejecución;
se conserva sin encolar una respuesta. No se repite la llamada por reactivar.

## Envíos y bloqueos

Se reutiliza la única conexión de despacho existente. Orden de exclusión:
conversación → cuenta → agente. La pausa usa la misma clave de agente y espera a
un despacho ya iniciado antes de confirmar. No se mantiene una transacción SQL
abierta durante el HTTP del proveedor ni, en el trabajador, durante el modelo.

Las respuestas pendientes no elegibles quedan BLOCKED con motivo
`agent_operation_ineligible`. Los envíos SENDING de resultado desconocido conservan
UNCERTAIN; no se vuelven a enviar. Un fallo de lectura no concede permiso.
Cancelación o fallo libera/invalida la conexión para no dejar bloqueos pendientes.

Cada llamada al modelo dentro del ciclo del SDK vuelve a comprobar la admisión,
incluida la que seguiría a una herramienta ya iniciada. Si pierde autoridad,
el turno queda bloqueado y auditado, sin respuesta ni consumo de otra iteración.
Los lotes mixtos de mensajes y desconexiones resuelven todas sus cuentas antes
de adquirir un bloqueo de agente; un cambio de mapeo obliga a reintentar el lote
completo en vez de adquirir una cuenta nueva en orden inverso.

Una plantilla aprobada no constituye autoridad automática. Las plantillas manuales
con preparación auditada de un administrador siguen siendo manuales y no se
confunden con respuestas del agente. No se añadió envío humano desde el panel.

## Habilitación y despliegue posterior

`AGENT_OPERATION_CONTROLS_ENABLED` es false por defecto. Solo controla la API de
administración; desactivarla nunca hace que los trabajadores ignoren pausas ya
persistidas. La API informa `controls_available`; el panel deshabilita el control
si falta esa evidencia o no puede consultar el estado.

Esta entrega no autoriza cambios de producción. Antes de instalar:

1. Inventariar nuevamente imágenes, Compose, emisores, procesos y revisiones reales.
   No asumir que los nombres/tags de documentos anteriores siguen vigentes.
2. Preparar respaldo privado de esquema y datos con dependencias, manifiesto de
   servicios/variables sin exponer valores, imágenes recuperables y restauración
   aislada comprobada. Incluir mensajes, admisiones, estados, asignaciones, outbox,
   audio y auditoría; no respaldar únicamente las dos tablas nuevas.
3. Mantener el control administrativo deshabilitado. Aplicar las dos migraciones
   aditivas en orden y verificar RLS/permisos e historial de migración.
4. Durante la sustitución, impedir que trabajadores antiguos reciban nuevos trabajos;
   drenar o detener de forma controlada agentes, scheduler y despacho antiguos.
   Los trabajos anteriores sin admisión no deben generar respuestas retrospectivas.
5. Instalar todos los trabajadores compatibles, incluido outbound, y después el
   backend receptor. Verificar el mismo código esperado en cada emisor y ausencia
   de emisores antiguos. Preservar Redis, cuentas, tokens y webhooks existentes.
6. Mantener compatibilidad explícita de las versiones publicadas ya aprobadas y sus
   digests; no ampliar la lista indiscriminadamente ni volver a publicar Zuvel.
7. Instalar el panel; comprobar salud y lectura/operación en un entorno de prueba.
   Solo entonces habilitar el control administrativo y confirmar que el panel
   lo refleja. No pausar Zuvel para una comprobación sin acordar su impacto.

## Recuperación segura

Deshabilitar botones no constituye recuperación del envío. Nunca restaurar un
binario antiguo que ignore pausas mientras existan agentes pausados o trabajos
invalidados. Preferir mantener las migraciones aditivas y recuperar con una imagen
compatible; no borrar tablas ni reducir revisiones en una base activa.

Si fuera necesario recuperar datos desde respaldo, detener primero todos los
emisores y conservar evidencia de los envíos posteriores al respaldo. No reiniciar
la cola restaurada automáticamente: reconciliar o bloquear los pendientes de
resultado incierto, incluidos audios cuyo inicio de proveedor no pueda probarse.
Establecer los agentes en pausa mediante el servicio auditado antes de habilitar
trabajadores; reactivar después crea una nueva revisión que invalida las admisiones
anteriores. La instalación queda bloqueada si no puede demostrarse esta recuperación.

## Verificación local

Se usan PostgreSQL/Redis locales y modelos, transporte y transcripción falsos.
No se consultó ni modificó información de clientes en producción. No hubo llamadas
pagas, mensajes reales de prueba, cambios de claves ni publicación de agentes.

Resultados finales del 21 de octubre de 2026:

- Backend completo: 1.024 pruebas aprobadas, incluidos dos clientes, texto/audio,
  mensajes pendientes, reactivación, fechas inválidas y las regresiones finales.
- Panel: 161 unitarias y 49 Chromium; tipos, lint y compilación correctos.
- Seguridad: 72 pruebas generales, 53 de aislamiento con roles reales, 454 pgTAP
  de matriz RLS, 115 de fundamento y 18 específicas de operación. Lint de base
  sin errores; asesores sin errores de seguridad.
- Ruff limpio; mypy sin errores en los siete módulos finales revisados.
- Restauración completa de una base local artificial: pausa en revisión 7,
  admisión denegada en revisión 6, dependencias y RLS forzada conservadas.
  No sustituye el respaldo/ensayo aislado de producción previo a instalar.

La revisión independiente encontró dos problemas importantes: otra iteración de
modelo después de pausar durante una herramienta e inversión de bloqueos en un
lote mixto de ingreso/desconexión. Ambos se reprodujeron RED y se corrigieron GREEN
en una única pasada; la suite completa posterior pasó. No hubo hallazgos críticos.
También se restauró el contrato estricto de fechas del historial con tres casos
RED y sus regresiones GREEN, sin debilitar la retención de mensajes vivos.

Pendiente menor: evaluar índices de las claves foráneas de admisiones con carga
representativa. El asesor los marca como información de rendimiento, no como fallo
de seguridad. No se agregaron índices por intuición ni se alteraron tablas ajenas.

La revisión no acredita inventario/emisores, recuperación real de producción ni
comportamiento de proveedores reales: esas comprobaciones siguen siendo requisito
de una instalación posterior autorizada. No se hizo push, merge ni despliegue.
