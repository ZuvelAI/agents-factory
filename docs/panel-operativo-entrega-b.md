# Entrega B — configuración independiente por agente

Estado: editor implementado localmente y revisado; cinco hallazgos importantes
corregidos con regresiones reproducidas. Verificación global local completada
sin excluir pruebas. Aceptación visual e instalación productiva pendientes.

## Qué se puede hacer

- Crear empresa y agentes sin crear números, conexiones ni versiones publicadas.
- Editar por agente identidad, propósito, saludo, tono, instrucciones, idiomas,
  vocabulario, contenido empresarial manual, políticas, operación y modelo.
- Conservar el texto ante un conflicto y comparar con la revisión guardada.
- Editar información compartida e incorporarla al borrador de forma explícita.
- Importar el asistente anterior exclusivamente a la instancia asociada a sus
  candidatos. Fuente ambigua, revisión obsoleta o destino editado se rechazan.
- Ver borrador separado del snapshot publicado. Herramientas de solo lectura;
  guardar preferencias operativas no las habilita.

## Estructura

Un backend, no dos aplicaciones. `configuration_router.py` recibe solicitudes
autorizadas; `configuration_models.py` valida contratos; `configuration_service.py`
coordina reglas y auditoría; `configuration_repository.py` concentra SQL;
`configuration_import.py` encapsula la importación explícita. Las vistas workspace
proyectan el borrador sin confundirlo con AgentSpec de ejecución.

Tablas nuevas: `company_profiles` y `agent_configuration_drafts`, con tenant,
revisión, snapshots, claves compuestas y RLS forzada. Solo el rol administrativo
puede leer/insertar/actualizar bajo contexto de empresa. El runtime no recibe
permisos ni consulta estas tablas. No hay DELETE ni modificación de tablas viejas.

## Evidencia local

- Backend de configuración:15 pruebas pasan, más2 de importación y13 de workspace.
- Panel:125 pruebas unitarias y28 recorridos de navegador pasan; lint, tipos y
  compilación final pasan.
- Suite completa backend definitiva:709 pruebas pasan,0 fallos,0 errores,
  1 advertencia conocida de Starlette/AnyIO. Ejecutada en copia temporal del
  código actual con PostgreSQL local estándar54322, sin exclusiones.
- La ejecución anterior en55322 tuvo668 aprobadas,1 fallo y31 errores; se conserva
  como evidencia histórica, pero ya no es el resultado final de validación.
- Advisors de seguridad de la base de prueba: sin hallazgos.
- Ensayo desde cero: todas las migraciones de aplicación aplicadas a
  `configuration_b_migration_20261015` dentro del contenedor local existente,
  con `auth.users(id uuid)` mínimo para la FK y propietario de instalación
  `supabase_admin`. Diez pruebas iniciales pasan allí; el rol HTTP real sigue
  siendo `agents_factory_admin`. No equivale a instalar/probar todo Supabase Auth.
- Guardados simultáneos contra PostgreSQL: uno200 y otro409; rollback de operación
  cuando falla auditoría; importación repetida no duplica el evento ni la fila.
- Datos de navegador sintéticos; no llamadas Meta/OpenAI ni cobros de API.

## Recuperación y producción

La migración no copia datos automáticamente. Las filas antiguas permanecen.
La recuperación funcional es volver al editor antiguo manteniendo estas tablas;
no ejecutar DROP ni degradar el runtime. No se probaron cambios en hosting,
credenciales, WhatsApp ni agentes activos porque no se modificaron.

Antes de instalar: respaldo productivo, inventario actualizado de asociación
legado/instancia, ensayo autorizado de importación y aceptación visual de Daniel.
Las pruebas/publicación/rollback del nuevo editor se implementan en C con plan
propio. No usar el flujo antiguo para publicar suponiendo que lee el borrador nuevo.

## Límites conocidos

Los modelos habilitados conservan el catálogo existente; sin precios inventados.
No se descargan fuentes automáticamente, no se añade RAG ni conectores nuevos.
Los campos libres son visibles a administradores autorizados; no se promete
detectar automáticamente credenciales pegadas dentro de instrucciones. Auditoría
registra revisiones y secciones, no el texto de instrucciones/conocimiento.

Revisión independiente: ningún hallazgo crítico. Se reprodujeron y corrigieron:
edición durante guardado, pérdida de texto al navegar (incluido Atrás), Enter en
listas, requisitos de validación omitidos y valores rechazados expuestos en422.
La protección422 está acotada a las rutas nuevas de configuración. Una variable
de navegación llamada token disparó el detector del repositorio; se renombró
guardId (no era credencial); las91 pruebas de ese control vuelven a pasar.

Menor corregido: «Sin definir» solo se ofrece cuando el contrato acepta null.
Modelo, tono, presentación, tratamiento, idioma, revisión y opciones operativas
obligatorias ya no permiten vaciar su selección. Las políticas y decisiones
opcionales conservan el valor pendiente. Cuatro pruebas de renderizado y un
recorrido de navegador protegen la distinción y el guardado de valores pendientes.

Instancia antigua sin origen estructurado verificable: no se inventa ni se parsea
el prompt. Puede crearse un agente manual independiente; iniciar manualmente el
mismo UUID requiere una operación de aplicación adicional, no definida en B.
Cambios compartidos hechos por otro administrador se detectan al leer/guardar o
comparar, no mediante polling continuo en una pantalla inactiva.

## Cierre de validación global — 2026-10-15

Se creó el proyecto local independiente `aiworkers-b-verification-6dupvo` en una
copia temporal. Solo se inició PostgreSQL; la CLI de Supabase aplicó todas las
migraciones y el propio test comprobó que su reinicio elimina tablas residuales.
No se reinició el proyecto anterior ni se cambió el puerto esperado por las
pruebas. El esquema Auth es el creado por Supabase, no el stub del ensayo inicial;
no se afirma haber probado el servicio Auth/OAuth productivo.

La copia reutilizó las dependencias instaladas y fijadas. Se desactivó únicamente
la reinstalación automática de pnpm al detectar una carpeta trasladada; no se
desactivaron controles de versión, seguridad ni validación de la base local.
La prueba de cifrado recibió una clave aleatoria efímera, no una clave de producción.

El catálogo estricto detectó9 tablas recientes sin registro de cobertura. Se
añadió `apps/backend/tests/security/agent_table_contracts.py` y una matriz de roles
para conocimiento/publicación, asignaciones, perfiles y borradores. Ambas matrices
forman el catálogo completo; una tabla nueva desconocida sigue haciendo fallar
el guardián. Se verifican lectura propia/ajena, contexto vacío/inválido, rechazo
de reasignación de empresa, borrado e inserción de fila ajena para admin/runtime.
Los borradores solo administrativos prueban la denegación completa al runtime.
No se cambió ninguna política ni permiso de la aplicación para hacer pasar tests.

Resultado del comando completo `python -m pytest -q`:709 passed,1 warning.
Los121 tests unitarios y27 recorridos del panel permanecen aprobados; no hubo
cambios de frontend en este cierre. Los datos de los ensayos son sintéticos.
