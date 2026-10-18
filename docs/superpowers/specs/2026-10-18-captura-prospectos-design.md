# Captura de prospectos por agente

Estado: diseño detallado para revisión de Daniel. El alcance conversacional fue aprobado; este documento no autoriza todavía implementación, migraciones, despliegue ni publicación.

## 1. Objetivo y alcance aprobado

Daniel quiere que un agente pueda registrar oportunidades comerciales reales dentro de AI Workers y revisarlas junto a sus conversaciones. Cada empresa puede tener varios agentes; la capacidad se activa por agente, nunca globalmente por conveniencia.

Se registrará al contacto cuando muestre interés concreto en un servicio, sin esperar necesariamente una solicitud de cotización. Un saludo no basta. Se conservarán nombre, teléfono y usuario disponibles, empresa si la comparte, servicio de interés, resumen de la necesidad, estado inicial «Nuevo» y enlace a la conversación. Los datos desconocidos quedan vacíos y un nuevo mensaje actualiza el prospecto correspondiente, no lo duplica.

Se preservan el estilo del panel aprobado, la conexión WhatsApp, la bienvenida y el comportamiento publicado. No se sustituye el editor ni se reconstruye la plataforma.

## 2. Alternativas y decisión propuesta

1. **Capacidad interna versionada — recomendada.** Usa configuración/publicación del agente, herramientas del runtime y almacenamiento de AI Workers. No requiere cuenta externa y permite controlar aislamiento, evidencia y duplicados.
2. Extraer oportunidades con un segundo análisis automático de cada mensaje. Añade llamadas, posibles demoras y otra lógica de decisión; se descarta como mecanismo inicial.
3. Enviar directamente a un CRM o una hoja de cálculo. Introduce autorización externa, sincronización y fallos adicionales; se reserva para una integración posterior.

La captura se propone durante el turno normal del agente; no se programará otra llamada de clasificación por cada mensaje. El uso de herramientas puede requerir pasos adicionales del modelo y consumir tokens: no se promete costo nulo ni un costo fijo por conversación.

## 3. Qué convierte una conversación en prospecto

Ejemplos positivos:

- «Quiero un agente para atender los clientes de mi negocio».
- «Necesito automatizar el seguimiento de mis prospectos».
- «¿Cuánto cuesta desarrollar una aplicación para mi empresa?».

Ejemplos que no crean prospecto por sí solos: «hola», «gracias», una consulta general sobre qué hace la empresa, una reacción, spam, instrucciones para manipular el sistema o un problema de soporte de un cliente existente sin intención comercial nueva.

El agente debe identificar la necesidad expresada por la persona, no disparar por encontrar una palabra aislada. La evidencia debe referenciar mensajes entrantes reales de esa conversación; una frase del asistente, un saludo que enumera servicios o un documento recuperado no constituye interés del cliente.

La captura no exige completar un formulario. El agente puede pedir empresa o contexto cuando ayude a orientar la conversación, pero no bloqueará el registro por falta de esos datos ni volverá a pedir un teléfono ya entregado por WhatsApp. No inventará empresa, presupuesto, correo, intención de compra ni autorización de seguimiento.

## 4. Datos, identidad y duplicados

El prospecto conserva: identidad interna, empresa administrada, contacto, nombre disponible, teléfono real y usuario opcionales, empresa declarada por el interesado, intereses comerciales, resumen breve, estado «Nuevo», fechas, conversación de origen y última conversación relacionada. Cada captura registra mensaje fuente, agente y versión que la originaron.

La «empresa del prospecto» declarada por el interesado no se confundirá con la empresa dueña del agente. Se reutilizan los perfiles WhatsApp existentes; no se copia el historial entero ni se usa el nombre como identificador único.

Reglas de identidad:

- El alcance siempre incluye la empresa administrada. Nunca se comparte un prospecto entre clientes de AI Workers.
- Con teléfono real explícito, el contacto se identifica por ese teléfono normalizado dentro de la empresa; varios agentes o cuentas de esa empresa pueden actualizar la misma oportunidad.
- Sin teléfono, se conserva la identidad de proveedor con su cuenta/alcance verificados. Un BSUID numérico no se transforma en teléfono.
- Nombre y usuario sirven para mostrar, no para fusionar registros ni autorizar acciones.
- Un enlace posterior entre identidad opaca y teléfono solo se acepta con asociación explícita del proveedor. Si ya existen registros incompatibles, se señala el conflicto para revisión; no se fusionan ni eliminan a ciegas.

Se mantiene un prospecto agregado por contacto identificado y empresa en esta entrega. Nuevos servicios de interés se añaden sin borrar los anteriores. Datos ausentes no borran valores conocidos; una corrección explícita del cliente sí puede actualizar un campo, conservando su procedencia. Un cambio del nombre de perfil no reemplaza silenciosamente un nombre expresado por el cliente.

Reintentos del mismo mensaje/operación no agregan capturas duplicadas. La base de datos impone unicidad y el servicio maneja carreras concurrentes, no se depende solo de comprobar primero si existe una fila.

## 5. Arquitectura y límites de responsabilidad

Se añade un módulo de prospectos dentro del backend existente, separado en contratos, servicio de aplicación, repositorio y lectura administrativa. No se crea otro backend, otro worker ni un CRM completo.

La capacidad propuesta es `lead_capture`, con una operación interna de propuesta de captura. El modelo solo propone datos comerciales y referencias de evidencia; empresa administrada, cuenta, contacto, conversación, mensaje, agente y versión se resuelven desde contexto confiable del servidor. No admite identificadores de otra empresa proporcionados por el modelo.

El adaptador valida argumentos y prepara una intención acotada, sin escribir un prospecto ni ejecutar servicios externos durante la llamada del modelo. Al finalizar el turno, el servicio de aplicación vuelve a comprobar control de conversación, versión/binding y permiso publicado; persiste prospecto, evidencia, respuesta y trabajo de salida dentro de la misma transacción. El envío a WhatsApp continúa por el outbox existente.

Si una persona tomó control, cambió la versión activa o la herramienta perdió autorización durante el turno, no se guarda una captura obsoleta ni se envía una confirmación de guardado incorrecta. La reanudación usa la política limitada de reintentos existente; no repite escrituras a ciegas.

Los manifiestos y validadores deben reconocer el almacenamiento interno como operación real autorizada, sin fingir una conexión CRM ni eliminar la validación de otras herramientas. La implementación integrará esta única capacidad, no habilitará conectores declarados como no disponibles.

## 6. Activación, pruebas y publicación

En la edición de cada agente aparecerá una tarjeta «Guardar prospectos», con descripción y estado. Empieza desactivada en agentes existentes y nuevos. Guardar el borrador no cambia producción.

Activarla incorpora la capacidad y su permiso a una versión compilada específica. Se conserva la secuencia de preparar, probar, revisar y publicar explícitamente en el canal seleccionado. Ninguna publicación de esta capacidad se deduce de aprobar el desarrollo.

Las pruebas interactivas y escenarios mostrarán las propuestas de captura como simuladas, con sus datos y motivo, pero nunca insertarán prospectos reales ni ejecutarán conectores externos. La revisión debe cubrir positivos y negativos, información incompleta y ausencia de interés. Herramienta no habilitada significa cero propuestas ejecutables aunque el mensaje o instrucciones pidan guardar un prospecto.

## 7. Experiencia del panel

Se reutilizan tema oscuro, tarjetas y detalle progresivo aprobados. Se añade «Prospectos» a la navegación operativa, con lista paginada y filtro por empresa y agente de captura. Búsqueda por nombre, teléfono, usuario o empresa declarada; el alcance empresarial se aplica antes de buscar.

Cada fila muestra identidad disponible, interés principal, resumen corto, estado «Nuevo», última actividad y acceso a la conversación. El detalle despliega intereses, datos disponibles y procedencia. Si participaron varios agentes, se identifica la atribución real de las capturas; no se adjudica todo al agente actual.

Desde la conversación se podrá abrir el prospecto relacionado. Una conversación sin interés comercial no aparecerá como error por carecer de prospecto. No se añaden envío manual, campañas, tareas comerciales, asignaciones, un tablero de ventas ni nuevas etapas de CRM en esta entrega.

Antes de implementar las pantallas se presentará una imagen de la lista y del detalle con datos ficticios, siguiendo la preferencia de Daniel de revisar la interfaz antes del desarrollo. Esta imagen no se presentará como una función ya existente.

## 8. Seguridad, privacidad y errores

Se exige autorización administrativa para consultar prospectos. Nuevos datos con RLS y claves/relaciones empresariales comprobadas; sin lectura pública, sin acceso cruzado y sin secretos dentro de instrucciones, argumentos, listados o auditoría.

Solo se guarda información comercial necesaria. No se añade inscripción a campañas ni se interpreta conversar como permiso para marketing. Una negativa explícita a registrar datos debe bloquear nuevas capturas para ese contacto y mostrarse al administrador; el mecanismo mínimo de supresión se incluirá en el plan. Solicitudes de eliminación siguen el procedimiento administrativo de privacidad, no provocan un borrado automático desde el modelo.

Auditoría de creación/actualización con referencias y resultado, sin volcar conversaciones completas o credenciales. Datos de prueba claramente separados y no persistidos como prospectos productivos.

No se confirma «guardado» si la persistencia falló. Un error no borra el contacto ni la conversación. Una captura inválida se rechaza con motivo seguro; los fallos transitorios se reintentan con límites e idempotencia. La capacidad deshabilitada conserva los prospectos históricos y no desconecta WhatsApp.

## 9. Aceptación

- Saludo sin interés: cero prospectos; solicitud concreta: un prospecto con evidencia real.
- Varios mensajes o reentrega: misma oportunidad, sin duplicar captura ni borrar intereses.
- Dos agentes de la misma empresa y contacto verificablemente igual: un prospecto, atribuciones correctas.
- Empresas diferentes, nombres iguales e IDs de distinto tipo: no se mezclan.
- Perfil sin nombre/usuario/teléfono: conserva lo disponible sin inventar; campos opcionales no bloquean la captura.
- Correcciones, conflicto de identidad y negativa a registrar datos tienen comportamiento explícito y probado.
- Agente deshabilitado, humano al mando, versión cambiada durante el turno o prueba simulada: no hay escritura productiva indebida.
- Preparar/guardar no publica. La versión previa sigue atendiendo hasta aprobación y publicación explícitas.
- Lista y detalle escapados, paginados, utilizables con teclado y en móvil; errores y vacíos comprensibles.
- No regresan los asteriscos visibles, no se repite la bienvenida a contactos existentes ni se cambia la conexión o clave.

## 10. Entrega y autorización

Secuencia: revisión de este diseño, imagen de pantallas, plan técnico con pruebas y recuperación, implementación local, revisión de resultados y autorización separada de instalación/publicación. Se mantienen cambios ajenos, tablas e historial existentes.

Fuera de alcance: CRM externo, Google Sheets, calendario, campañas, scoring automático, orquestación entre agentes, migración Railway, captura retroactiva masiva y limpieza destructiva. No se fijan nombres ni cantidad de tablas sin completar el inventario del plan; la separación lógica no implica multiplicar tablas innecesariamente.

Autorrevisión: no quedan decisiones «TBD» ni campos requeridos inventados. La unicidad se basa en evidencia de identidad, no en nombres; las capturas simuladas y reales están separadas; el guardado queda ligado a la autoridad vigente al commit. Este documento requiere aprobación antes de preparar el plan e implementar.
