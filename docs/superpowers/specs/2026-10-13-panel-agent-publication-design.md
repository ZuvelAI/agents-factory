# Configuración del panel → agente publicado → WhatsApp

## Objetivo aprobado

Daniel necesita que el agente del cliente Zuvel responda con la marca, saludo,
tono, instrucciones y conocimiento configurados en AI Workers. Los datos ya
guardados deben conservarse. Guardar configura un borrador; probar y publicar
son acciones explícitas. No se cambia el número, la coexistencia, los tokens,
las cuentas de revisión ni la conexión de Meta.

## Evidencia del estado actual

- El onboarding persiste su configuración, pero Knowledge incorpora un bloqueo
  fijo incluso al completar los campos; los siguientes pasos heredan el bloqueo.
- WhatsApp navega a la pantalla de conexión sin representar claramente que el
  número ya está conectado.
- Existen modelos, compilador, versiones y servicio de publicación de AgentSpec.
  La publicación exige evidencia de validación para los digests exactos y falla
  de forma segura cuando dicha evidencia no existe.
- El worker activo usa Milestone2AgentSpecProvider: instrucciones genéricas.
  ProductionAgentSpecProvider existe, pero requiere una instancia enlazada.
- El constructor de instrucciones usa la persona; una referencia de conocimiento
  por sí sola no pone su contenido a disposición del modelo.
- La entrada y la respuesta de WhatsApp ya funcionan. No debe repetirse signup.

## Alternativas y decisión

1. Inyectar directamente el formulario en cada respuesta: rápido, pero guardar
   cambiaría producción sin una versión aprobada. Se descarta.
2. Conectar el onboarding al ciclo existente de versiones, pruebas, publicación
   y asignación por cuenta: recomendado y elegido para este diseño.
3. Construir antes el sistema completo de ingestión multiformato, búsqueda
   vectorial y aprobaciones operacionales: excede esta entrega. Se mantiene como
   trabajo separado, sin simular que está disponible.

## Alcance funcional de esta entrega

### Datos y conocimiento

Conservar tenant_onboarding_configs y todas sus revisiones. Crear una proyección
determinista de la revisión guardada hacia un borrador de AgentSpec, reutilizando
el compilador y ciclo existentes. La identidad comercial, instrucciones, saludo,
tono, tratamiento, idiomas, notas de políticas y límites de operación se incluyen
explícitamente; ningún campo se da por aplicado si el runtime no lo soporta.

El conocimiento inicial será una versión inmutable del texto/resumen aprobado,
nombre de fuente, tipo, referencia, autoridad y revisión declarada. Ese texto
debe estar disponible al agente como contexto de negocio separado de las
instrucciones de seguridad. Una URL o un nombre de PDF solo son procedencia:
no implican descarga, lectura o validación automática del documento. El panel
explicará esta limitación. Se exige revisión confirmada, texto no vacío y cero
conflictos críticos declarados; no se afirma haber detectado conflictos de forma
automática.

Cambiar conocimiento o configuración crea un nuevo borrador y digest. Nunca
reescribe la versión publicada ni reutiliza pruebas de otra revisión.

### Estado de los pasos

Knowledge se completa al disponer de una versión aprobada del contenido que
realmente consumirá el agente, no eliminando a ciegas el bloqueo. Policies,
Human Operations y Approval Routes mantienen sus requisitos y dependencias.
Acciones de alto riesgo que requieran enlace/OTP no se habilitan si ese flujo no
existe. Handoff solo se habilita con una superficie real y controles de conversación
existentes; ninguna promesa de atención humana surge solo de escribir un nombre.

El paso WhatsApp mostrará la cuenta activa que se asignará al agente y su estado,
con acceso opcional a su configuración; no exigirá reconectar una cuenta saludable.
Si hay varias cuentas, el administrador debe seleccionar explícitamente la cuenta
destino. Nunca se elige por nombre o por la primera fila. La cuenta de revisión
no se reasigna automáticamente.

### Probar, validar y publicar

Desde el panel: preparar candidato, probar candidato, revisar resultado y publicar.
El resultado de pruebas incluye fecha, versión, configuración, conocimiento y
código evaluados. Se incorporan evidencias persistidas y auditables al puerto
ProductionQualityGate existente: no se sustituye por un booleano siempre verdadero.

Pruebas mínimas: saludo/identidad de marca, consulta con respuesta presente en el
conocimiento, consulta sin información suficiente, límites de alcance, protección
frente a instrucciones maliciosas y respeto a atención humana. Las pruebas de
modelo no exigen coincidencia literal de todo el texto: verifican comportamientos
definidos, ausencia de hechos inventados y uso del contexto correcto. Los chequeos
deterministas de integridad, aislamiento, herramientas permitidas y digests son
obligatorios. El administrador revisa las respuestas reales antes de aprobar.
La revisión humana queda registrada y ligada al mismo candidato, sin presentarse
como una certificación automática o como todo el Quality Gate v1 del plan maestro.

El botón Publicar muestra cuenta destino y revisión exacta. Publicación y enlace
de cuenta a instancia ocurren en una transacción protegida por rol administrador,
aislamiento por tenant y comprobación de revisión para evitar carreras. Si faltan
pruebas vigentes, revisión o conexión saludable, se rechaza con causa visible.

### Runtime

Resolver la instancia publicada para la cuenta de WhatsApp de la conversación,
no solo para el tenant: tenants pueden tener varias cuentas o agentes. Cargar la
versión PRODUCTION y su conocimiento inmutable, verificar digests y reutilizar
ProductionAgentSpecProvider. Nunca usar un borrador como respuesta real ni volver
silenciosamente al proveedor genérico cuando una cuenta enlazada esté mal configurada.

Para cuentas aún no enlazadas, conservar el comportamiento legado durante la
transición; el panel lo identifica como genérico/no publicado. La cuenta Zuvel
solo cambia de proveedor tras publicación explícita. Versiones antiguas quedan
disponibles para rollback validado. Nuevos mensajes usan la versión activa; una
respuesta en curso mantiene el snapshot con el que empezó.

## Seguridad y datos

Reutilizar autorización PlatformAdmin, auditoría y alcance por tenant. Nuevas
tablas de conocimiento/evidencias/enlaces requieren RLS, claves compuestas por
tenant y restricciones de inmutabilidad. Las referencias y texto empresarial se
tratan como datos no confiables que no pueden modificar reglas de plataforma.
No incluir tokens, claves, documentos de otros tenants ni prompts internos en
la vista de pruebas. Los resultados visibles son las respuestas de prueba y los
datos de configuración autorizados, no secretos del runtime.

## Secuencia de implementación

1. Proyección determinista y versión del conocimiento aprobado; pruebas locales.
2. Preparación de candidatos y visualización del estado real en onboarding.
3. Ejecución/revisión de pruebas y evidencia persistida exacta.
4. Publicación y enlace explícito cuenta–instancia; resolverlo en el worker.
5. Pruebas de regresión, aislamiento, edición posterior, rollback y flujo completo.
6. Despliegue acotado, preservando conexión y datos. Publicar Zuvel desde el panel
   tras revisar la configuración y respuestas con Daniel.

Migraciones se ensayan primero sobre la base desechable. Antes de migrar producción
se verifica el estado real y se prepara recuperación. No se reinician ni modifican
servicios ajenos. No se envían pruebas a clientes reales sin destinatario y contenido
autorizados; las pruebas iniciales usan el panel y fixtures controlados.

## Criterios de aceptación

- Los datos ya ingresados siguen disponibles; estados indican requisitos reales.
- El panel permite probar y publicar una revisión exacta para una cuenta explícita.
- Guardar cambios posteriores no modifica respuestas de la versión publicada.
- WhatsApp usa marca e información publicada de Zuvel y no la persona genérica.
- Sin información, el agente no inventa; sin validación vigente, no publica.
- Aislamiento entre tenants y cuentas probado; cuenta de revisión preservada.
- Rollback no borra borradores, conocimiento ni historial de conversaciones.

## Fuera de alcance

Rastreo web, descarga de PDFs, Drive, embeddings/RAG general, detección automática
de conflictos, nuevas herramientas comerciales, implementación del flujo OTP de
aprobaciones, rediseño de toda la plataforma y cambios de infraestructura. Si la
configuración guardada requiere alguna capacidad no disponible, el panel debe
mostrarla como pendiente, no darla por operativa.
