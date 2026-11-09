# Correcciones R1–R7 para revisión del usuario

Fecha: 27/10/2026. Base auditada: `76f18c37d9601641c555c6f10dae64b0360c8ad2`.
Código y pruebas: `8102eaa6aba903725038ed6a0e9250ae62ee45ce`.
Rama: `feat/new-batch-review`. PR #4 en borrador, contra `feat/revision-close`
(`1fe27aad4a364a56f3f45e88667310df08f01310`). El informe de entrega identifica el
SHA final; comprobar ese SHA y no sustituirlo por la punta futura de la rama.
Comparación del bloque: base auditada → SHA de entrega. Para C1+C2 acumulados:
`0d244d28cb56529da53dbf39b3969b291201e94b` → SHA de entrega; antecedentes en
[C1](REVISION_C1.md) y [C2](REVISION_C2.md).

Sólo datos ficticios. No se modifican reglas de negocio, ramas base ni fuentes
históricas de preparación. Sin fusión, despliegue ni revisión independiente invocada.
El usuario hará la revisión final; este documento no acredita aprobación de Astra.

## Matriz de correcciones y evidencia

| Hallazgo | Antes / reproducción | Cambio | Regresión verificable |
| --- | --- | --- | --- |
| R1 P1, fundamentos | Cada miembro repetía el motor de autorización completo; un cambio RN11 ajeno cambiaba RN10 | `closure-input-v2`: dependencias de fila/regla/cohorte y campos pertinentes; captura compartida por hash, fuera de los miembros | Tamaño N/2N/4N; RN11 ajena conserva fundamento RN10; incorporación pertinente lo invalida; alcance API/BD/ZIP idéntico |
| R2 P1, publicación/respaldo | Un rollback después de publicar dejaba bytes fuera de `stored_files`; la igualdad física impedía respaldar | Exclusión entre procesos para publicar y tomar snapshot; transacción SQLite + inventario separado de extras preservados | Fallo postpublicación sin cierre parcial; conciliación repetible; dos cierres y backup concurrente; conflicto/reintento; faltante/alteración registrados siguen rechazados |
| R3 P2, recuperación | Fixture declaraba esquema 18 sin comprobar código real; no arrancaba la aplicación extraída | Release con commit/árbol/esquema reales e inventario comprobado; backup exige compatibilidad; arranque de SU aplicación restaurada | Dos cierres, sucesora, decisiones, fundamentos y documento ficticio; proceso aislado `-I`, API loopback, cuarentena, activación interrumpida/repetida, sesión revocada, login nuevo, hashes intactos; esquema incompatible rechazado |
| R4 P2, alcance UI | Preview omitía miembros; el estado cerrado ocultaba fundamentos | Consultas autenticadas de miembros paginados y resumen congelado; Salida conserva limitaciones, cobertura, decisiones y propuestas | Se localizan fila 2/RN20 y fila 2/RN21 en UI y ZIP; cierre recargado muestra su captura, no fuentes actuales; confirmación expresa y lectura protegida |
| R5 P2, antecedentes | Decisiones/correcciones sin revisión de origen visible | API y UI muestran ordinal, estado, vínculo al cierre y carácter histórico; origen desconocido se declara | Revisiones 1 y 2 con Confirmada/Descartada y correcciones propias; historia no acredita vigencia ni se hereda; ZIP anterior idéntico |
| R6 P2, entrega | Descargar no tenía evento propio | `closed_export_response_prepared` con actor, revisión, cierre y hashes, después de verificar bytes y revalidar acceso | Dos descargas generan dos eventos; permiso denegado, cierre inexistente y fallo de preparación no generan éxito; ZIP inmutable |
| R7 P2, lecturas | Sondas directas sobre las tres funciones auditadas devolvieron datos después de revocar sesión; no se afirma reproducción HTTP previa | `list_alerts`, `run_summary`, `list_runs`: snapshot único y revalidación final de permiso/versiones/revisiones | Barreras deterministas de cambio y revocación; segundo revisor escribe durante lectura y provoca 409, seguida de lectura coherente; no se reabre H1 de detalles |

Pruebas: [test_audit_fixes.py](../tests/test_audit_fixes.py), 15 casos nuevos;
[restored_probe.py](../tests/restored_probe.py), auxiliar del proceso restaurado.
Las dos regresiones JavaScript nuevas están en `web_closure.test.cjs` y
`web_workbench.test.cjs`. Las aserciones anteriores de seguridad siguen vigentes.

## Capturas, formato e historia

La migración **22 es aditiva**: `closure_input_captures` y `limitation_formats`,
con claves foráneas y triggers de inmutabilidad. No reescribe fundamentos, capturas
o ZIP anteriores. Cada fundamento nuevo referencia una captura compartida; cada
miembro guarda sólo las dependencias pertinentes. El ZIP nuevo incluye una sola
entrada por captura referenciada en `closure_input_captures.jsonl`.

Los fundamentos de una revisión abierta anterior al formato v2 quedan históricos
y requieren reconfirmación explícita. Se conserva el texto para revisarlo y se
encadena una versión nueva; nunca se convierten silenciosamente en vigentes.
Una revisión ya cerrada continúa descargando su ZIP original y muestra `legacy-v1`
si corresponde. Se comprobó con código real del commit auditado: creó bases y un
cierre de esquema 21 en otro proceso, luego se migraron copias ficticias a 22.
El respaldo anterior, los registros y el hash del ZIP se conservaron; rollback,
`integrity_check` y `foreign_key_check` también se comprobaron.

Sonda de serialización de miembros, bytes JSON (no latencia ni capacidad máxima):

| Filas ficticias | Base auditada | Corregido |
| ---: | ---: | ---: |
| 16 | 712592 | 174832 |
| 32 | 2512784 | 349776 |
| 64 | 9375632 | 699664 |

La regresión agrega además los bytes persistidos y la captura compartida, con
crecimiento próximo a 2 al duplicar filas. La captura completa sigue pudiendo ser
grande: no se acredita memoria o tiempo de cierre para el máximo volumen admitido.

## Extras, concurrencia y recuperación

La cuarentena de objetos extra es **lógica**: el manifiesto los identifica como
`unregistered_at_snapshot_may_await_commit`, con ruta, hash y tamaño. Se conservan
en su ruta privada y se copian/restauran; no se registran como originales ni se
exponen por las rutas de dominio. Pueden pertenecer a un productor pendiente de
commit; moverlos o borrarlos automáticamente sería inseguro. La eliminación
definitiva queda fuera del bloque. Repetir la conciliación no altera bytes/BD.
Un original registrado ausente o alterado continúa bloqueando el respaldo.

El publicador sostiene `.objects.lock` sólo durante la publicación física. El
backup adquiere primero `BEGIN IMMEDIATE` y después ese mismo cerrojo entre procesos;
mantiene ambos mientras compara/copia. Un productor puede publicar antes del backup
y registrar después: su objeto queda extra en ese snapshot, sin pérdida. La espera
es acotada y devuelve ocupación/reintento; no se reintenta una escritura obsoleta.
Se comprobó también exclusión nativa entre procesos y liberación al terminar uno.
La rama Windows de ese cerrojo todavía requiere ejecución del usuario.

`scripts.release_snapshot.build_release` genera `SOURCE_MANIFEST.json` versión 2:
commit, estado limpio/sintético, hashes del árbol y esquema leído de `app/db.py`.
Con árbol limpio o commit explícito lee objetos Git inmutables. `source_archive`
verifica además hashes/tamaños/lista exacta de `INVENTARIO.json` en una release
limpia, respetando su hash propio nulo. Código sucio sólo se permite con indicación
explícita sintética y no se presenta como bytes del commit base. Un backup nuevo
exige release v2 y mismo esquema que su base. Archivos legacy con código/esquema
comprobables mantienen procedencia desconocida, sin fabricar un commit histórico;
el viejo paquete ficticio de sólo README no acredita compatibilidad.

Desde una copia Git limpia, con `.tmp` creada, ejemplo de paquete de código para
ensayo sintético (el destino debe ser nuevo; no hace backup ni migra datos):

```sh
.venv/bin/python -B -c "from pathlib import Path; from scripts.release_snapshot import build_release; print(build_release(Path.cwd(), Path('.tmp/application-review.zip'))['provenance'])"
```

La regresión integral inyecta rollback después de publicar, conserva/clasifica el
extra, confirma el primer cierre, abre y analiza explícitamente la sucesora, guarda
decisiones/fundamentos nuevos, confirma el segundo, respalda y restaura. Arranca en
proceso aislado desde `restored/application`; verifica que todos los módulos `app`
y `scripts` cargados pertenecen a ese árbol. El arranque antes de activar se rechaza
sin modificar la base; una interrupción del comprobante puede retomarse; sesiones
viejas se revocan, acceso nuevo ficticio funciona y ambos ZIP conservan sus hashes.
No prueba recuperación ante desastre: usa la misma máquina, runtime y dependencias
instaladas, no un equipo vacío ni pérdida física del volumen.

El evento de R6 acredita **bytes verificados preparados por el servidor para una
respuesta**. No acredita transmisión completa ni recepción del navegador. No se
reescribe el ZIP para auditar una descarga ni se registran tokens/contraseñas.

## Ejecución y resultados

Python: **239 descubiertas = 224 anteriores + 15 nuevas; 237 aprobadas, cero fallos,
cero errores, dos omisiones Windows** (AES-GCM/.NET y ACL/NTFS), sin fallos esperados
ni éxitos inesperados. Las omisiones no validan equivalentes Linux. JavaScript:
**41 aprobadas = 39 anteriores + 2 nuevas**, sin fallos/omisiones. `pip check` correcto.
La suite se verifica también sobre el paquete limpio guardado, para que el ensayo
restaurado lea el archivo Git del commit exacto y compruebe su inventario vigente.

Se reutilizó el venv aislado `.tmp/validation-venv`, sin paquetes del sistema.
Python 3.12.14, SQLite 3.53.1, Node 24.19.0. No se instalaron ni descargaron
dependencias en este bloque; 21 versiones declaradas, locks intactos. No se atribuye
a esta jornada una instalación limpia nueva. Comandos de verificación:

```sh
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

Chromium real en loopback `127.0.0.1:18768`: ocho fundamentos, confirmación expresa,
segundo cierre, alcances exactos visibles antes/después, dos descargas del primer
cierre idénticas y antecedentes contradictorios por revisión. Sin errores de página.
Servidor, base/cuentas ficticias y descargas temporales retirados al terminar.
Las capturas no equivalen a aceptación de usabilidad.

Se observaron dos fallos del guion de navegador: seleccionaba el último grupo en
vez del documental y leía el detalle antes de finalizar su consulta. Se corrigió
la selección/espera del guion, sin cambiar expectativas funcionales. El primer caso
R7 del segundo revisor dio 401 porque el fixture emitía la sesión antes de conceder
acceso, operación que revoca sesiones por diseño. Se emitió después del permiso;
se mantuvo la aserción 409 y la producción no relajó autenticación.

Evidencia local excluida de Git: `audit-r1-before.json`, `audit-r1-after.json`,
`audit-r7-before.json`, `audit-restored-application.json`, `audit-browser.json`,
capturas `audit-browser-{active-scope,frozen-scope,history}.png`,
`audit-r7-fixture-initial.log`, `audit-browser-history-initial.log`,
`audit-python-final.log`, `audit-python-summary.json`, `audit-node.log`,
`audit-pip-check.log`, `audit-inventory.json` y `audit-summary.json` en `.test-results/`.
Inventario final: 136 entradas, 135 hashes/tamaños comprobados y autohash excluido;
sin faltantes ni archivos adicionales. SOURCE_HASHES.json, PREPARACION.md y locks
conservados byte por byte respecto de main. No se publican bases, fuentes, ZIP de
datos, sesiones ni entornos virtuales.

El fallo intermitente histórico del ensayo de interrupción de procesos no recibió
causa retrospectiva demostrada. Sus logs C2 se conservaron; las aprobaciones nuevas
no demuestran que nunca pueda repetirse. No se aumentaron tiempos ni se relajaron
aserciones para este bloque.

## Dictámenes y pendientes

- **Demo:** recorrido ficticio comprobado, con limitaciones y antecedentes visibles.
  Aceptación de comodidad/usabilidad pendiente del usuario; no aprobación económica.
- **Integración:** cambios preparados para revisión en la PR #4 en borrador.
  Revisión independiente del usuario y ejecución Windows del SHA nuevo pendientes;
  no se fusiona ni se activa auto-merge. El usuario informó 224 Python + 39 JS sin
  omisiones en Windows para el SHA auditado 76f18c3; no valida estas correcciones.
- **Recuperación:** ensayo sintético de misma máquina comprobado desde su código
  restaurado, con activación y hashes. Cifrado/ACL Windows, volumen persistente,
  equipo vacío y desastre físico no quedan validados por Linux.

Guía exacta: [VERIFICACION_WINDOWS.md](VERIFICACION_WINDOWS.md). No iniciar otro
incremento por continuidad implícita. Este bloque no declara completo ni apto para
producción al TP.
