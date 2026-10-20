# Prospectos — entrega local

Fecha: 2026-10-19. Implementación local; no instalada ni activada en producción. Referencia visual aprobada: `docs/design/prospectos-20261018.png`. Las capturas del navegador usan personas y empresas ficticias.

## Uso y alcance

En la ficha de cada agente: **Editar borrador → Capacidades e integraciones → Guardar prospectos**. Guardar modifica solo el borrador, protegido por revisión esperada y aviso de cambios sin guardar. Después requiere preparar candidato, probar, revisar y publicar en el canal elegido. Las versiones anteriores siguen atendiendo sin esta capacidad; deshabilitarla no borra prospectos históricos ni desconecta WhatsApp.

La sección **Prospectos** lista contactos con interés comercial por empresa y agente de captura. Permite buscar nombre, teléfono real, usuario o empresa declarada. Lista y fuentes tienen páginas de hasta veinte elementos y cursores ligados al alcance. El detalle se puede abrir aunque no esté en la página actual; conserva agente, versión, evidencia y enlace a la conversación exacta. Vacíos, fallos de consulta, supresión y conflicto de identidad se muestran por separado. Conversaciones ofrece el enlace inverso cuando existe ficha.

No hay envío manual, campañas, CRM externo, scoring, etapas de venta, eliminación automática ni captura retroactiva. «Nuevo» es el único estado comercial. La empresa del interesado no es la empresa dueña del agente.

## Estructura del backend

```text
Mensaje original de WhatsApp → contexto de identidad verificado
                                ↓
Versión publicada con permiso → propuesta del modelo (sin escritura)
                                ↓
Fin del turno → control humano + versión/canal vigentes + evidencia original
                                ↓
Transacción: identidad + prospecto + evidencia + respuesta + outbox
                                ↓
Lecturas administrativas → panel de Prospectos y conversación de origen
```

Módulo: `apps/backend/src/agents_factory/modules/leads/`. Contratos en `models.py`; identidad en `identity.py`; persistencia en `repository.py`; reglas en `service.py`; herramientas puras en `runtime_tools.py`; autoridad y efectos del turno en `turn_effects.py`; negativa directa en `privacy.py`; simulación sin persistencia en `simulation.py`; lecturas en `read_models.py`, `read_repository.py` y `admin_router.py`. El worker existente ejecuta el turno; no se añade otro servicio desplegable.

| Tabla | Responsabilidad |
| --- | --- |
| `lead_subjects` | Identidad interna y preferencia persistente de no capturar. Puede existir sin prospecto. |
| `lead_subject_keys` | Alias tipados: teléfono real dentro de la empresa, identidad de proveedor dentro de empresa/cuenta. |
| `lead_prospects` | Una ficha agregada por identidad y empresa; datos disponibles, intereses y resumen. |
| `lead_capture_events` | Evidencia acotada e inmutable con mensaje, conversación, agente y versión originales. |

Migración aditiva: `20261018211730_lead_capture.sql`; depende del esquema de contactos `20261018194714_whatsapp_contact_profiles.sql`. Las cuatro tablas tienen RLS forzada, claves empresariales, sin grants de Data API. App/admin acceden con contexto de empresa; actualizaciones limitadas por columna, sin DELETE; eventos/alias no tienen UPDATE. No hay tablas por cliente o agente ni funciones security-definer nuevas.

## Reglas y límites

- El saludo, agradecimiento o catálogo del asistente no constituyen interés comercial. El modelo decide la semántica; validación estricta comprueba citas literales de mensajes entrantes persistidos del mismo hilo, incluido el actual. No se puede garantizar que una inferencia semántica del modelo sea siempre correcta; la fuente se mantiene visible.
- Empresa, cuenta, contacto, agente y versión los determina el servidor, no los argumentos del modelo. Teléfono y BSUID con iguales dígitos son identidades de distinto tipo; nombres/usuarios no fusionan fichas. Asociación posterior solo con evidencia explícita del proveedor. Conflictos se señalan, nunca se fusionan o eliminan automáticamente.
- Los campos ausentes no borran valores. Las correcciones explícitas conservan evidencia; nombre declarado prevalece sobre perfil. El resumen está sintetizado, no es una cita verificada. Los intereses nuevos no borran anteriores.
- Locks de alias/identidad y unicidad por mensaje/operación evitan duplicados; todos los efectos se confirman junto a respuesta/outbox. Si hay control humano o cambia la autoridad durante el modelo, se rechaza el resultado obsoleto y aplica el reintento limitado existente. No se promete entrega externa ni facturación «exactamente una vez».
- Una negativa directa inequívoca puede registrar solo preferencia de supresión, también bajo control humano. El detector directo es deliberadamente conservador y no cubre toda paráfrasis posible; la herramienta de supresión del agente cubre el resto cuando está autorizada. El historial truncado no borra la preferencia. Solicitar borrar datos requiere el procedimiento administrativo, no un DELETE del modelo.
- Las herramientas producen intenciones PREPARED, no afirmaciones de persistencia. Propuestas inválidas, autoridad perdida o fallos transitorios no deben producir confirmación de guardado ni escritura parcial. Auditoría guarda referencias y resultados, no conversaciones completas ni credenciales; rechazos de esquema tienen errores genéricos seguros.
- Vista previa y escenarios usan las mismas herramientas puras, pero no repositorios/escrituras. Un valor `simulated=true` no autoriza nada. Candidatos con captura requieren resultados v2 con nueve escenarios (ocho turnos de modelo y un control local). Evidencia v1 de seis escenarios sigue válida solo para candidatos antiguos; TTL, digest, revisión y aprobación siguen obligatorios.
- No se añade otro clasificador de pago por mensaje. Las iteraciones de herramientas pueden añadir solicitudes y tokens al turno normal. Ocho turnos de prueba no equivale a ocho solicitudes facturadas. Se conserva la clave/modelo existentes; no se han efectuado llamadas reales en esta implementación.

## Verificación

Entorno aislado: copia `/private/tmp/aiworkers-b-verification.6DUpVo`, PostgreSQL local 54322 y Redis 56379. Modelo y Meta sustituidos por dobles; navegador con servidores ficticios 3130–3132. El checkout activo conserva los cambios de contactos anteriores sin incluirlos indiscriminadamente en los commits de prospectos.

Antes de las correcciones de revisión: backend 857/857, panel 144/144, navegador 42/42. Después de corregir: backend **860/860**, panel **145/145**, navegador **42/42**, compilación/tipos/lint aprobados; mypy de quince módulos y Ruff aprobados. Las pruebas cubren identidad tipada, alias posteriores, concurrencia, citas ajenas/de asistente, empresa inventada, supresión, rollback, control humano, cambios de autoridad, simulación, compatibilidad heredada, permisos y aislamiento; el navegador comprueba filtros, selección fuera de página, HTML literal, teclado, móvil/escritorio, borrador independiente y vínculo a la conversación.

Ensayo de actualización local: reset hasta contactos, inserción de cuenta/conversación/perfil/versiones ficticias, aplicación solo de prospectos y comparación de digest de todas las tablas públicas anteriores: sin cambios. El control de seguridad incluye recreación completa desde migraciones. Un primer intento del script oficial detectó uv global 0.12.19 en vez del 0.12.5 fijado; se reutilizó la versión correcta ya instalada y el entorno de dependencias verificado, sin cambiar versiones o excepciones de seguridad.

Control oficial `check_repository_security.sh`: aprobado; 72 pruebas de seguridad, 46 de matriz de roles/secretos, pgTAP 424 de aislamiento e inventario y 115 fundacionales, sin errores de esquema. Los advisors mantienen recomendaciones de rendimiento anteriores (incluida política SELECT permisiva duplicada de bindings) e índices nuevos aún sin uso tras recrear una base vacía; no se eliminaron índices ni políticas para silenciar recomendaciones.

EXPLAIN de la consulta real bajo `agents_factory_admin` y RLS con cinco mil prospectos ficticios: página reciente de 21 filas, 0,158 ms; búsqueda por subcadena con una coincidencia, 3,722 ms. Solo escenario sintético local, sin historial de capturas voluminoso ni concurrencia productiva: no es una promesa de capacidad o latencia. Se mantienen los índices compuestos previstos, sin añadir extensiones o índices de texto prematuramente.

Revisión independiente única (rango `ee7ec85..5a4f851`): sin críticos; encontró prevalencia de supresión ante alias posterior, inversión de locks de publicación, dependencia Git de contactos no incluida, incompatibilidad de más de cien intereses e inventario pgTAP incompleto. Los cuatro defectos propios se corrigieron en una pasada con pruebas que reprodujeron los fallos. Daniel autorizó el 19 de octubre guardar los prerrequisitos de contactos por separado: `ba6294c` (identidad, persistencia, lectores administrativos necesarios y migración), `68020bb` (presentación de contactos). La separación de fragmentos se comprobó desde Git y corrigió en `7ac538b`/`881e292`, sin incorporar enrutamiento de salida, ajustes de signup ni la vista heredada pendiente.

Se comprobó el árbol guardado, no solo el checkout integrado: copia `/private/tmp/aiworkers-leads-clean.Ocuuvr`, código en `881e292`, dependencias fijadas reutilizadas, sin fuentes no guardadas. Único ajuste temporal de configuración: identificador del proyecto Supabase local para apuntar a la base aislada existente, además de los tipos generados por Next. Resultado: **851/851 pruebas backend, 134/134 unidades de panel, 42/42 navegador, tipos/lint/compilación aprobados, Ruff y mypy de dieciséis módulos aprobados**. Los nueve casos adicionales backend y once de panel del checkout integrado pertenecen a cambios pendientes de envío/signup/vista heredada que no se incluyeron; ninguna prueba guardada se excluyó. El primer ensayo encontró el identificador local predeterminado y el siguiente un marcador residual de aquella prueba; se reconstruyó la base aislada y se repitió la suite completa hasta pasar, sin tocar fuentes ni relajar comprobaciones.

El requisito Git señalado por la revisión queda resuelto para contactos/prospectos. La autorización se limita a guardado y verificación local: rama `codex/whatsapp-coexistence` conservada, sin merge, push, PR o despliegue. Los cambios pendientes ajenos y los registros de ejecución se conservan para la conciliación previa a una futura instalación.

Deuda menor de la revisión resuelta el 19 de octubre: `agent-testing-panel.tsx` ya no afirma cinco llamadas fijas. Distingue turnos del modelo de solicitudes API y advierte que el costo depende de iteraciones y tokens, manteniendo el aviso de ocho turnos con captura. Cambio exclusivamente de texto; modelo y configuración intactos. Verificación del checkout integrado: 145 unidades de panel, nueve escenarios de navegador de publicación, tipos y lint del componente aprobados.

No ensayado: modelo real y su exactitud semántica, tráfico real de Meta, carga productiva, respaldo productivo restaurado, instalación o publicación. El ensayo sintético de rendimiento no es una garantía de capacidad del hosting. Antes de habilitar, probar respuestas y propuestas del candidato exacto con la clave actual requiere autorización por su costo.

## Futura instalación y recuperación

Inventario de solo lectura del 19 de octubre: backend y panel saludables con imágenes `aiworkers-coex-runtime:contacts-20261018` y `aiworkers-coex-dashboard:contacts-20261018`. Los trabajadores de agente/scheduler usan `first-contact-20261017-final`, outbound `format-gpt6-286a2f0` y knowledge `e437e8c`; no se cambiaron ni reiniciaron servicios. Comparación SHA-256 de fuentes del backend instalado: `whatsapp/meta_provider.py`, `whatsapp/schemas.py` y `whatsapp/signup_service.py` coinciden con el checkout integrado, pero no con HEAD. Por tanto, las correcciones pendientes de esos tres archivos están efectivamente instaladas y desplegar el HEAD actual las perdería. `tenants/admin_router.py` coincide tanto con HEAD como con producción. Esta comprobación no certifica equivalencia de las fuentes del panel compilado ni de los demás trabajadores. Hace falta autorización adicional para guardar los prerrequisitos pendientes y luego autorización de instalación; esta inspección no hizo escrituras productivas ni llamadas a modelos/Meta.

1. Autorizar instalación por separado. Inventariar release, migraciones, snapshot activo y canales reales; no asumir que los IDs locales corresponden a producción. Conciliar antes de desplegar los cambios previos de envío BSUID, signup/timeout y vista heredada que deliberadamente siguen fuera de estos commits: podrían estar instalados y no se debe sustituir su comportamiento por un HEAD incompleto respecto a producción. Preparar respaldo de base y verificar su restauración aislada antes de tocar producción.
2. Aplicar migración aditiva; instalar runtime/API/workers compatibles y después panel. Mantener captura apagada y snapshot publicado intacto. No cambiar clave, modelo, conexión ni hosting.
3. Comprobar salud, permisos administrativos y regresión de conversaciones/contactos. La nueva captura sigue sin publicarse hasta revisar un candidato y evidencia nuevos, y confirmar explícitamente su canal.
4. Si falla instalación, volver al release compatible anterior dejando tablas aditivas intactas; no hacer DROP ni restaurar indiscriminadamente sobre mensajes nuevos. Si falla una publicación posterior, reasignar el snapshot anterior por el flujo de publicación existente; detener nuevas capturas conservando evidencia. Si se necesita restaurar datos, detener escrituras y acordar ventana/pérdida antes de hacerlo.

No hay UPDATE directo para encender capacidad; no se incluyen credenciales ni instrucciones que alteren producción automáticamente.

## Decisiones de implementación

1. Revalidar identidad y evidencia desde el evento original persistido al aplicar; no aceptar contexto del modelo ni perfil cacheado como autoridad. Si el proveedor no aporta asociación válida, se declina la captura.
2. Contratos específicos de las tablas de prospectos dentro de la matriz real de roles, manteniendo descubrimiento completo. Costo: otra fixture explícita, no menos comprobaciones.
3. Supresión conservadora para todos los subjects en un conflicto sin fusionarlos. Tras la revisión también prevalece la negativa histórica y se conserva su fecha/mensaje originales. Si la asociación del proveedor fue errónea, puede requerir revisión administrativa de privacidad.
4. Fence transaccional de ciclo de cuenta compartido entre runtime y escritores de autoridad, sin ampliar permisos UPDATE del runtime. Debe adquirirse antes del bloqueo de fila de cuenta en publicación/rollback; todos los escritores deben respetar el orden. Costo: protocolo cooperativo y pruebas de concurrencia en los flujos completos.
5. Herramientas puras nuevas por turno en vez de estado mutable en el arranque del worker. El límite es un turno y la simulación reutiliza la fábrica.
6. Negativa directa sin agente autor: preferencia de sujeto y auditoría con referencia al mensaje, no evento comercial atribuido a un agente inventado. El contexto nulo nunca autoriza una captura.
7. Reutilizar la delegación de escenarios ya existente en el worker, sin otro coordinador. Integridad y esquema del candidato siguen controlando revisión/publicación.
8. Ocho turnos de modelo no son ocho solicitudes facturadas; iteraciones y tokens varían. La interfaz debe advertirlo y no prometer costo fijo.
9. Congelar nombre opcional del agente en candidatos nuevos con captura, omitiendo null para preservar digests heredados. Snapshots antiguos sin etiqueta muestran nombre no registrado; nunca se atribuyen al nombre mutable posterior.
10. Referencias de subjects conflictivos, determinadas por servidor, en evidencia append-only para mostrar el aviso sin fusionar. Eventos antiguos sin referencias no pueden etiquetarse retrospectivamente; la supresión sigue siendo autoritativa.
11. Quitar el límite exclusivo de cien intereses del validador de lectura: debe aceptar lo que el servicio puede guardar, conservando los intereses anteriores. Se mantienen validación de cada texto, empresa y páginas de veinte fichas; no se aplica truncamiento comercial silencioso.
12. Actualizar el inventario pgTAP explícito completo, incluyendo diez tablas previas de agentes/editor, contactos y cuatro nuevas de prospectos. Lectura administrativa exclusiva se declara para perfiles de empresa y borradores; no se excluyen relaciones del catálogo para conseguir un resultado verde. La deuda previa de inventario no constituye una fuga RLS demostrada.
