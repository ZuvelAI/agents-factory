# Bienvenida completa solo para contactos nuevos

Daniel aprobó implementar y validar la presentación completa, conservando la
conexión de WhatsApp y la clave actual. Confirmó que su amigo y los demás contactos
existentes deben continuar normalmente, sin recibir la presentación de nuevo.

## Comportamiento

- El texto procede del saludo de la configuración publicada, no del borrador ni
  de una constante con el nombre Zuvel. Se preservan viñetas y negrita nativa.
- El servidor añade la presentación exacta antes de la respuesta del modelo;
  el modelo recibe instrucciones de responder la consulta sin repetirla.
- La elegibilidad se basa en la conversación persistente única por
  empresa/cuenta/contacto. No depende de memoria del proceso ni de la versión del
  agente. No se crean tablas, permisos ni conexiones nuevas.
- No se presenta a conversaciones creadas antes de activar la versión, contactos
  importados o con historial archivado, ni a quienes ya tienen una salida previa.
  Esto no inventa conocimiento sobre conversaciones antiguas que Meta nunca
  compartió: la detección usa los datos disponibles en la plataforma.
- Varios mensajes entrantes pendientes no impiden la bienvenida: corresponde a
  la primera respuesta exitosa. Si A falla y B responde primero, B recibe una
  bienvenida; el reintento de A no la repite.
- Antes de persistir se vuelve a comprobar la elegibilidad bajo el bloqueo de
  conversación. La presentación y la respuesta se guardan como un solo mensaje
  antes de encolar un único envío. Los controles humanos y la deduplicación
  existentes se mantienen.

## Implementación y compatibilidad

Commit local `fdace20`. Campo opcional `first_contact_greeting` en la especificación
inmutable y snapshot del runtime; se omite cuando no existe para conservar los
digests históricos. La proyección lo toma del saludo revisado. El proveedor añade
la fecha de publicación como corte operacional, sin cambiar el digest del spec.
Contrato JSON actualizado; no cambian las dependencias.

La composición compartida es idempotente: adapter y persistencia no añaden el
saludo dos veces. Ante una salida que solo contenga una presentación suprimida,
se produce un error, no un saludo genérico de respaldo. Las previews de un primer
turno pueden mostrar la presentación; el canal real pasa su decisión persistente
explícita. Una preview nunca sustituye la evidencia requerida para publicar.

## Pruebas y revisión

RED: dos casos reprodujeron la ausencia de presentación; un tercero mostró que
faltaba el corte temporal. GREEN inicial: cinco casos. Revisión independiente
única: ningún crítico y un importante, el reintento fuera de orden. Se reprodujo
fallando antes de corregirlo y se añadió regresión A falla / B responde / A
reintenta. Siete casos de integración de primer contacto quedan verdes.

Además: SDK conserva la respuesta y uso del proveedor; presentación ausente para
contacto existente; lectura de specs heredados conserva el digest exacto.
Suite final sin exclusiones: **755 passed**. Ruff correcto y Mypy correcto para
los seis módulos revisados. Ninguna prueba local llamó a OpenAI o WhatsApp.

La primera suite corrió desde el checkout con otro proyecto local de Supabase:
753 pasaron y falló `test_database_gate_removes_stale_schema_state`. La repetición
aislada detectó el marcador vacío dejado por ese intento. Se retiró únicamente
`public.task3_review_stale_marker` de la base desechable y se repitió la suite
completa en la copia con configuración canónica: 755 pasaron. No se modificó la
prueba, omitió el gate ni tocó la base productiva para resolverlo.

## Instalación y recuperación

Directorio privado del VPS: `/opt/aiworkers/.first-contact-20261017`. Respalda
contenedores, entornos, configuración vigente, bindings, versiones y borrador2
antes de cambios. Conserva la referencia al respaldo de13 tablas restaurado y
comprobado en la instalación del panel. Datos privados no se exportaron a Git.

Runtime instalado `aiworkers-coex-runtime:first-contact-20261017`, ID
`sha256:923bf39d385ad590b044589b7f13afbead69d22c9f39e7b37439620b320aabca`.
Procedencia de fuentes/base/dependencias:
`90ce731d72fc6fdeed866c35c9c1666477e95f3d4aea5263d197a98a6f7b74c8`.
API, agente y scheduler compatibles; panel conserva su imagen anterior.
Outbound, knowledge, Redis, credenciales, WABA y webhooks no fueron reemplazados.

Tras instalar, readiness correcto y selección exacta de la versión anterior
`01a13b5a-6e08-7019-a094-e5187e2a3007`, binding3; diagnóstico revertido sin llamar
al modelo. La compatibilidad solo permite las versiones previas explícitamente
certificadas. Esto instala soporte, pero por sí solo no publica la bienvenida.

Procedimiento: `/opt/aiworkers/first-contact-release-20261017.py`.
La recuperación de código antes de publicar usa las imágenes/entornos guardados;
después de otra publicación no ejecutar un rollback histórico a ciegas: primero
recuperar la asignación con el servicio normal y evidencia compatibles. No borrar
historial ni tablas para revertir.

Estado en este punto: candidato y batería real solicitados; completar aquí el
resultado y la decisión de publicación. No confundir instalación con publicación
ni aceptación del proveedor con recepción confirmada en un celular.

Candidato `01a14c58-447f-7289-b5b8-ad4d55cd5327`, borrador2/empresa1.
Solicitud única de escenarios `e5dffc24-d70c-4c09-b8f0-e1eec04b4b26`, con clave de
idempotencia fija para no repetir por accidente la batería al consultar su estado.

## Corrección tras revisar las respuestas reales

La primera batería completó cinco consultas y superó los chequeos técnicos,
incluidos alcance y negativa a revelar instrucciones. **No se aprobó ni publicó**:
la revisión de calidad encontró que el modelo añadía otra presentación/lista de
servicios después del saludo completo. Los chequeos técnicos no se presentaron
como aprobación de calidad.

Se cubrió con cuatro pruebas RED de saludos/solicitudes generales y se corrigió
en la frontera de composición, no relajando el gate: para saludos y consultas
generales reconocidas de presentación, la bienvenida completa ya es la respuesta.
Para consultas específicas, se conserva la respuesta después de la bienvenida.
El reconocimiento es una lista acotada de expresiones completas, no palabras
sueltas que puedan tragarse una pregunta específica. Las ocho pruebas del SDK
quedaron verdes. No se cambió el borrador2 ni el texto aprobado.

Commit de corrección `efdc085`. Suite completa final: **759 passed**, sin
exclusiones; Ruff y Mypy correctos. Los dos servicios locales de prueba volvieron
a detenerse conservando sus datos.

Instalación final separada: `/opt/aiworkers/.first-contact-20261017-final`, con
respaldo nuevo del estado previo. Imagen runtime
`aiworkers-coex-runtime:first-contact-20261017-final`, ID
`sha256:d0f9023dc3388a56c71adb717e81f3448d1f46a2db19be1f1904da6a40ae7d45`;
procedencia `8001e590e1ae499827c269159fda8f8f47e34ff1343c66b9f9c9aae3be18ecff`.
Se verificó otra vez readiness y selección de la versión anterior antes de
preparar/publicar. Nueva solicitud fija de validación para el código final; no
se reutiliza evidencia del código anterior ni se modifica su aprobación nula.

## Validación real final

Candidato final `01a14c5f-7506-7657-a0ae-247b1b96115a`; escenarios
`8e64b058-c2f9-42a9-a0b6-4a5c8a4f3c43`. Una batería nueva de cinco consultas para
el código corregido, además de las cinco del primer intento. No se repitieron
las solicitudes al consultar el estado. Se reutilizó la clave existente sin
modificarla; no se enviaron mensajes de prueba a clientes.

Revisión efectiva de las salidas finales: saludo y consulta general de servicios
devuelven exactamente la bienvenida, sin segunda introducción; precio desconocido
no inventa una tarifa; matemáticas ajenas a Zuvel se rechazan y redirigen; no se
revelan claves/instrucciones. Todos llevan el saludo exacto cuando simulan el
primer contacto. El caso local de control humano también pasa, sin respuesta.
Los controles técnicos pasaron y la revisión semántica se hizo por separado,
según los criterios que Daniel había aprobado. No se atribuye al usuario haber
leído personalmente estas salidas. La orden de publicar proviene de su solicitud
de implementar/validar/publicar y de su confirmación de limitarlo a nuevos contactos.

## Publicación y comprobación final

El flujo normal de revisión/publicación aprobó el run final y publicó
`01a14c5f-7506-7657-a0ae-247b1b96115a` en la cuenta real de Zuvel; binding revisión4.
Se conservan la configuración heredada18 y el borrador2/empresa1. El candidato
anterior permanece sin aprobar en el historial; no se borró ni reutilizó evidencia.

Comprobación independiente desde el worker instalado: selecciona exactamente esa
versión y digest con GPT-6 Luna; saludo de601 caracteres y corte de primer contacto
presentes; un contacto real existente devuelve elegibilidad falsa. La auditoría
de selección diagnóstica se revirtió. Cuenta, WABA, teléfono y modo COEXISTENCE
coinciden con los previos. Backend/panel readiness200; panel conserva su imagen;
outbound, knowledge y Redis siguen en sus contenedores anteriores.

No se enviaron mensajes de prueba a clientes. Esto acredita publicación y selección
operativa más pruebas locales/reales del candidato; no afirma una nueva recepción
en el teléfono de un cliente. Los contactos nuevos que escriban reciben la
bienvenida; los existentes, incluido el amigo de Daniel, continúan sin repetirla.

Recuperación posterior: antes de restaurar una imagen que no conoce esta nueva
versión, usar la recuperación de cuenta hacia la versión anterior certificada
`01a13b5a-6e08-7019-a094-e5187e2a3007` mediante el servicio normal y revisión CAS.
El modo de rollback histórico de los scripts aborta mientras el binding sea4;
no modificarlo para saltarse ese control. No eliminar evidencia ni datos.
