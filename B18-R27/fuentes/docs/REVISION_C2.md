# Paquete de revisión C2 — revisión independiente pendiente

Implementación autorizada de RF16/RN30. El usuario excluyó Astra y otros revisores
independientes durante este bloque; la revisión queda a su cargo. No se invocaron.
Esta entrega no aprueba el TP completo ni inicia otros incrementos.

## Versión y alcance

Base C1: 1fe27aad4a364a56f3f45e88667310df08f01310, PR #3.
Rama C2: feat/new-batch-review; PR en borrador contra feat/revision-close.
Código/tests final: f7e45842272a7cd8844951be6a04b7f2beb178df. El informe final identifica el SHA completo del
paquete con documentación e inventario y el enlace verificado de la PR.
Main, MIME, PR #2 y la rama de C1 se conservan intactas. Sin fusión ni despliegue.

RF16/RN30 y MD02/MD05: nueva revisión explícita de un lote cerrado, vinculada a la
anterior, compartiendo el mismo Excel/importación/filas. Selección operativa de una
revisión por lote (abierta o última); no hay otra facturación ni doble cobertura.
MD06/MD07/MD12: decisiones anteriores históricas, procedencia inmutable, análisis
explícito y captura previa, control de permisos/versiones y apertura atómica.

## Decisiones técnicas y archivos para revisar

- app/revisions.py: GET de historial y POST de apertura con motivo, responsable,
  predecesora y versiones. Sólo una sucesora de una revisión cerrada con captura C1;
  referencia/hash del cierre, fuentes y decisiones/propuestas previas identificadas.
  Inserción de revisión, procedencia, versión de conjunto y auditoría en una transacción.
- app/revision_scope.py y app/db.py: migración 21. `invoice_imports` conserva su
  referencia original; `current_invoice_imports` selecciona una revisión por lote.
  Las filas originales no se copian. `revision_work_fields` conserva los valores por
  revisión; `work_fields` es una vista de la representación operativa actual.
- Historias de selección JSON, vínculos, declaraciones y prestador: propiedad de
  revisión en `revision_input_owners`, vistas actuales y triggers de procedencia e
  inmutabilidad. La migración vincula los registros existentes a la única revisión
  original de cada importación. Ordinales físicos siguen siendo únicos entre revisiones;
  `previous_id` encadena versiones dentro de la revisión. No equivale a reutilización.
- Consumidores de controles, autorizaciones, valores, propuestas y exportación consultan
  esas vistas de forma explícita. El helper conserva acceso al esquema anterior sólo
  para fixtures de migración; el arranque normal exige actualización offline.
- app/controls.py, app/review.py y app/values_v1.py: captura fija revisiones comparadas,
  invalida sólo revisiones abiertas y conserva vigencia de resultados cerrados según
  el manifiesto de cierre. Las listas operativas no presentan análisis anteriores como
  el análisis nuevo. Una alerta de otra revisión devuelve 409 y remite a su cierre.
- app/provisional.py y app/closure.py: procedencia de apertura en el manifiesto nuevo;
  descarga por ID de revisión, o último cierre por ordinal si se omite el parámetro.
  El archivo anterior se lee y verifica sin recalcular. Dos cierres son direccionables.
- web/revisions.js, web/app.js e index.html: historial, descarga concreta, motivo y
  confirmación expresa; versiones/predecesora del contexto consultado, respuestas
  tardías descartadas, acceso revocado sin evidencia y sin reintento automático.
  Refresco posterior retira datos de trabajo previos. Las capturas cerradas se rotulan
  como históricas y advierten que no validan la revisión actual.

La nueva revisión parte de las filas originales: no hereda correcciones, selecciones de
capturas, vínculos, declaraciones temporales/unidades, alcance de prestador, decisiones,
propuestas ni fundamentos como vigentes. Las fuentes registradas siguen disponibles y se
conservan todas las historias. El formulario advierte esta política antes de confirmar.
Todos los controles de la nueva revisión requieren evaluación explícita; el registro de
apertura identifica los códigos afectados y los IDs históricos. La reutilización asistida
entre revisiones no se implementa; no se fabrica equivalencia ni una nueva decisión humana.
Los controles independientes dentro de una revisión conservan el comportamiento RN28 previo.

## Evidencia ejecutada en Linux

Python 3.12.14; SQLite 3.53.1; Node v24.19.0. Se reutilizó `.tmp/validation-venv`, aislado,
sin system-site-packages. Las 21 dependencias declaradas coinciden con requirements-lock.txt.
En C2 no se instalaron ni descargaron paquetes: no se acredita aquí otra instalación limpia.
Sin dependencias nuevas ni cambios a requirements/locks. `pip check`: sin incompatibilidades;
la advertencia local de caché no escribible no es una instalación ni un error de dependencias.

```sh
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

- Python: 224 descubiertas (214 previas + 9 C2 + 1 diagnóstico de procesos), 222 aprobadas, 0 fallos, 0 errores,
  2 omisiones Windows, sin fallos esperados ni éxitos inesperados.
- JavaScript: 39 aprobadas (34 previas + 5 C2), cero fallos/omisiones.
- Migración ficticia v20→21: respaldo SQLite/objetos, SQL fallido con rollback, valores
  anteriores preservados, integrity_check y foreign_key_check correctos. Respaldo sigue
  en v20. Se mantuvo la regresión anterior v8→actual, con orden lógico para la nueva vista
  work_fields; se conserva el orden rowid y todas las comparaciones de las otras tablas.
  La regresión de v19 sigue apuntando específicamente a SQL de migración 20 y al destino actual.
- API: apertura sin ejecución ni decisiones heredadas; motivo/versiones/predecesora;
  duplicado y solicitud obsoleta rechazados; permisos, CSRF, otro conjunto y sesión revocada;
  fallo de auditoría sin revisión parcial; dos cierres y una tercera apertura; filas e historia
  sin duplicar; corrección y prestador anteriores intactos pero sin selección vigente nueva;
  fuentes posteriores disponibles sin cambiar el cierre; JSON/vínculos/declaraciones
  reconfirmados y una única cantidad facturada en el conjunto comparado.
- Chromium real, sólo 127.0.0.1:18767: ingreso, historial, descarga, motivo y confirmación,
  segunda revisión sin ejecución automática, análisis solicitado, dos filas/dos alertas
  pendientes y nueva descarga anterior idéntica. Captura de análisis anterior identificada
  como histórica. Sin errores de página. Servidor, usuarios, base y descargas temporales
  retirados. Las capturas son datos ficticios, no aceptación de usabilidad del usuario.

La primera suite completa detectó una comparación de orden inconsistente introducida al
adaptar el fixture a una vista (rowid frente a clave lógica). Se corrigió únicamente esa
ordenación; no hubo pérdida de filas ni se cambió una expectativa funcional. Se repitió la
suite completa. Un primer ensayo del navegador esperaba un cambio de estado que el contrato
existente no realiza al analizar; se corrigió el guion y luego se comprobó la captura y las
filas reales, sin modificar estados ni expectativas de negocio para lograr un resultado.

Evidencia local ignorada por Git: `.test-results/c2-python-summary.json`,
`c2-python-details.log`, `c2-node.log`, `c2-pip-check.log`, `c2-environment.json`,
`c2-browser.json`, capturas `c2-before-opening.png`, `c2-new-review.png` y
`c2-explicit-analysis.png`. El resumen conjunto y la verificación del inventario están en
`c2-summary.json` y `c2-inventory.json`. El informe final identifica el SHA comprobado.
No se publican bases, usuarios, sesiones, ZIP, logs privados ni entornos.

En otra pasada completa se observó un fallo intermitente en
`test_real_process_interruption_during_preparation`: el proceso no alcanzó la señal
esperada dentro de diez segundos. Dos ejecuciones diagnósticas consecutivas del mismo
test, sin cambios, aprobaron. Se repitió después el runner completo en serie. La causa
no quedó determinada; no se cambiaron leases, tiempos, aserciones ni controles y se
conservó el fallo previo en `c2-python-process-failure-summary.json`/log. El diagnóstico
individual con unittest no sustituye al runner aislado final.

## Investigación ampliada del ensayo de interrupción

El traceback original sólo registró `ready.wait(10)==False`. No conservó el estado
final del hijo, y la base ficticia fue retirada por el teardown. Ese registro no permite
distinguir hijo detenido, salida técnica temprana, contención o demora del entorno.
La causa de aquella ejecución sigue sin atribución; no se considera resuelta por repetir.

Se compararon C1 exacto 1fe27aad4a364a56f3f45e88667310df08f01310, exportado a una
carpeta temporal sin modificar su rama, y C2 a587c2790e07dbf9a572da8f6922661f30b91d4b.
Mismo intérprete/lock y bases ficticias nuevas por ensayo. `tests/processing_worker.py`,
la sincronización original y los guardas/heartbeat de `app/processing.py` eran iguales;
C2 sólo cambió la consulta de entradas a la vista de revisión actual en ese módulo.

Sonda temporal instrumentada, conservando las aserciones originales de crash:

| Condición | C1 | C2 | Interpretación |
| --- | --- | --- | --- |
| Diez ejecuciones sin demora inducida | 10/10 pasan; 0,028779–0,050371 s | 10/10 pasan; 0,027221–0,061029 s | Tiempo desde entrada al helper hijo hasta evaluar; muestra pequeña, no prueba de capacidad ni exclusión de regresión |
| Demora inducida de 0,75 s tras claim y antes de execute | Falla la señal de etapa | Falla la señal de etapa | La vigencia original de 0,6 s vence antes del primer guarda/heartbeat |
| Estado tras esa demora | interrupted/activity_lost; AttemptInterrupted; validating; 0 filas preparadas; 0 análisis publicados | Igual | Rechazo seguro; la reproducción inducida no prueba que eso causara el fallo original |

La demora se introdujo sólo en la sonda temporal de diagnóstico, no en los tests ni en
producción. El padre conservó su espera de diez segundos. Esto demuestra una fragilidad
preexistente de esa sincronización: la misma señal ausente puede ocultar una salida
correcta por vencimiento previo. No permite atribuir el fallo original a C2 ni afirmar
que el entorno Linux sea su causa. Los valores operativos siguen siendo 15 s para ejecución y 90 s para publicación; el
fixture sigue usando 0,6 s. No se cambiaron duraciones, leases, renovaciones,
guardas, expectativas ni código de procesamiento para obtener un pase.

Corrección acotada del diagnóstico de pruebas: `worker_stage_diagnostic` en
`tests/processing_worker.py` conserva estado, etapa, error técnico, filas preparadas,
vida/código de salida del hijo cuando falta la señal. Selección explícita sin sesiones,
credenciales ni datos de facturación. `crash` sigue exigiendo la misma etapa dentro de
los mismos diez segundos, ambas consultas durante trabajo, ausencia de publicación,
interrupción real y rollback/reintento posteriores. El detalle no convierte fallos en pases.

Nueva regresión en `tests/test_processing.py`: proceso independiente con barreras de
claim/ejecución; el padre vence la vigencia ficticia antes de liberar el primer guarda.
Se comprueban salida técnica temprana, ausencia de evaluación/resultados y diagnóstico
`interrupted/activity_lost`, incluso con código de salida de proceso cero. No depende de
una pausa probabilística. Las trece pruebas dirigidas de procesamiento aprobaron; después el runner aislado
completo descubrió 224 pruebas y aprobó 222 con las dos omisiones Windows. Node volvió a
aprobar 39 y pip check fue correcto. App y web permanecen idénticos al paquete anterior
a587c2790e07dbf9a572da8f6922661f30b91d4b; no se repitió Chromium en esta ampliación de tests.

Evidencia local: `c2-process-investigation.json`, `c1-process-unforced.json`,
`c2-process-unforced-final.json`, `c1-process-forced-preheartbeat.json`,
`c2-process-forced-preheartbeat.json` y `c2-process-targeted-final.log` en .test-results/.
El fallo original sigue conservado; su traceback genérico no se reemplazó por el de la
reproducción inducida. Los ensayos instrumentados fuera del runner son diagnóstico y no
sustituyen a la suite aislada final. No hay corrección funcional de producción justificada
con la evidencia disponible. Si reaparece, el nuevo traceback distinguirá salida temprana
de hijo aún vivo; conservarlo antes de plantear un cambio en vigencias o sincronización.

## Pendientes y riesgos

- Vigilar el ensayo de interrupción: se demostró fragilidad previa ante vencimiento antes
  del heartbeat, pero la causa de la ejecución original sigue sin atribución. Los pases
  posteriores y la reproducción inducida no acreditan que ese fallo haya desaparecido.
- Windows no ejecutado para esta versión. AES-GCM/.NET y ACL NTFS omitidas en Linux no
  validan capacidades equivalentes de Linux. Seguir VERIFICACION_WINDOWS.md con el SHA final.
- Revisión independiente Astra y aceptación de interfaz: a cargo del usuario, pendientes.
- Una nueva revisión exige reconfirmar los datos de trabajo. No hay migración operativa
  ejecutada ni reutilización asistida entre revisiones. Verificar ese recorrido en la
  revisión humana; cambiar su política requeriría otro encargo, no una suposición silenciosa.
- Las fuentes/documentos siguen siendo recursos versionados del conjunto; registrarlos
  no modifica el ZIP anterior ni inicia controles. C2 no valida fuentes reales, aplicabilidad
  económica, reglas documentales pendientes, despliegue o seguridad de producción.
- INVENTARIO.json describe el paquete vigente; SOURCE_HASHES.json, docs/PREPARACION.md y
  los locks históricos permanecen byte a byte. El inventario se enumera sin hash propio.
