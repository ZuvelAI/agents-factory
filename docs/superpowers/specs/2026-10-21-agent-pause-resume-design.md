# Pausa y reactivación por agente

Estado: diseño conversacional aprobado; documento pendiente de revisión de Daniel.
No autoriza todavía implementación ni despliegue.

## Objetivo y alcance

Daniel necesita detener y reactivar las respuestas automáticas de un agente desde
el panel, sin desconectar WhatsApp, borrar conversaciones, modificar su versión
publicada ni afectar otros agentes. Al reactivar se atenderán únicamente mensajes
nuevos; los anteriores no se reproducen ni generan una cola de respuestas tardías.

Es un cambio arquitectónico: intervienen recepción, procesamiento y entrega.
Esta entrega no incluye archivo, nuevas integraciones, envío humano desde el
panel, migración Railway, cambio de credenciales ni eliminación de código legado.

## Alternativas y decisión

1. Control persistente compartido por panel y trabajadores, con comprobaciones en
   recepción, generación y envío: recomendado y aprobado conversacionalmente.
2. Pausar únicamente la generación: insuficiente porque deja salir respuestas
   previamente preparadas.
3. Desconectar el canal: descartado porque impide conservar la recepción normal.

## Estado y servicio de operación

Un estado persistente por empresa e instancia de agente distingue habilitado de
pausado y conserva una revisión monotónica. Es independiente del borrador, de la
publicación y de la salud de conexión. La migración es aditiva y conserva como
habilitados los agentes existentes. Un agente sin canal no se presenta atendiendo.

Un servicio de aplicación único aplica pausa/reactivación con autorización
administrativa, empresa e instancia explícitas, revisión esperada y auditoría.
Solicitudes concurrentes obsoletas devuelven conflicto sin sobrescritura. Repetir
la misma operación no crea una nueva ventana de elegibilidad ni revive trabajos.

Pausar y reactivar no publica, reasigna ni modifica una cuenta. Las asignaciones y
las publicaciones no eliminan implícitamente una pausa existente. Un agente nuevo
sin canal puede mantener su estado habilitado sin aparentar disponibilidad.

## Mensajes elegibles y pendientes

La admisión persistida de cada mensaje entrante registra el agente responsable y
la revisión operativa aplicable. La transición y esta admisión se ordenan mediante
un bloqueo transaccional compartido; no dependen del reloj del navegador ni de la
hora en que un trabajador atrasado empieza a ejecutar.

Cada transición invalida la revisión anterior. Solo se generan y envían respuestas
si la revisión capturada coincide con la vigente y el agente sigue habilitado.
Los mensajes admitidos durante una pausa conservan historial pero nunca se
reencolan automáticamente. Los admitidos antes de la pausa cuyos trabajos sigan
pendientes tampoco vuelven a ser elegibles tras reactivar.

La deduplicación conserva la admisión original: un webhook repetido no convierte
un mensaje viejo en nuevo. Los eventos de historial importado no son mensajes
nuevos elegibles. Para mensajes retrasados por Meta, se combina el corte de
reactivación con la marca temporal del proveedor: un mensaje con fecha anterior
al corte no obtiene respuesta por llegar tarde; marcas ausentes o inválidas se
retienen sin automatización y con motivo observable.

La restricción cubre respuestas de texto, notas de voz y respuestas técnicas
automáticas. No impide recepción, estados de entrega ni intervención humana
existente. El historial conservado puede servir de contexto para una consulta
nueva, pero no dispara por sí mismo respuestas a consultas anteriores.

## Límite de envío y carreras

Antes de iniciar una entrega a Meta se valida de nuevo la revisión y se coordina
con la transición de pausa. Al confirmarse la pausa no pueden iniciarse nuevas
entregas automáticas del agente. Una petición ya iniciada o aceptada por Meta no
se puede retirar; el panel debe advertir esta limitación, sin prometer cancelación.

Las respuestas aún no iniciadas se bloquean con motivo auditable; no se borran ni
se reenvían al reactivar. Una generación o transcripción ya iniciada puede terminar
y consumir su costo, pero su resultado no se entrega si perdió elegibilidad.
Las entregas inciertas mantienen su tratamiento seguro existente sin reintentos
que puedan duplicar mensajes. No se sostiene una transacción de base de datos
abierta durante toda una generación de IA.

## Panel y errores

La ficha de cada agente muestra Pausar o Reactivar, estado vigente y última
modificación. La confirmación de pausa explica que se guardan mensajes sin
respuesta automática y que un envío ya iniciado podría llegar. Reactivar explica
que únicamente se responderán mensajes nuevos.

La interfaz muestra carga, conflicto y error sin confirmar cambios optimistamente
antes de persistirlos. Si falla la lectura del control operativo, los trabajadores
no asumen permiso para enviar; conservan evidencia del fallo sin exponer secretos.
Los cambios se reflejan también en los resúmenes de empresa sin confundir pausa
con desconexión. Archivar sigue no disponible en esta entrega.

## Verificación y aceptación

- Pausa de A no modifica ni bloquea al agente B ni a otra empresa.
- Recepción durante pausa conserva mensaje, contacto e historial sin respuesta.
- Reactivación atiende el primer mensaje nuevo y no recupera mensajes anteriores.
- Trabajos demorados, duplicados y ciclos rápidos pausa/reactivación no evaden el corte.
- Un webhook retrasado con fecha anterior no dispara una respuesta tardía.
- Pausa durante generación, transcripción y preparación bloquea la entrega pendiente.
- Carreras entre pausa y envío respetan el límite de entrega ya iniciada.
- Publicación, rollback y cambio de asignación no reactivan un agente pausado.
- Autorización, aislamiento, conflictos de revisión y auditoría tienen pruebas.
- Panel accesible y estados reales se verifican con pruebas de interacción.
- Las pruebas no requieren llamadas pagas ni mensajes reales de clientes.

## Instalación y recuperación

El plan posterior detallará migración, permisos mínimos, módulos, pruebas y orden
de instalación. Requiere respaldo y ensayo de recuperación. No se vuelve a un
trabajador que ignore pausas mientras existan agentes pausados o trabajos con
revisiones invalidadas: la recuperación debe mantener el bloqueo de envío.
No se despliega ni se cambia el estado del agente Zuvel durante esta revisión.
