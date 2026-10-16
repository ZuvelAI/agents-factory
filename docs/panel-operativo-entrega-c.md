# Entrega C — pruebas y publicación por agente

Estado: implementación local, sin despliegue, llamadas API reales ni cambios en
clave OpenAI, WhatsApp, coexistencia, webhooks o infraestructura productiva.
Plan aprobado: `docs/superpowers/plans/2026-10-16-panel-pruebas-publicacion-por-agente.md`.
El panel anterior y los cambios ajenos se conservan.

## Qué permite

Desde `/tenants/{empresa}/agents/{agente}/test`: preparar una versión del borrador
guardado, conversar con ella de forma aislada, ejecutar escenarios, revisar sus
respuestas y publicar explícitamente en un número elegido. Ninguna cuenta se
elige automáticamente. Se muestra la versión actual del destino incluso si
pertenece a otro agente de la misma empresa. Hay historial y recuperación de
versiones publicadas compatibles; recuperar no reemplaza el borrador.

Preparar/guardar/probar/aprobar NO envían WhatsApp ni publican. Preview no es
evidencia aprobable. Las herramientas están deshabilitadas en las pruebas; esto
no certifica integraciones operativas. La UI distingue el chequeo técnico de la
revisión de calidad humana. No hay saludo genérico de respaldo si falla el modelo.

## Garantías y límites

- Evidencia ligada a empresa, instancia, versión, revisión de agente/empresa,
  digests y código. Dos agentes con revisión1 no comparten candidatos/pruebas.
- Conocimiento congelado por versión; propósito incorporado a las instrucciones.
- TTL de pruebas24h. Editar después conserva historial, pero impide aprobar o
  publicar evidencia obsoleta. Las rutas recalculan vigencia bajo locks.
-30 previews y6 suites por hora/empresa/agente. Cada suite hace5 llamadas al
  modelo y un control humano local; el costo depende del consumo real.
- Preview:1–20 mensajes, alternados y terminados en usuario;2000 caracteres por
  mensaje de usuario,8000 por respuesta,20000 en conjunto; salida8000. La UI conserva
  hasta9 turnos completos recientes dentro de ese límite y permite reiniciar la
  conversación de prueba. La política de historial se explica en pantalla.
- Clave repetida con mismo contenido devuelve el mismo run; contenido distinto409.
  Otra solicitud mientras hay una pendiente del mismo tipo/candidato devuelve409.
  Reentrega con resultado guardado no vuelve a llamar al modelo. Una caída tras
  la llamada y antes del commit todavía puede causar consumo externo repetido:
  no se promete facturación exactamente una vez.
- Polling visible cada2s, máximo2min; luego consultar estado, nunca repetir a ciegas.
- Publicación confirma número, revisión del binding y agente reemplazado. Una
  carrera pierde con409, sin publicación parcial. Auditoría fallida revierte todo.
- RLS y privilegios mínimos; runtime no obtiene acceso a perfiles/borradores.
- Contratos tipados y errores seguros; ninguna credencial llega a componentes.

## Recuperación e instalación futura

No hay cambios productivos que revertir en esta entrega. Antes de instalar:
respaldo probado, ensayo de migraciones y aprobación expresa. Aplicar ambas
migraciones C antes de desplegar API/worker/UI compatibles. Para desactivar la
función, retirar los accesos/rutas nuevos sin borrar tablas, versiones o evidencia.
Una reversión operacional no es DROP de historial ni restauración del borrador.

Migraciones: `20261016122850_workspace_agent_publication.sql` (procedencia, una
tabla) y `20261016123657_workspace_publication_test_origins.sql` (runs existentes).
No se reescriben resultados previos; se identifican LEGACY/SCENARIOS por defecto.

## Verificación local

- Backend completo y workers mediante la suite raíz:743 passed, una advertencia
  existente de Starlette/AnyIO, sin fallos ni exclusiones; modelo falso, sin API.
- Frontend después de correcciones:135 pruebas unitarias y37 recorridos Chromium;
  lint, tipos y build correctos. Captura real sintética revisada;390px y1440px sin
  desbordamiento. Nueve recorridos específicos cubren el flujo nuevo.
- Ruff y Mypy de9 módulos nuevos: correctos.
- Reset desde cero de todas las migraciones en proyecto Supabase independiente:
  correcto. Upgrade desde esquema/código bbc54fd con una publicación legacy real
  sintética: los hashes y recuentos de versiones, runs, resultados, revisiones,
  deployments y bindings coinciden antes/después. También se comprobó db lint
  local: sin errores de esquema. No se ejecutaron advisors de un proyecto remoto.
  El ensayo aislado de upgrade usa auth.users mínimo como dependencia de FK;
  no certifica el servicio Auth. El reset desde cero sí usa el proyecto Supabase
  desechable completo para el esquema de arranque.

## Revisión independiente y decisiones

Revisión única del rango bbc54fd..8391730: ningún crítico, cinco importantes.
Se corrigieron en una pasada con pruebas: identidad estable y payload conservado
al reintentar, run aceptado conservado aunque falle GET; cursor/sección y runs
seleccionados conservados con consulta exacta; recuperación disponible sin
candidato; límites compatibles de respuesta/historial; comparación del snapshot
aprobado completo (conocimiento/procedencia, modelo y reglas), no solo prompt.
El navegador cubre además recuperación legacy, reintento ambiguo, evidencia fuera
de la primera página y texto sin enviar en página posterior.

Hallazgo menor aplazado explícitamente: el resumen general heredado aún interpreta
un borrador existente como cambios pendientes y contiene un aviso de futura
entrega en sus secciones no disponibles. La pantalla de publicación usa procedencia
y estado exactos. Ajustar esa proyección antes de la aceptación productiva; no se
oculta el límite ni se atribuye una versión a todos los números.

Lo que el revisor no juzgó: despliegue, credenciales y WhatsApp vivos (sin autoridad
para tocarlos); calidad/costos del modelo real (sin llamadas); conectores/pausa/
archivo (fuera de C); auditoría visual propia y totales completos (verificados por
el implementador). Estas exclusiones no se presentan como pruebas superadas.

La repetición final detectó una prueba previa inestable de alertas: received_at
empataba dentro de la transacción y el UUID podía ordenar distinto a la inserción.
Se reprodujo con IDs controlados y se cubrieron ambos órdenes esperados. No cambió
la consulta real ni se omitió la prueba; el recuento final incorpora ese caso extra.

Decisiones de implementación: migraciones aditivas separadas; pruebas del worker
ubicadas en integración backend para reutilizar DB/roles reales;409 mientras hay
otra prueba pendiente del mismo tipo en vez de reutilizar un prompt distinto;
gate y vistas separados para evitar ciclos; paginación por sección. Se conserva
la transacción de exclusión del worker existente, sin prometer exactamente una vez
en el proveedor ante caída. No se añadieron servicios ni dependencias.

## Fuera de esta entrega

Integraciones con efectos reales, pausa/archivo, migración Railway y eliminación
del legado no se habilitan aquí. El saludo inicial solicitado por Daniel queda
pendiente: presentación completa solo en primer contacto; si hay pregunta puntual,
responderla después en el mismo mensaje. No se ha cambiado el agente activo.

Ensayo API real propuesto, no ejecutado: hasta6 llamadas (1 preview y5 escenarios)
con la clave existente sin modificarla; autorización y acceso seguro por separado.
Esto no publicaría ni enviaría WhatsApp. Instalación productiva requiere otra
confirmación expresa.
