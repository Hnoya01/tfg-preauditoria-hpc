# N1/N2: transporte del ensayo local y motivos administrativos

28/10/2026. Trabajo local sobre `e3e114b75b67f3872a2780fd039c3d5230b70c90`,
rama `feat/new-batch-review`. No hay un commit nuevo para este incremento: debe
identificarse por base más diff. Sin staging, commits, push, cambios de PR, fusión
o despliegue. La denegación previa de publicación no se reintenta por otra vía.
No se invocaron Astra ni otros revisores; sólo datos ficticios y temporales.

## Evidencia recibida, separada de la ejecución actual

La revisión externa comunicó para e3e114b: 246 Python descubiertas, 243 aprobadas,
un fallo N1 y dos omisiones Windows; 41 JavaScript aprobadas. Informó mecanismos
R1–R7 corregidos y no demostró regresiones H1–H3; su recuperación HTTP local
independiente conservó dos cierres, historial, hashes y revocación.

El usuario informó en Windows para ese mismo SHA: 246 Python y 41 JavaScript
aprobadas, pip check correcto y 21 versiones exactas; P01 con 40 conexiones
cerradas y cero managers vivos. Son resultados de la base, no del diff actual.
No identifican quién retenía el archivo en el antiguo WinError 32.

## N1: proxy heredado en recuperación

Reproducción propia antes de corregir: el ensayo sin variables proxy aprobó;
con variables SOCKS heredadas falló en `tests/restored_probe.py` al construir
HTTPX, por ausencia del extra opcional socksio. El proxy del fixture sólo apunta
a un socket centinela en 127.0.0.1, sin credenciales ni conexiones externas.
El fallo original queda en `.test-results/n1-before.log`.

La corrección se limita a `trust_env=False` en los dos `httpx.Client` del probe:
propietario y viewer. No cambia el proxy global, dependencias, transporte de la
aplicación ni aserciones. El destino del ensayo sigue siendo la API efímera
loopback; se conservan cuarentena, activación interrumpida/repetida, revocación,
login ficticio, viewer denegado, código extraído propio y ambos hashes de cierre.

`tests/test_restored_transport.py` repite el recorrido integral desde SU aplicación
restaurada con y sin las ocho variables proxy habituales (mayúsculas/minúsculas).
Un audit hook de red del subprocess de regresión rechaza bind/connect fuera de
loopback y resolución de nombres externa. El socket centinela exige cero usos del
proxy. Las variables sólo cambian dentro del fixture y se restauran al terminar;
no se instala socksio ni se amplía el hook de archivos del runner.

## N2: explicación sin alterar el motivo conservado

`web/closure.js` muestra descripción administrativa y `Código: …` en encabezados
y miembros del alcance, tanto activos como congelados. Las etiquetas existentes
de Planilla conservan su significado y el prefijo FICTICIO donde corresponde;
se añaden las de cierre/actualización/ámbito y alias históricos conocidos.
Ausencia de evidencia o de etiqueta no se presenta como rechazo ni aprobación.

Un código desconocido muestra «Motivo sin etiqueta administrativa en esta versión»
y su valor original literal; uno ausente se identifica como no informado. Se
comprueban propiedades propias para no interpretar constructor/__proto__ como
etiquetas. Todo se renderiza con textContent: el código con apariencia de HTML
sigue siendo texto. No se modifica el JSON del API, fundamentos, reglas, hashes,
permisos ni ZIP congelados. Las cadenas actuales describen el motivo histórico;
no recalculan sus resultados.

Dos regresiones JavaScript cubren las etiquetas conocidas de Planilla, significados
administrativos seleccionados, códigos históricos/desconocidos y renderizado seguro.
Se mantiene la comprobación exacta de fila/control/resultado y se actualiza sólo la
expectativa de la celda de motivo para incluir su explicación y código trazable.
Los dos fallos nuevos previos al arreglo quedan en `n2-before.log`.

## Verificación local

Python: **248 descubiertas = 246 de la base + 2 regresiones N1; 246 aprobadas,
cero fallos/errores y dos omisiones Windows AES-GCM/ACL**, sin fallos esperados ni
éxitos inesperados. Las omisiones no validan esas capacidades en Linux. JavaScript:
**43 aprobadas = 41 anteriores + 2 N2**, cero fallos/omisiones; pip check correcto.
Las dos focales N1 y las nueve de cierre JavaScript aprobaron. Python 3.12.14,
SQLite 3.53.1, Node 24.19.0 y Git 2.52.0; 21 versiones declaradas verificadas.

Chromium real en 127.0.0.1:18768: fila 2/RN20 y RN21 identificables, descripción
administrativa y código original visibles en la tabla, ocho fundamentos y confirmación
expresa, limitaciones congeladas visibles, dos descargas anteriores idénticas y
antecedentes de dos revisiones conservados. Sin errores de página. La captura
`n1n2-browser-frozen-scope.png` muestra las etiquetas sin truncarlas; no es aceptación
por personas. Servidor, cuentas/base y descargas temporales retirados.

Se reutiliza `.tmp/validation-venv`, dedicado y sin paquetes del sistema. No se
instalaron dependencias ni se cambiaron locks. Comandos de verificación completos:

```sh
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

Los comandos focales unittest son diagnóstico y no sustituyen el runner protegido.
Se preservan los fallos previos aunque las repeticiones posteriores aprueben.
La intermitencia histórica de interrupción de procesos sigue separada de N1 y del
antiguo WinError 32; no se cambian sus tiempos, leases ni aserciones.

Evidencia local excluida de Git: `n1-before.log`, `n1-focused.log`,
`n1-restored-with{,out}-proxy.json`, `n2-before.log`, `n2-focused.log`,
`n1n2-browser*.{json,png,log}`, `n1n2-python-summary.json`, `n1n2-python-final.log`,
`n1n2-node.log`, `n1n2-pip-check.log`, `n1n2-inventory.json`, `n1n2-summary.json`
y `n1n2-changes.patch` en `.test-results/`. Los temporales de datos/servidores y
descargas se retiran; no se publican fuentes, bases, usuarios ni credenciales.

Inventario local: **142 entradas, 141 hashes/tamaños comprobados**, manifiesto propio
sin autohash y sin archivos adicionales. Se permiten sólo los ocho archivos del diff;
los archivos restantes deben coincidir byte por byte con sus blobs de e3e114b.
La preparación original, SOURCE_HASHES.json, PREPARACION.md y locks permanecen
intactos. El inventario describe esta copia modificada, no un nuevo commit ni un
paquete limpio atribuido a e3e114b. El índice Git no se modifica.

Windows de este diff y aceptación de interfaz con personas pendientes. La prueba
de navegador no equivale a aceptación de usabilidad, y la recuperación de misma
máquina/runtime no equivale a desastre. Para comprobar la modificación se necesita
esta copia/diff: clonar sólo e3e114b ejecutaría la versión anterior. Cualquier
publicación futura requiere nueva autorización explícita; no se inicia otro bloque.
