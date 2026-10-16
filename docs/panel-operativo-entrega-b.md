# Entrega B — configuración independiente por agente

Estado: implementada localmente; revisión final en curso. No instalada en producción.

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

- Backend de configuración, importación y workspace:27 pruebas pasan.
- Panel:121 pruebas unitarias y22 recorridos de navegador pasan.
- Suite completa backend:665 pasan,1 falla,31 errores de preparación,1 advertencia.
  El fallo es `test_database_gate_removes_stale_schema_state` (tabla residual de
  ensayo); los31 errores corresponden a suites que exigen el puerto canónico y
  rechazan55322. No presentar esta suite completa como aprobada.
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
