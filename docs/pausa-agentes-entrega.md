# Pausa y reactivación de agentes

Estado: implementación local; instalación en producción no realizada. La revisión
independiente y las comprobaciones finales se registran al cerrar esta entrega.

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

Evidencia anterior al cierre final: backend 1.011 pruebas; panel 161 unitarias,
49 de navegador, tipos, lint y compilación correctos. Los nuevos casos integrados
de dos empresas, texto/audio, corte antes del modelo y fechas inválidas pasaron
junto con los contratos Meta seleccionados (51 pruebas). El cierre final registra
los resultados completos posteriores a esos ajustes y la revisión independiente.
