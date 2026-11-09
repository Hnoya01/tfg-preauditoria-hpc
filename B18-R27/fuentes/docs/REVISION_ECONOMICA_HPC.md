# Referencia económica HPC por fila

Base: f903bad58c176312e3637fd1394d78d22addc8ec. Rama publicada feat/hpc-row-applicability.
Commit funcional probado: 4a0d685053e5f5d9593eec88c750f4a52f4798a7. La PR prevista es
en borrador sobre feat/new-batch-review; **no se creó**: el control automático rechazó
esa acción por falta de autorización específica, también tras comprobar que el
repositorio es privado y no existía una PR. No se usan otras vías ni nuevos reintentos.
Se solicita confirmación específica al usuario. El informe final identifica el último
SHA de documentación, con código funcional idéntico. Sin fusión ni despliegue.

## Requisito, alcance y evidencia

RF14/RN14/RN15: conectar una referencia suficiente a la prestación para comparar
fecha, código, unidad y cantidad, conservando fuente y versión; tolerancia $0,01.
RN12 conserva O/P/Q como importes de fila. RN27/MD10 siguen separando indicio,
decisión humana, respaldo económico y propuesta: este incremento no habilita su
confirmación/ajuste final ni escribe propuestas monetarias.

Se reutilizan el registro de PDF, versiones HPC, cotejos documentales, capturas de
análisis, decisiones, dependencia selectiva y cierre congelado. No se reemplazan
el motor monetario, la conciliación de autorizaciones ni la comparación exploratoria.
Esta última sigue identificada como exploratoria y no se convierte en aprobación.

La aplicabilidad identifica fila/revisión, fuente/corte/hash, arancel/versionado,
factor o respaldo documental del valor, fecha, cantidad completa, ARS por práctica,
convenio/página/fragmento, cobertura documental y fundamento individual del revisor.
El servidor verifica originales y coherencia; el contenido de la página y la aplicación
al caso son afirmaciones humanas trazables, no una interpretación automática del PDF.
No basta con enviar un precio o un booleano: el precio proviene de la fuente/versiones
registradas, con evidencia comprobada y permiso/versión validados en transacción.

Código completo conservado: sólo para valores se agrupan candidatos por los primeros
seis dígitos HPC. La fecha debe dejar exactamente un arancel; ambigüedad no se resuelve
eligiendo el más barato ni por coincidencia de nombre. Autorizaciones mantienen su
código completo y controles previos. La versión de valor se elige por fecha efectiva
y ordinal; una incompatible no hace reaparecer la anterior. Este corte admite sólo
la unidad versionada literal `por práctica`; otras unidades permanecen pendientes.

Para el original NBU se requiere cotejo vigente de factor coincidente o referencia
documental general respaldada. Una observación individual afectada/diferente prevalece
como bloqueo. El original no se extrapola más allá de BASE_2026-10-09. Una versión
posterior exige su propio respaldo; no se infiere una fecha final contractual por
faltar ese dato. La cobertura comprobada hasta una fecha no es vencimiento del convenio.

Se registra explícitamente una referencia específica aceptada identificada como
`unresolved`: no produce un cálculo general, ni se reemplaza silenciosamente. Para
dejar de considerarla debe documentarse su retiro o cambiar el caso pertinente.
No se exige demostrar que no existen acuerdos particulares. Su cálculo, adicionales,
normas especiales y redondeo de fracciones de centavo quedan fuera de este primer bloque;
sin evidencia suficiente los resultados son no concluyentes y el importe es desconocido.
Se conserva la diferencia con signo para revisión, sin transformarla en débito.

## Operación y capturas

En Planilla, Detalle → Referencia económica HPC consulta la fuente elegida en
Convenios/valores. Registrar la referencia general exige confirmación expresa,
PDF/página/fragmento, cantidad/unidad, fecha cubierta y fundamento. Identificar una
referencia específica la deja sin cuantificar. El retiro conserva su historia.
Guardar no importa, analiza, resuelve alertas ni genera una propuesta. El usuario
ejecuta Actualizar análisis explícitamente para producir RN14/RN15.

Ejemplo exclusivamente ficticio probado: arancel $15 por práctica × 2 = $30
comparables; total de fila $32 − $30 = diferencia $2. No se multiplica $32 por 2.
La diferencia absoluta de $0,01 está dentro de tolerancia; $0,02 queda para revisión.
RN15 suficiente no aprueba la factura ni confirma el indicio de RN14.

Las filas conservan contexto y estado técnico/resultados/decisiones separados. Una
referencia modificada o retirada afecta RN14/RN15 pertinentes, sin borrar sus cifras
históricas; lo ajeno conserva vigencia. Un nuevo valor que empieza después de la fecha
de práctica y un PDF ajeno no invalidan el resultado. Cambios de fuente, código,
cantidad, descripción, contexto/documentos pertinentes sí se conservan como dependencias.
No hay reanálisis automático ni recuperación silenciosa de versiones anteriores.

Los resultados preparados antes de un conflicto/revocación quedan históricos sin
publicación parcial. Las limitaciones usan dependencias por miembro y capturas
compartidas, sin repetir el motor global por fila. Los registros de aplicabilidad
son inmutables y pertenecen a una revisión; la sucesora empieza sin heredarlos.
Una consulta cerrada lee el registro histórico sin evaluar referencias actuales;
el cierre/ZIP guardado permanece idéntico después de registrar nuevos valores.

API privada GET/POST:
`/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/economic-applicability`.
GET exige permiso reviewer y `source_id`, ofrece hash de base y versiones.
POST exige sesión, origen/CSRF, ambas versiones y hash coincidente; se revalida dentro
de `BEGIN IMMEDIATE`. Un viewer, fuente ajena, revisión cerrada o guardado obsoleto se
rechaza sin escritura parcial. El historial económico no es el historial de propuestas.

## Migración y verificaciones

Esquema 23 aditivo: `row_economic_references`, FK de fila/fuente/revisión, unicidad,
triggers de revisión abierta e historia inmutable. No rellena referencias legacy ni
reescribe cierres. El arranque no migra automáticamente una base existente.
Sólo con servidor detenido y base ficticia en esta tarea:

```sh
.tmp/validation-venv/bin/python -B -m app.cli --data-dir .tmp/demo-data backup-and-upgrade
```

La regresión 22→23 prepara respaldo, inyecta SQL inválido, exige rollback íntegro y
posterior migración correcta, verifica integridad/FK y conserva copia previa en 22.

Pruebas focales: 17 Python y cinco anteriores de compatibilidad (22 aprobadas);
seis regresiones JS añadidas a web_values (siete aprobadas en ese archivo).
Cubren fórmula/tolerancia, código completo/prefijo, faltantes/ambigüedad/normas, unidad,
permisos/CSRF, dos escritores simultáneos, revocación/cambio mediante barreras,
invalidez selectiva, historia/cierre/sucesora y migración. Las JS cubren HTML/prototype
como texto literal, explicación, respuesta tardía, confirmación/versiones/conflicto y cierre.
Navegador Chromium real, API temporal 127.0.0.1:18769: un análisis antes y después del
guardado (no se inició otro), dos después de la acción explícita; $30 comparables,
$32 de fila y diferencia $2. Retirar afectó esa fila y mantuvo vigente la otra.
HTML en el fragmento se mostró como texto y no hubo errores de página. Se retiraron
servidor/base/cuentas ficticias temporales. Captura economic-browser-control.png y
resumen economic-browser.json en .test-results/, excluidos de Git.
Suite protegida final: **265 descubiertas = 248 anteriores + 17 nuevas; 263 aprobadas,
cero fallos/errores, dos omisiones Windows AES-GCM/ACL**, sin fallos esperados ni éxitos
inesperados. Las omisiones no validan esas capacidades en Linux. **49 JS aprobadas =
43 anteriores + 6 nuevas**, sin omisiones; pip check correcto. Se conservaron H1–H3,
R1–R7 y N1/N2 en la suite. La prueba con referencia registrada, cierre y sucesora creó
respaldo/restauración: fingerprint completo idéntico, tabla nueva poblada conservada
y bytes del ZIP cerrado iguales. No se declara recuperación ante desastre.

Python 3.12.14, SQLite 3.53.1, Node 24.19.0 y Git 2.52.0. Se reutiliza
.tmp/validation-venv sin system-site-packages; las 21 versiones del lock coinciden.
No hubo instalación ni descarga nueva, ni se modificaron dependencias o locks.
Inventario final: **146 entradas, 145 hashes/tamaños comprobados**, autoentrada sin
autohash, sin archivos adicionales. SOURCE_HASHES.json, PREPARACION.md y metadatos de
la preparación original conservados. Los 22 archivos del diff son exclusivamente
código de este bloque, regresiones y documentación/inventario; no se publican logs,
bases, usuarios, venv ni capturas. La rama queda disponible para revisión; la creación
de la PR borrador permanece bloqueada como se describe al inicio, sin fusión.

Comandos reproducibles en venv dedicado sin dependencias nuevas ni cambios de locks:

```sh
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

La primera corrida focal tuvo siete fallos por una ruta incorrecta del helper de tests
y un error por tratar el ID devuelto por create_user como dict; se corrigieron los
helpers y las 17 focales finales aprobaron. Los logs iniciales se conservan.
La desconexión del entorno interrumpió una edición
antes de aplicarla; al recuperarse se verificaron rama, diff y logs antes de continuar.

Primera suite completa: 265 ejecutadas, 258 aprobadas, cinco fallos y dos omisiones
Windows. Reveló compatibilidad de invalidación de fuentes/alcances sin referencias,
un marcador ficticio que afectaba controles económicos sin cálculo y reconfirmación
legacy al reagruparse los motivos. Se corrigieron esas dependencias sin relajar
los cinco controles de regresión; la expectativa de una captura sin versiones añade
RN14/RN15 porque sus reglas cambiaron. La regresión de migración histórica sigue probando
21→22 explícitamente; el nuevo test comprueba 22→23 con rollback/respaldo.

La primera suite JS tuvo 48 casos, 47 aprobados y un fallo: el selector de prueba
buscaba la primera opción del formulario, que ahora es el tipo de registro; se corrigió
el localizador del PDF y se conservó la aserción de HTML inerte. El navegador encontró
un 409 al usar versiones previas de Procesamiento después del guardado: se añade una
lectura de actualización, nunca otro POST de análisis, con regresión JS específica.
Dos intentos posteriores del guion leyeron la captura anterior por usar una espera async
inadecuada; el guion ahora espera el estado terminal visible y exige un análisis adicional.
El cuarto recorrido aprobó. Todos los logs previos se conservan separados de los finales.

Evidencia local excluida de Git: economic-focused-{1..6}.log, economic-python-1.log,
economic-python-1-summary.json, economic-python-final.log, economic-python-final-summary.json,
economic-node-1.log, economic-node-final.log, economic-browser-{1..4}.log,
economic-browser-api-{1..3}.log, economic-browser-control.png, economic-browser.json,
economic-runtime.json, economic-pip-check.log y economic-inventory.json en .test-results/.
El cuarto log de API se conserva como economic-browser-api.log. No se borran los fallos
ni se atribuye una causa nueva a la intermitencia histórica de procesos o WinError 32.

Windows de este incremento, aceptación humana UI y revisión independiente permanecen
pendientes. El usuario realizará la revisión; no se invocó Astra. Las pruebas de navegador
son evidencia técnica, no aceptación de comodidad. Cifrado/ACL Windows no se validan por
sus omisiones en Linux; recuperación de misma máquina no acredita desastre externo.
No hay datos reales, cuentas persistentes, servicios nuevos, fusión ni despliegue.
