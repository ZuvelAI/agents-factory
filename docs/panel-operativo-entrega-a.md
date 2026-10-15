# Panel operativo — entrega A local

Fecha: 2026-10-14. Diseño aprobado por Daniel, implementación directa autorizada.
Estado: implementación local verificada; revisión independiente final pendiente.
No desplegado. No hay migraciones, nuevas credenciales ni llamadas reales a Meta
u OpenAI durante estas pruebas. Zuvel sigue atendiendo con su versión instalada.

## Disponible en esta entrega

- Menú de cinco accesos y tema oscuro/morado, reutilizando marca y fuentes locales.
- Empresas con búsqueda, conteos reales de la página y vista previa de agentes.
- Empresa con cero, uno o varios agentes, identificados por UUID y no por nombre.
- Ficha de configuración publicada y borrador separados; detalle desplegable.
- Conocimiento e instrucciones de la versión, modelo y referencias a herramientas.
- Estados desconocidos explícitos: publicar no significa que el worker esté sano.
- Registro operativo de conversaciones por empresa, agente y cuenta, paginado.
- Mensajes con atribución de versión persistida y estado de entrega cuando exista.
- Actualización cada45s, suspendida con pestaña oculta o edición de filtros.
- La selección de otra empresa limpia filtros dependientes de agente/cuenta.
- Accesos a administración anterior; guardado/publicación permanecen sin cambios.

No se habilitan todavía creación de empresa/agente, edición independiente,
prueba interactiva, nuevos conectores, pausa ni archivo. Son entregas B/C con
planes específicos antes de programar. Botones pendientes deshabilitados y
explicados, no simulados como funciones activas.

## Cambios respecto al mapa inicial del plan

- AgentPage añade company_name para identificar también empresas sin agentes.
- Se conserva la vista anterior /conversations sin tocar su trabajo previo.
  La nueva navegación usa /conversation-log y endpoints de lectura bajo
  /admin/agent-workspace; ambos consultan los mismos datos operativos.
- Se preservan los archivos de conversaciones previos sin incluirlos en commits.
- La atribución usa messages.agent_spec_id y su versión dentro del tenant;
  nunca el enlace actual de WhatsApp. Mensajes sin evidencia no se atribuyen.
- El archivo histórico importado de coexistencia permanece separado y se explica
  en pantalla: no se presenta como mensajes operativos ya sincronizados.
- Las versiones heredadas no tienen nombre/tono/propósito independientes: el
  nombre empresarial se identifica como tal; campos ausentes no se inventan
  extrayendo texto del prompt. La entrega B añadirá la edición estructurada.

## Evidencia ejecutada

- Baseline:13pruebas existentes de formato aprobadas.
- Nuevos endpoints:404esperado antes de implementación;8integraciones aprobadas
  sobre PostgreSQL local, con aislamiento, permisos admin/noadmin, paginación,
  versión publicada/borrador, salud sin mensajes y salida sin credenciales.
- UI:fallo por rutas ausentes antes de implementar;116unitarias aprobadas.
- Navegador:17pruebas completas aprobadas, incluidas rutas anteriores de
  autenticación, publicación, alertas y WhatsApp. Seis prueban el panel nuevo.
- Fixture de empresa sin agentes alterada temporalmente0→1:el nuevo caso falló;
  restaurada0, suite verde. Ningún cambio temporal quedó en producto.
- Filtro dependiente:prueba falló al conservar agente al cambiar empresa;
  corrección verificada en navegador. Etiquetas exactas accesibles corregidas.
- TypeScript y ESLint completos:sin errores. Mypy en cuatro módulos nuevos:sin
  errores. Ruff acotado y git diff --check:sin errores.
- Suite backend sin filtros ejecutada:646aprobadas,1fallo y31errores de preparación.
  El fallo es test_database_gates::test_database_gate_removes_stale_schema_state
  por tabla histórica task3_review_stale_marker ya existente. Los31errores son
  test_secret_tenant_isolation y test_tenant_isolation_matrix, que rechazan el
  puerto local55322 por requerir el puerto canónico. No se alteraron esos guardas.
- Regresión excluyendo esos tres archivos:646aprobadas,1advertencia deprecación
  preexistente de Starlette/anyio. No equivale a una suite completa aprobada.

No se aplicaron migraciones ni se ampliaron permisos/RLS para que pasaran lecturas.
El cliente pnpm se ejecutó desde la caché11.24.0 fijada por el proyecto, sin
actualizar dependencias. Los tests de UI usan fixtures sintéticas; las consultas
de persistencia se validaron por separado contra PostgreSQL desechable.

## Revisión visual

Capturas reales del navegador local, con datos sintéticos, en
apps/control-plane/test-results/agent-workspace-empty-comp-bd031-in-explicit-and-recoverable-chromium/:
empresas.png y agente.png. Se conserva el estilo aprobado con menús reducidos,
tarjetas, detalle progresivo y foco visible. Interacciones verificadas a390y1440px;
la revisión visual no sustituye las pruebas de permisos ni de interacción.

## Próxima puerta

Revisión independiente de ce460da..HEAD y una única pasada de correcciones si
aparecen hallazgos importantes. Después Daniel revisa esta entrega local antes
de preparar B/C o autorizar cualquier instalación en producción. Railway sigue
separado. No fusionar, subir ni archivar el checkout ni borrar datos históricos.
