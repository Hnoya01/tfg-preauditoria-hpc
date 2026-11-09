# Verificación Windows del artefacto publicado

## Alcance vigente: Q1/Q2 y migración 25→26, PR #7

Rama `feat/consultas-respuestas-externas`, base `feat/rn14-human-review`, PR #7 en
borrador. Usar el **SHA completo del informe final de estas correcciones**, no
`91a69cff9c94e4acfba7a081dc49fb44ce8c8b8c`, la base, `main` ni una rama móvil.
El esquema vigente es 26: Q2 actualiza el trigger de fechas mediante migración 25→26 con respaldo previo, sin añadir columnas ni reescribir registros.

El usuario informó Windows aprobado de 91a69cff: 298 Python y 63 JS, sin fallos ni
omisiones, migración 24→25, recuperación con/sin proxy, AES-GCM/NTFS e inventario
156/155. Es evidencia histórica aportada por el usuario, no del nuevo SHA.
Windows de las correcciones y aceptación humana siguen pendientes. No se reabre
la aprobación anterior de f903bad.

El antecedente posterior `e6715449c1cdc347fcc1de8d32ee55263014134f` tuvo 298/299
Python aprobadas y un error de barrera; JS76, Chrome y los controles de recuperación
pasaron según el usuario. La causa original sigue indeterminada. El incremento posterior
de cierres corrigió la sincronización del ensayo y agregó cobertura; la validación
Windows posterior se identifica abajo como antecedente del nuevo candidato.

Para esta corrida conservar la primera ejecución completa y todos los directorios
`.test-results/closure-concurrency-*` y `closure-probe-*`. Verificar que el ensayo
original y las cuatro regresiones de `tests.test_closure_concurrency` pasan, sin
omisiones; la suite completa las descubre automáticamente con el runner protegido.
Las fallas deliberadas dentro de las regresiones son resultados esperados capturados:
la prueba exterior debe aprobar y verificar diagnóstico/limpieza, incluida liberación
del bloqueo SQLite del descendiente. No confundir esas trazas con un fallo de suite.
Si falla Job Object/contención, conservar error nativo: no desactivar el job, cambiar
ACL, ampliar plazos ni repetir para buscar verde. Si se agotan los 60 s globales,
conservar fases y primera causa; no atribuir automáticamente el fallo al producto.
La limpieza tiene esperas adicionales acotadas de hasta 5 s por job/proceso.

Antecedente informado aprobado por el usuario: `aa9db1936f9bda1bc02cbe562604a558c285338b`,
303 Python, 76 JS, cinco focales de cierres, tres fechas y cinco escenarios U1/U2.
No valida el nuevo candidato funcional. Usar exclusivamente el SHA de su entrega.
La corrida Chromium sin filtros ahora incluye seis escenarios: cinco U1/U2 y
`q1_q2` (historia de internación sin consulta nueva y respuesta histórica).
Conservar también los tres casos canónicos de browser-datetime.json. El runner
incluye preservación de registros/ZIP cerrados, rollback del trigger y replay previo
al bloqueo de consultas nuevas. No migrar una base operativa para estas pruebas.

## Revisión que debe probarse

Copiar los 40 caracteres del informe de entrega y conservarlos en el registro.
La guía verifica ese commit exacto en una copia nueva; ninguna prueba usa una base
operativa. Si el SHA no está disponible o el checkout está sucio, detener ese bloque.

## Requisitos y copia separada

Abrir PowerShell 7 (`pwsh`). Se necesitan Git, Python 3.12 (`py -3.12`), Node con `node:test`
y los auxiliares PowerShell 7/.NET utilizados por las dos pruebas Windows. Usar el acceso
habitual ya autorizado al repositorio privado; no escribir contraseñas o tokens en comandos.
Si falta una herramienta, registrar cuál y detener sólo lo que dependa de ella. No instalar
servicios ni cambiar la configuración de seguridad del equipo para acomodar las pruebas.

Los siguientes comandos crean una carpeta nueva con nombre único bajo TEMP. No ejecutarlos
dentro de la carpeta operativa del proyecto ni reutilizar su venv. Comprobar el resultado de
cada bloque antes de seguir; todas las escrituras posteriores quedan en la copia sintética.

```powershell
$ErrorActionPreference = 'Stop'
$RevisionObjetivo = (Read-Host 'SHA completo del informe final de PR7').Trim().ToLowerInvariant()
if ($RevisionObjetivo -notmatch '^[0-9a-f]{40}$') { throw 'Se requiere el SHA completo de 40 caracteres' }
$CarpetaSintetica = Join-Path $env:TEMP ('tfg-sintetico-' + [guid]::NewGuid().ToString('N'))
git clone --no-checkout --single-branch --branch feat/consultas-respuestas-externas https://github.com/Hnoya01/tfg-preauditoria.git $CarpetaSintetica
if ($LASTEXITCODE -ne 0) { throw 'No se pudo obtener la copia privada; no agregar credenciales al comando' }
Set-Location $CarpetaSintetica
git cat-file -e "${RevisionObjetivo}^{commit}"
if ($LASTEXITCODE -ne 0) { throw 'El commit solicitado no está en la copia; no reemplazarlo por otra revisión' }
git switch --detach $RevisionObjetivo
if ($LASTEXITCODE -ne 0) { throw 'No se pudo seleccionar la revisión exacta' }
$RevisionActual = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $RevisionActual -ne $RevisionObjetivo) { throw 'El checkout no coincide' }
$CambiosIniciales = @(git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $CambiosIniciales.Count -ne 0) { throw 'La copia no está limpia' }
New-Item -ItemType Directory -Path .test-results -Force | Out-Null
```

## Venv nuevo y dependencias declaradas

```powershell
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el venv Python 3.12' }
& .\.venv\Scripts\python.exe -m pip install --no-cache-dir --index-url https://pypi.org/simple -r requirements-lock.txt 2>&1 | Tee-Object .test-results\windows-install.log
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación; conservar el log y no cambiar el lock' }
& .\.venv\Scripts\python.exe -m pip check 2>&1 | Tee-Object .test-results\windows-pip-check.log
$PipCheckExit = $LASTEXITCODE
if ($PipCheckExit -ne 0) { throw 'Dependencias incompatibles; conservar el diagnóstico' }
```

La instalación deshabilita la caché local de pip. Registrar si el log confirma descargas;
no afirmar descarga limpia si no se completó. No instalar pypdf ni otras dependencias para
este circuito: el lock cubre la suite. No actualizar pip ni resolver otro lock en esta tarea.
Si ensurepip falla por TEMP/TMP, aplicar únicamente el procedimiento temporal del README en
esta copia; registrar lo ocurrido. No copiar paquetes desde el venv operativo.

## Pruebas y registro

```powershell
& .\.venv\Scripts\python.exe -B -m scripts.run_synthetic_tests
$PythonExit = $LASTEXITCODE
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs tests/web_medical_consultations.test.cjs 2>&1 | Tee-Object .test-results\windows-node.log
$NodeExit = $LASTEXITCODE

$Registro = @(
    "revision=$RevisionActual"
    "python_exit=$PythonExit"
    "node_exit=$NodeExit"
    "pip_check_exit=$PipCheckExit"
)
$Registro | Set-Content -Encoding utf8 .test-results\windows-result.txt
& .\.venv\Scripts\python.exe -c "import platform,sqlite3,sys; print(sys.version); print(platform.platform()); print('SQLite',sqlite3.sqlite_version)" | Add-Content .test-results\windows-result.txt
node --version | Add-Content .test-results\windows-result.txt
$PSVersionTable.PSVersion.ToString() | Add-Content .test-results\windows-result.txt
& .\.venv\Scripts\python.exe -m pip list --format=freeze | Set-Content -Encoding utf8 .test-results\windows-packages.txt
Get-Content .test-results\python-summary.json
Get-Content .test-results\windows-result.txt
git config --show-origin --get core.autocrlf | Add-Content .test-results\windows-result.txt
git status --short
```

Aunque Python falle, ejecutar Node permite conservar su resultado independiente. Si Python
no genera `python-summary.json`, registrarlo como no completado; no inventar un resumen ni
cambiar el runner, las aserciones o los decoradores para obtener un resultado favorable.
No usar `unittest discover` como reemplazo: no añade el aislamiento del runner.

Comparar resultados con el informe del **mismo SHA** y registrar cantidades reales.
No fijar el número de pruebas a los antecedentes: las regresiones nuevas lo amplían.
En Windows deben ejecutarse AES-GCM/.NET y ACL NTFS, sin omisiones esperadas. Un
fallo, error, omisión inesperada o resumen ausente queda pendiente de investigar;
no cambiar aserciones ni controles para lograr una aprobación.

Las pruebas usan sus propios datos, usuarios y temporales ficticios. No añadir archivos de
pacientes, catálogos operativos ni respaldos propios. Los resultados quedan en .test-results/
y los temporales bajo .tmp/ de la copia; no deben incorporarse a Git.

## Diagnóstico dirigido de empaquetado y P01

Si se necesita aislar un fallo, en esta misma copia sintética y después de conservar
los logs del runner completo:

```powershell
& .\.venv\Scripts\python.exe -B -m unittest -v tests.test_release_portability tests.test_resource_lifecycle tests.test_p01.P01Tests.test_cookie_csrf_origin_lockout_and_idle_expiry 2>&1 | Tee-Object .test-results\windows-portability-targeted.log
$TargetedExit = $LASTEXITCODE
"targeted_exit=$TargetedExit" | Add-Content .test-results\windows-result.txt
Get-Content .test-results\p01-resources.jsonl
```

Son comprobaciones dirigidas; este comando unittest no instala el hook del runner y no
reemplaza la verificación completa aislada. Los repositorios LF/CRLF son temporales:
sólo cambian su configuración local. No cambiar core.autocrlf global ni normalizar
inventarios para acomodar el resultado. P01 conserva los tres clientes y trabajadores;
registra conexiones y estado de hilos antes de eliminar la base. Si reaparece WinError 32,
conservar el traceback y p01-resources.jsonl: no borrarlo con fuerza, tolerar el error,
agregar sleeps ni atribuir automáticamente quién retiene el archivo. Incluso si los
contadores son cero, no demuestran ausencia de todos los handles nativos/externos.

## Qué devolver y qué queda fuera

Devolver el SHA, versiones, códigos de salida, `python-summary.json`, `python.log`,
`windows-node.log`, `windows-pip-check.log`, `p01-resources.jsonl` y el estado final de Git. Si falló la instalación,
conservar también `windows-install.log`. Si se ejecutó el diagnóstico, añadir `windows-portability-targeted.log`. No enviar el venv, bases, carpetas completas ni
credenciales. Revisar cualquier diagnóstico ajeno a la suite antes de compartirlo.

No ejecutar migraciones operativas, abrir accesos públicos, fusionar PR o validar usabilidad
por el mero hecho de aprobar tests. La aceptación de interfaz se revisa por separado con las
capturas ficticias de la jornada. Conservar la copia hasta revisar resultados; su eliminación
posterior es una decisión del usuario, no un paso automático de esta guía.

Antecedente histórico R1–R7 (el esquema vigente es 26): esquema 22, fundamentos selectivos, extras preservados en backup, release
compatible, arranque desde código restaurado, alcances congelados, origen histórico, auditoría
de respuesta y lecturas coherentes. Comprobar especialmente el cerrojo nativo msvcrt, la
liberación al terminar un proceso y las dos pruebas Windows AES-GCM/ACL. Estas comprobaciones
Windows del SHA nuevo aún no se ejecutaron; no requieren migrar ninguna base propia. La revisión
independiente Astra queda a cargo del usuario; esta guía no acredita esa revisión.

Corrección de portabilidad: paquetes desde blobs originales sin conversión; cierre explícito
si falla la inicialización SQLite y error ante apagado con hilos vivos. No se afirma que
se haya identificado el retenedor original de WinError 32 ni se validó Windows en nube.
Paquete de revisión: REVISION_PORTABILIDAD.md.

## Comprobación focalizada y revisión independiente

Además de la suite completa, repetir las regresiones U2/U1:

```powershell
node --test tests/web_medical_consultations.test.cjs tests/web_values.test.cjs
& .\.venv\Scripts\python.exe -B -m unittest tests.test_medical_consultations.MedicalConsultationTests.test_exact_replay_after_closed_revision_has_no_second_event_or_version
```

El comando Python focal no sustituye el aislamiento del runner. Las siete suites JS
se enumeran en el bloque principal, incluida `web_medical_consultations.test.cjs`.
El runner completo prueba migraciones 24→25 y 25→26 (respaldo y rollback), cierres, recuperación/activación y con/sin
proxy; conservar sus logs. Para validar paquete/inventario, no modificar bytes ni
normalizar hashes: las pruebas de release/recuperación comprueban el artefacto.

Con un runtime Playwright/Chromium ya disponible, ejecutar
el siguiente bloque sin filtros y conservar JSON/logs de `.test-results/`:

```powershell
Remove-Item Env:TFG_BROWSER_CASE -ErrorAction SilentlyContinue
$env:TFG_BROWSER_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
# TFG_CHROMIUM debe señalar el Chrome disponible; NODE_PATH, el runtime Playwright existente.
node tests/browser_write_outcomes.cjs 2>&1 | Tee-Object .test-results\windows-browser.log
$BrowserExit = $LASTEXITCODE
"browser_exit=$BrowserExit" | Add-Content .test-results\windows-result.txt
if ($BrowserExit -ne 0) { throw 'Conservar primera corrida y diagnosticar; no repetir para buscar verde' }
```
Si falta ese runtime, registrar el ensayo como no ejecutado, sin declararlo aprobado.
Son datos ficticios y fallos de red controlados: U2 debe conservar un ID, una respuesta,
un evento y un incremento de versión; U1 debe distinguir guardado confirmado de
pantalla pendiente, y leer historia ante resultado incierto sin reenviar el POST.

Para la revisión focalizada Astra (a solicitar por el usuario; no automática),
proporcionar el SHA publicado y comparar desde 91a69cff. Revisar aislamiento por
sesión/fila/revisión de operaciones pendientes, conservación exacta del cuerpo y
clave tras reconstrucción, cierre/reapertura, revocación y respuestas tardías;
revisar éxito de escritura separado del refresco y ausencia de reintentos no
idempotentes. Para este candidato comparar además Q1/Q2 desde aa9db193: creación
nueva restringida sólo en I, historia/replay conservados y migración 25→26 sin
reescribir datos ni cierres. Contrastar pruebas DOM, HTTP/Chromium y los
bloqueos de evidencia declarados en ESTADO.md; no confundirlos con aceptación humana.

<details>
<summary>Antecedentes textuales de la guía anterior (no son instrucciones vigentes)</summary>

### Guía histórica

## Revisión humana RN14: versión nueva pendiente

Esta guía comprueba ahora **feat/rn14-human-review**, con base **feat/hpc-row-applicability**
en a376491354aa90ecf47a328c05eed29860695079 (PR #5). Introducir el SHA completo
publicado del informe final, no el nombre de rama ni el SHA de la base. Windows de
a376491 sigue pendiente y no valida esta versión. La aceptación humana UI está diferida
al fin de semana; las pruebas automáticas no la sustituyen. Las pruebas de simulación
no ejecutan débitos ni operan bases reales. [Paquete RN14](REVISION_PROPUESTAS_RN14.md).
Se añadieron 17 regresiones Python y 7 JS; conservar las cantidades reales del runner.
Los apartados de versiones anteriores siguientes son antecedentes.

## Incremento económico HPC: revisión nueva pendiente

Esta guía se aplica ahora a la rama **feat/hpc-row-applicability**, apilada con base
**feat/new-batch-review** en f903bad58c176312e3637fd1394d78d22addc8ec. El informe final
proporciona el SHA remoto completo y el estado real de su PR (creación bloqueada al
cerrar esta guía): introducir el SHA publicado en el
paso de checkout exacto, sin sustituirlo por la rama ni por f903bad.
El usuario informó para f903bad 248 Python y 43 JS aprobadas sin omisiones, pip check
correcto y recuperación con/sin proxies con hashes intactos. Ese resultado no valida
este incremento ni identifica el retenedor del antiguo WinError 32.
Las 17 nuevas regresiones Python cubren la aplicación por fila; hay seis nuevas JS.
Conservar resultados reales del runner, errores y omisiones; no inferir éxito de los
totales esperados ni de Linux. Detalles: [paquete económico](REVISION_ECONOMICA_HPC.md).

Los antecedentes de portabilidad siguientes corresponden a versiones anteriores.

Pendiente de ejecución del SHA nuevo por el usuario. La versión 89571d9d53872c9ae3f5ff870f96f6131665ff08
falló en Windows: 239 Python, 226 aprobadas, 13 errores, cero omisiones; 41 JS y pip check
correctos. Doce errores fueron de inventario al preparar/inspeccionar releases y uno fue
WinError 32 en limpieza P01. No se considera validada. El resultado anterior 224/39 de
76f18c37d9601641c555c6f10dae64b0360c8ad2 tampoco valida el nuevo SHA.
Esta guía comprueba un commit exacto en una copia nueva; no opera el proyecto original ni
migra bases reales. La suite abre una API temporal sólo en loopback para el ensayo de
recuperación y la detiene al terminar; no crea un servicio persistente. Versión de portabilidad/cierre de recursos de feat/new-batch-review; resultado Linux en ESTADO.md.
El informe final identifica el SHA del paquete que debe verificarse, incluida su documentación.


</details>
