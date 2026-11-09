# Portabilidad del paquete y cierre de recursos P01

Bloque autorizado del 27/10/2026, sobre `89571d9d53872c9ae3f5ff870f96f6131665ff08`,
en `feat/new-batch-review`, PR #4 en borrador contra `feat/revision-close`
(`1fe27aad4a364a56f3f45e88667310df08f01310`). El informe final identifica el SHA
completo para repetir la comprobación; no sustituirlo por una punta futura de rama.
Antecedentes y matriz funcional: [R1–R7](REVISION_R1_R7.md), [C2](REVISION_C2.md).
Sin cambios de negocio, esquema, dependencias, Git global ni fuentes históricas.
No se invocaron Astra/revisores; no se fusiona ni despliega.

## Resultado Windows recibido y alcance de la evidencia

El usuario ejecutó el SHA 89571d9: 239 Python, 226 aprobadas, 13 errores, cero
omisiones; 41 JavaScript aprobadas, pip check correcto, 21 versiones exactas y Git
limpio. Python 3.12.10, SQLite 3.49.1 y Git 2.50.1 Windows. **Ese SHA no aprobó Windows.**

Doce errores convergen en `source_archive`, al comparar bytes con el inventario:
once durante la preparación de un respaldo y uno al inspeccionar la release
histórica de esquema 21. Afectan AuditWorkflowTests (4), RecoveryTests (3) y
RecoveryStartupTests (5). No son doce restauraciones que fallaron independientemente:
esas ramas no superaron la preparación/validación del paquete. Los logs no contienen
hashes discordantes ni diagnóstico CRLF; esa atribución inicial fue del usuario.

El otro error es `WinError 32` en `P01Tests.test_cookie_csrf_origin_lockout_and_idle_expiry`,
al eliminar `app.sqlite3` durante `tearDown`. La traza no identifica el retenedor
y no incluye ResourceWarning. No se atribuye a antivirus, SQLite, diferencias de
versiones ni al ensayo histórico de interrupción de procesos.

## Causa reproducida y corrección de empaquetado

`git archive` sí lee el commit, pero aplica conversiones de checkout. La suposición
anterior de que garantizaba bytes originales era incorrecta. Reproducción en un
repositorio ficticio, con el mismo commit y checkout limpio, cambiando sólo
`core.autocrlf` local a ese fixture:

| Configuración | SHA-256 del blob LF | SHA-256 exportado por git archive |
| --- | --- | --- |
| false | 2824aaa45a3ae4cc8f4f4e716479739ff5a7314d3dda38dd298554891dfbce6a | 2824aaa45a3ae4cc8f4f4e716479739ff5a7314d3dda38dd298554891dfbce6a |
| true | 2824aaa45a3ae4cc8f4f4e716479739ff5a7314d3dda38dd298554891dfbce6a | ece6daa837726053ce2f6066f51e7198643ca4386a997378429d45f5ba85de8f |

El manifiesto generado sobre el archive podía concordar consigo mismo, mientras
el inventario seguía describiendo los blobs. El rechazo de ese inventario era
correcto; no se normaliza texto al verificar ni se adaptan hashes al checkout.

`scripts/release_snapshot.py` ahora enumera el árbol exacto mediante `ls-tree -rz`
y lee los blobs por OID con `cat-file --batch`, sin filtros/textconv ni conversiones.
Un commit explícito ya no depende de que sus archivos existan en el checkout actual.
Se siguen rechazando enlaces, gitlinks y rutas no admitidas. La rama de trabajo
sucia conserva su identificación explícita como sintética, sin atribuir sus bytes
al commit base. No se modifica el contrato v2, la comprobación de esquema ni la
validación estricta de `source_archive`.

Regresiones en `tests/test_release_portability.py`: LF/CRLF, binario y nombre con
espacios; hash/bytes de cada entrada idénticos a su blob y árbol igual en ambos
modos; inventario verificado; commit histórico sin archivo presente en checkout;
alteración, faltante y agregado rechazados incluso después de recalcular el
manifiesto externo; enlaces/gitlinks rechazados. Se prueban bytes de entradas y
árbol, no identidad binaria entre ZIP nuevos creados en distintos instantes.
Los ZIP de cierres históricos no se regeneran.

## Defectos de cierre demostrados y límite del WinError original

Se reprodujeron por inyección determinista dos defectos distintos:

- `db.connect`: si fallaba un PRAGMA posterior a abrir SQLite, el llamador nunca
  recibía una conexión que pudiera cerrar y faltaba el cierre explícito. Ahora
  cualquier fallo de inicialización cierra y propaga la excepción. La regresión
  usa una conexión SQLite real y comprueba que queda inutilizable por cierre.
- `ProcessingManager.close`: podía retornar después de `join(5)` con coordinador
  o trabajador aún vivo. Ahora comprueba ambos y comunica cierre incompleto;
  conserva las mismas esperas, solicita parada y no informa un cierre correcto.
  Las pruebas mantienen un hilo real en una barrera, inyectan una espera agotada
  sin sleeps y verifican error, liberación posterior y cierre repetible.

Estas reproducciones justifican las correcciones, **pero no demuestran que alguna
retuviera el archivo del Windows original**. No se reprodujo aquí ese WinError.

P01 mantiene los tres clientes/lifespans, procesamiento habilitado y todas las
aserciones de cookies, CSRF/origen, vencimiento inactivo/absoluto y bloqueo de login.
`tests/resource_support.py` instrumenta únicamente las conexiones Python de su base
ficticia: creación, propietario, cierre explícito y referencias débiles, sin retener
conexiones para alterar su vida. Registra estados de todos los managers antes de
cerrar clientes y antes de eliminar el temporal. Intenta cerrar todos los clientes,
propaga errores y exige cero conexiones sin cierre y cero hilos vivos antes de
limpiar. Si la limpieza falla, añade tipo/winerror/nombre de archivo y vuelve a lanzar.
No se tolera el error, no se reintenta con sleeps ni se desactivan trabajadores.
El JSON no registra SQL, contraseñas, cookies, datos ni rutas personales.

La ejecución dirigida Linux de autenticación observó 24 conexiones explícitamente
cerradas y los tres coordinadores terminados antes de la eliminación estricta.
No identifica handles de procesos externos ni todos los recursos nativos; si el
WinError reaparece, ese registro permitirá separar lo observado de lo todavía
desconocido. No se debe convertir una nueva pasada correcta en atribución retroactiva.

## Verificación y entrega

Código y pruebas: `d68faa7c377e83806a5ac212934af27e844688d1`.
Python: **246 descubiertas = 239 anteriores + 7 nuevas; 244 aprobadas, cero fallos,
cero errores y dos omisiones Windows AES-GCM/ACL**, sin fallos esperados ni éxitos
inesperados. JavaScript: **41 aprobadas**, sin fallos/omisiones; pip check correcto.
Las 16 focales de empaquetado/recursos/P01 aprobaron. Los dos casos de interrupción
aprobaron en serie y en la suite completa, manteniendo el fallo focal previo como
evidencia de intermitencia. Se comprueba también el paquete limpio del commit final
con su inventario, sin atribuir al SHA anterior los resultados nuevos.

Las siete regresiones nuevas son cuatro de empaquetado y tres de recursos. P01
gana comprobaciones de cierre sin cambiar su número de casos. Se reutiliza el venv
aislado, Python 3.12.14, SQLite 3.53.1, Node 24.19.0 y las 21 versiones del lock.
Sin instalación ni descarga nueva en este bloque. Comandos completos:

```sh
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

La primera focal amplia (29 casos) tuvo dos fallos en los ensayos de interrupción:
el hijo terminó normalmente con estado interrupted/activity_lost, etapa validating,
cero filas procesadas, antes de alcanzar las barreras preparation/publication. El
diagnóstico disponible es más preciso que el timeout histórico sin estado del hijo,
pero no prueba la causa temporal original ni relación con WinError 32. Se conserva
`portable-targeted.log`; no se cambiaron tiempos, leases ni aserciones de esos casos.
Los ajustes iniciales del nuevo fixture LF/CRLF sólo forzaron recrear el checkout y
actualizar su stat en el índice; no cambiaron expectativas ni hashes para aprobar.

Evidencia local excluida de Git en `.test-results/`: `portable-before*.log`,
`portable-focused.log`, `portable-targeted.log`, `portable-resources-final.log`,
`portable-processing-investigation.log`, `portable-eol.json`, `p01-resources.jsonl`,
`portable-python-summary.json`, `portable-python-final.log`, `portable-node.log`,
`portable-pip-check.log`, `portable-inventory.json`, `portable-clean-release.json`
y `portable-summary.json`. No se publican bases, usuarios, ZIP de datos ni entornos.

Inventario final: 140 entradas y 139 hashes/tamaños; manifiesto propio sin autohash.
La generación del inventario vigente usa los blobs preparados en el índice, no
bytes del checkout convertidos accidentalmente; se vuelve a comprobar frente al
commit final. Se conserva el autohash excluido y la evidencia de preparación original.
SOURCE_HASHES.json, PREPARACION.md, locks, ramas base y cierres históricos intactos.

Windows del SHA nuevo y revisión independiente del usuario pendientes. Guía y
reproducción dirigida: [VERIFICACION_WINDOWS.md](VERIFICACION_WINDOWS.md). Este
bloque no declara completo el TP, aptitud para producción ni recuperación ante
desastre; no inicia incrementos adicionales.
