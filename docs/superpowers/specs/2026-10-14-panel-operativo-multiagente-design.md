# AI Workers: panel operativo por empresa y agente

Estado: propuesta funcional para revisión de Daniel. No autoriza implementación,
migraciones, despliegue ni cambios en agentes activos.

## 1. Objetivo y decisiones confirmadas

Daniel administrará varias empresas; cada una puede tener uno o varios agentes.
Necesita una interfaz bonita, moderna y resumida para entender qué hace cada
agente, observar conversaciones y editar toda su configuración. El trabajo con
Codex sigue siendo otra vía de administración, no una fuente de datos paralela.

Dirección visual aprobada: tema oscuro de Zuvel, acento morado, tarjetas por
empresa/agente, navegación corta y detalle progresivo. Referencia conceptual:
`/Users/daniel/.codex/generated_images/019ff7cf-b61b-7671-9738-5e4074d9f114/exec-ce516f83-ac70-4913-96d7-8ada558c0edb.png`.
Los nombres, métricas y conversaciones de esa imagen son ficticios; no prueban
funciones existentes ni datos reales.

El panel es interno para Daniel y administradores autorizados en esta entrega.
Un portal con acceso de clientes es un producto separado, no se deduce de este
diseño. Migrar a Railway y analizar Leti también son trabajos separados.

## 2. Alternativas y recomendación

1. Cambiar solo estilos del asistente actual: menor cambio, pero conserva el
   recorrido complejo y la configuración única por empresa. No resuelve el objetivo.
2. Panel operativo sobre los servicios existentes, ampliando configuración por
   agente: recomendado. Preserva conversaciones, publicación y conexión actual.
3. Reconstruir plataforma y migrar hosting a la vez: mezcla riesgos, dificulta
   comparar resultados y recuperar el servicio. Se descarta para esta entrega.

## 3. Qué existe y qué debe ampliarse

El checkout de trabajo ya contiene panel Next.js, backend Python, instancias y
versiones de AgentSpec, conocimiento aprobado, evidencias de prueba, publicación,
enlace por cuenta de WhatsApp y lectura administrativa de conversaciones.
`tenant_onboarding_configs` guarda actualmente una configuración por empresa.
No se afirma que ya permita borradores independientes para múltiples agentes.

Se reutilizan el compilador, los controles de acceso, auditoría, pruebas y
publicación. Se amplían los contratos para identificar empresa e instancia de
agente en cada edición, prueba y publicación. El esquema exacto y los cambios de
API se documentarán en el plan tras aprobar este diseño; no se inventan aquí
nombres de tablas como si ya existieran.

## 4. Navegación y pantallas

Menú principal: Resumen, Empresas, Conversaciones, Actividad y Ajustes.

### Resumen y empresas

Resumen presenta conteos reales, pendientes y accesos a empresas. Empresas ofrece
búsqueda y tarjetas con nombre, agentes y estado resumido. La cantidad de agentes
es dinámica, incluso cero. No se rellenan datos ni indicadores con ejemplos.
Nueva empresa solicita identidad básica y crea un espacio sin conectar WhatsApp
ni publicar agentes. Ver empresa abre su lista de agentes.

### Empresa

Cabecera con identidad compartida y botón Nuevo agente. Cada tarjeta indica
nombre, propósito, estado de publicación, canal y capacidades realmente activas.
Abrir agente muestra su ficha; Conversaciones filtra empresa y agente.
Nuevo agente crea un borrador independiente; no copia conexiones ni secretos.
Una empresa sin agentes muestra una invitación a crear el primero.

### Agente: entender primero, editar después

La ficha resume propósito, tono, conocimiento, capacidades, integraciones, modelo,
canal asignado, versión activa y fecha de publicación. Se distingue siempre
"Publicado" de "Borrador": ninguna descripción editable se presenta como activa.

Secciones editables:
- Identidad: nombre, propósito, tono, saludo, idiomas e instrucciones.
- Conocimiento: contenido empresarial, fuentes, procedencia y revisión.
- Capacidades: herramientas permitidas, límites y requisitos reales.
- Integraciones: conexiones, estado, permisos y agentes autorizados a utilizarlas.
- Operación: políticas, derivación humana, límites y aprobaciones soportadas.
- Modelo: selección entre modelos habilitados y parámetros soportados.

Guardar borrador conserva cambios sin afectar producción. Probar cambios prepara
una versión exacta y muestra sus respuestas. Publicar exige las pruebas vigentes,
revisión y confirmación del destino. Historial permite inspeccionar diferencias
y volver a una versión previamente publicada mediante rollback validado.

La prueba interactiva lateral no envía mensajes a WhatsApp ni ejecuta acciones
externas con efectos reales. Las herramientas se simulan de forma explícita en
esa superficie; una comprobación real de conexión es una acción distinta. No se
presenta una simulación como verificación de una integración.

### Conversaciones

Lista filtrable por empresa, agente, cuenta y estado. Al abrir una conversación:
mensajes con hora, dirección, estado de entrega cuando esté disponible y agente/
versión utilizada cuando haya evidencia. No se atribuye retrospectivamente todo
el historial al agente que está activo hoy.

Buscar y paginar evita descargar todo el historial. Las conversaciones sin
atribución verificable se identifican como tales. El historial importado y el
tráfico nuevo se diferencian; cero conversaciones no significa canal desconectado.
La intervención humana y devolución al agente reutilizan controles reales. No
se incluye envío manual desde el panel sin definir y verificar ese flujo aparte.

### Actividad y ajustes

Actividad muestra cambios administrativos, publicaciones, pruebas y errores
operativos con fecha, alcance y enlace al objeto afectado. Oculta secretos y
datos sensibles innecesarios. No expone trazas internas completas al navegador.
Ajustes contiene identidad compartida, administración permitida y conexiones.
Costos solo se muestran con fuente y alcance identificados: no se presenta como
costo total una cifra que omita Meta, OpenAI o infraestructura.

## 5. Reglas de múltiples agentes y canales

Empresa contiene agentes; cada agente tiene identidad estable, borrador propio,
versiones, pruebas y publicaciones. La identidad empresarial puede compartirse,
pero editarla no reescribe versiones ya publicadas. Cada agente muestra cuándo
su borrador necesita incorporar una actualización de información compartida.

Para esta primera entrega un número de WhatsApp tiene un único agente responsable
activo. Una empresa puede tener varios agentes y varios números; puede guardar
agentes sin canal. Reasignar un número requiere confirmación explícita y evidencia
válida del agente destino. Nunca se elige por nombre o por primera fila.

Varios agentes colaborando automáticamente sobre el mismo número requerirían
reglas de enrutamiento y transferencia: no se habilitan ni se prometen en esta
entrega. Un borrador sin canal puede probarse, pero no figura como atendiendo.

## 6. Una configuración, dos formas de administrarla

Panel y operaciones realizadas con Codex usan los mismos servicios de aplicación,
permisos, revisión esperada y auditoría. No se adopta la edición directa de filas
como flujo administrativo. Codex no necesita exponer secretos al chat para operar.
Una modificación simultánea se rechaza por conflicto de revisión y ofrece recargar
y comparar; no sobrescribe silenciosamente cambios del otro administrador.

Credenciales se guardan mediante el mecanismo seguro existente, nunca en texto
visible ni en instrucciones. Conectar un proveedor requiere su autorización real.
Una conexión compartida de empresa no habilita automáticamente herramientas para
todos sus agentes. Las capacidades no implementadas aparecen como no disponibles,
con motivo, en vez de un interruptor que prometa un comportamiento inexistente.

## 7. Estados, errores y seguridad

Se muestran por separado publicación (sin publicar/publicado/cambios pendientes),
ejecución (atendiendo/pausado/error/sin canal) y conexión (conectada/desconectada/
requiere revisión/desconocida). Atendiendo exige señales comprobables y recientes;
una versión publicada por sí sola no acredita salud. Se indica última verificación.

Errores legibles ofrecen el siguiente paso sin filtrar tokens ni consultas. Una
caída de conexión no borra la configuración. Un agente publicado inválido no
responde silenciosamente con un asistente genérico. Se preservan aislamiento por
empresa, autorización administrativa, inmutabilidad y trazabilidad.

Pausar afecta nuevas respuestas automáticas, no elimina datos ni desconecta Meta;
el tratamiento seguro de respuestas ya pendientes debe probarse antes de habilitar
el control. Archivar un agente impide nuevas asignaciones y exige retirar primero
sus canales; conserva historial. No hay eliminación definitiva en esta entrega.

## 8. Transición y límites

Primero se inventarían rutas, contratos y uso real de tablas. El agente de Zuvel
actual se representa conservando instancia, versión, conocimiento y cuenta; no
se repite Embedded Signup. La configuración heredada se migra de forma explícita
al agente correspondiente, con respaldo, comprobación y recuperación ensayada.
Nunca se copia el mismo borrador a todos los agentes por conveniencia.

Secuencia de entregas: lectura y navegación; configuración independiente por
agente; pruebas/publicación; capacidades e integraciones soportadas; verificación
completa y despliegue autorizado. Cada entrega debe ser utilizable y verificable.
El panel antiguo permanece como recuperación mientras se valida la sustitución.

Fuera de alcance: migración Railway, portal de clientes, facturación, nuevos
conectores arbitrarios, orquestación multiagente en un número, nueva plataforma
de ingestión/RAG, limpieza destructiva de tablas y copia de arquitectura de Leti.
La auditoría de tablas puede recomendar simplificaciones, no autoriza borrarlas.

## 9. Criterios de aceptación

- Una empresa con uno y otra con varios agentes se representan sin duplicación.
- Editar un agente no modifica otro ni altera una versión publicada.
- Cada pantalla distingue datos activos, borrador y estados desconocidos.
- Configuración y capacidades visibles coinciden con el snapshot de ejecución.
- Pruebas, revisión, publicación y rollback conservan los controles existentes.
- Empresa, agente, cuenta y versión quedan atribuidos sin filtrar otros clientes.
- Credenciales y acciones con efectos reales no aparecen en pruebas simuladas.
- Conflictos concurrentes, errores de conexión y ausencia de datos son comprensibles.
- Navegación por teclado, contraste, foco, estados de carga/error y diseño adaptable
  funcionan; la estética no sustituye accesibilidad ni evidencia operacional.
- Conversaciones, conexión y comportamiento aprobado de Zuvel se conservan.

## 10. Revisión requerida

Daniel debe revisar este documento, especialmente la edición completa y la regla
de un agente activo por número. Aprobarlo permite preparar el plan de ejecución;
no equivale todavía a autorizar su implementación ni la migración de producción.
