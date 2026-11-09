# B18-R27 · Entrega del prototipo de preauditoría HPC

En una PC nueva, seguí primero la sección **Instalación Windows** de este archivo desde la carpeta `fuentes`. Una vez creado el entorno e instaladas las dependencias, abrí **ABRIR-DEMO.cmd** desde esta carpeta y entrá como **demo-administrativo**. Elegí **DEMO FICTICIO · recorrido administrativo y auditor**, factura **FICTICIO_presupuesto_TAC.xlsx**, y revisá la TAC del **02/08**. El presupuesto está en una columna distinta del débito propuesto. El pase al auditor y la descarga se realizan en la planilla de la misma factura.

El [guion de la entrega](GUIA-DEMO-R27.txt) contiene los pasos para empezar con la factura preparada o cargar el Excel y el CSV ficticios. Los [resultados verificados](docs/ESTADO.md) distinguen la demo del cotejo local de agosto. Las guías y manifiestos de versiones anteriores son históricos.

[Guía breve para la defensa](docs/DEFENSA_R27.txt)

Para la mesa examinadora: la guía vigente es [GUIA-DEMO-R27.txt](GUIA-DEMO-R27.txt). Las instrucciones de R22 a R26 describen ensayos anteriores.

## Antecedente B18-R26 · Plazo de facturación de Imágenes HPC

Abrí [ABRIR-DEMO.cmd](ABRIR-DEMO.cmd) y entrá como demo-administrativo en la factura ficticia `FICTICIO_autorizaciones_R26.xlsx`. El filtro **Facturación fuera de término** muestra la TAC del 16/07 con $100.000 a revisar. **Ver factura completa** permite consultar también la TAC del 17/07. Ambas tienen una orden de autorización ficticia. La [validación de agosto](docs/ESTADO.md) contiene el resultado del cotejo y los pasos de reproducción.

## Antecedente B18-R25 · Preauditoría de Imágenes HPC

La [guía de la demo R25](GUIA-DEMO-R25.txt) describe la TAC repetida y el comprobante de incorporación grupal. Se inicia con ABRIR-DEMO.cmd. El [estado de la entrega](docs/ESTADO.md) contiene la comparación con R24 y los límites del ensayo local.

## Antecedente B18-R24 · Equivalencias, adicionales y unidades

El estado vigente y el cruce real están en [docs/ESTADO.md](docs/ESTADO.md). El [guion de la demo](GUIA-DEMO-R24.txt) explica la mamografía bilateral y la radiografía con exposición adicional. Abrí ABRIR-DEMO.cmd para iniciar la presentación ficticia en un puerto libre de loopback.

# B18-R23 · Demo de Imágenes HPC

El estado vigente y los resultados están en [docs/ESTADO.md](docs/ESTADO.md). El [guion de presentación](GUIA-DEMO-R23.txt) explica los tres conjuntos ficticios. Abrí ABRIR-DEMO.cmd para iniciar la demo en un puerto libre de loopback.

# B18-R22 · Preauditoría de Imágenes HPC

Abrí [ABRIR-DEMO.cmd](ABRIR-DEMO.cmd) en Windows. El [guion de cinco minutos](GUIA-DEMO-R22.txt) indica la factura, las cuentas ficticias y los importes esperados. El [estado de R22](docs/ESTADO.md) contiene los resultados de pruebas y la validación agregada. Los apartados que siguen describen incrementos anteriores del prototipo.

## Recorrido administrativo y auditor

[Guía del circuito y demo ficticia](docs/RECORRIDO_ADMIN_AUDITOR.md): resolución por observación,
derivaciones internas, solicitud de información e historia compartida. Rama local de prueba,
sin publicación ni aprobación económica. Migración aditiva a esquema 27 con respaldo previo.

## Documentación y requisitos

- [Requisitos vigentes del TP](docs/REQUISITOS_TP.md): especificación, no estado de implementación.
- [Decisiones confirmadas](docs/DECISIONES.md) y [contrato A1](docs/AUTORIZACIONES_JSON.md).
- [Contrato de fuentes](docs/CONTRATOS_DATOS.md), [exclusiones](docs/EXCLUSIONES.md).
- [Estado, resultados y pendientes](docs/ESTADO.md).
- [Revisión humana RN14 y simulaciones separadas](docs/REVISION_PROPUESTAS_RN14.md): confirmación/ajuste explícito, historia y separación de totales.
- [Referencia económica HPC por fila](docs/REVISION_ECONOMICA_HPC.md): aplicabilidad documentada, RN14/RN15 y límites; sin propuestas automáticas.
- [N1/N2: transporte local y motivos administrativos](docs/REVISION_N1_N2.md): diff local sobre e3e114b, sin publicación.
- [Manifiesto de archivos de esta entrega](SHA256-ENTREGA.txt) y [preparación](docs/PREPARACION.md).

Python 3.12 es la base documentada. Node.js se necesita sólo para las pruebas JavaScript
(node:test, sin dependencias npm ni build). SQLite viene con Python. PowerShell 7 y .NET
son necesarios para probar los auxiliares actuales de cifrado/ACL en Windows.
No se necesita Microsoft Excel, Word ni acceso al sistema hospitalario.

Guía de comprobación en copia nueva: [Windows, revisión exacta y evidencia](docs/VERIFICACION_WINDOWS.md).

## Instalación Windows (PowerShell, desde esta copia)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
```

Si ensurepip falla por la ubicación temporal, crear .tmp y configurar TEMP/TMP sólo para
esta consola; ejecutar `.\.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip`.
No modificar la instalación original ni usar su venv. El lock de Windows se conserva byte a byte.

## Instalación Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip check
```

Si el lock no resuelve en Linux, conservar el error y resolver en un venv nuevo con
`pip install -r requirements-dev.txt`; guardar un lock Linux separado después de probarlo.
No sobrescribir el lock Windows ni afirmar equivalencia de versiones sin comparar.
Podrían requerirse paquetes del sistema para venv o compilación si no hay wheels compatibles.

## Auxiliar documental opcional

`python -m pip install -r requirements-documentary.txt` instala pypdf 6.10.0 en el venv
seleccionado. Es la versión inspeccionada del runtime auxiliar, no una actualización de la app.
`prepare_agreement_review` requiere referencias PDF y catálogo autorizados; no se incluyen ni
se ejecuta con fuentes reales en esta copia. Su función de parser tiene pruebas sintéticas.

## Pruebas sintéticas

Windows:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs tests/web_medical_consultations.test.cjs
```

Linux:

```sh
.venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs tests/web_medical_consultations.test.cjs
```

El runner crea sus temporales, limpia variables TFG heredadas y limita accesos de archivos Python
al árbol de la copia y al intérprete. Los auxiliares nativos revisados no están aislados por ese hook.
Los resultados locales van a .test-results/ (excluido). Las pruebas de ACL y AES-GCM se omiten en Linux
por sus decoradores originales; una omisión no valida la función. No se relajan controles.
En Linux, el runner inicializa `mimetypes` con la tabla incorporada de Python, después de
instalar el hook; no consulta `/etc/mime.types` ni depende de tablas MIME heredadas.
La configuración afecta sólo al proceso de pruebas y no cambia el arranque de la API.
Windows conserva su inicialización anterior. Las regresiones comprueban HTML/CSS/JS,
OpenPyXL y rechazos de lectura/escritura externos en procesos nuevos.

También funciona `python -m unittest discover -s tests -t . -v`: el helper crea .tmp, pero ese comando
no añade el aislamiento del runner y no es el recomendado para la verificación de esta copia.

## Recuperación segura e historia de análisis

Una restauración permanece en cuarentena desde el inicio de la extracción. La API y las
conexiones de operación rechazan destinos pendientes, incompletos o sin activación verificada,
antes de abrir la base con escritura. `scripts.recovery_data.activate_quarantined(destino)`
es una operación local explícita: revoca las sesiones recuperadas y registra la activación.
Puede retomarse si se interrumpe entre el commit y el comprobante. El directorio restaurado
mantiene los trabajadores deshabilitados; no se habilitan automáticamente al arrancar la API.
Un directorio de datos normal conserva el arranque habitual. Los metadatos de recuperación
son archivos privados del operador; no protegen frente a quien pueda reescribir la base y sus archivos.
No ejecutar una restauración o migración sobre datos operativos sin una tarea específica.

El esquema vigente 26 conserva historia de análisis (19), cierre C1 (20), revisiones C2 (21)
y capturas compartidas/formato de fundamentos (22); añade referencias económicas
inmutables por fila y revisión (23), sin activar referencias legacy. Añade simulaciones
en tabla separada y FK de procedencia de importes RN14 (24), y consultas/respuestas
externas inmutables (25) y recepción histórica con fecha de registro separada (26). Las bases existentes requieren
respaldo y actualización offline mediante el comando ya disponible `app.cli backup-and-upgrade`;
el servidor no migra automáticamente una base antigua. En una base ficticia, con servidor detenido:

```sh
.venv/bin/python -B -m app.cli --data-dir .tmp/demo-data backup-and-upgrade
```

Antes de evaluar se conserva una captura durable; los resultados completos se guardan antes
de intentar publicarlos. Un conflicto sigue rechazando la publicación y conserva esos resultados
como históricos. Las capturas interrumpidas pueden quedar en `captured` o `prepared`: no son
análisis vigentes, no crean decisiones ni habilitan importes. El historial se consulta con sesión
y permiso de revisor, mediante rutas GET con `offset` y `limit` (1–100):

- `/api/datasets/{dataset_id}/batches/{batch_id}/analysis-history`
- `/api/datasets/{dataset_id}/analysis-history/{identity}`

Son consultas de evidencia, separadas del último análisis operativo; no añaden una pantalla nueva.
El recorrido sintético combinado está en `tests/test_integrated_journey.py` y se ejecuta dentro
del runner documentado. Incluye Excel/A1/HPC, decisiones, invalidación selectiva, reanálisis y
exportación provisional, con importes ficticios sin aprobación económica real.

## C1: cierre y exportación congelada

En Salida, Revisar condiciones de cierre presenta pendientes, controles y limitaciones.
Un fundamento se registra una vez por causa/alcance y conserva historial. Al confirmar el
cierre se seleccionan expresamente las limitaciones vigentes; no se vuelven a escribir sus
fundamentos si no cambió el alcance. Alertas pendientes o procesamiento activo bloquean el cierre.
Una limitación no aprueba el control ni resuelve una alerta pendiente. La falta de respaldo
monetario permanece sin cuantificar, nunca se convierte en cero ni en aprobación económica.

Los controles sin resultado se identifican como no ejecutados. RN20–RN22, todavía sin implementación,
se incluyen como limitación documental con aplicabilidad sin verificar; no se infiere que
sean no aplicables. La revisión puede cerrarse con esas limitaciones sólo si están justificadas
y confirmadas. Esto no acredita cumplimiento completo del TP ni de toda la factura.

El servidor comprueba permiso de revisor y versiones antes de confirmar en una transacción:
manifiesto, referencia al archivo privado, estado cerrado y auditoría. La captura se prepara
antes; un conflicto/rollback no deja cierre parcial. Los bytes publicados sin registro se
preservan y se incluyen separadamente en el inventario del backup, incluso si esperan un commit. Nunca se
borran automáticamente ni se relaja la detección de originales registrados ausentes/alterados.

Las descargas posteriores devuelven el archivo conservado y verificado por hash; no vuelven
a analizar ni recalculan decisiones o importes con fuentes posteriores. El cierre y sus
registros de limitaciones son inmutables. Una nueva revisión C2 se vincula a la anterior;
no se reabre ni modifica una revisión cerrada.

Rutas autenticadas (POST exige origen y CSRF):

- POST `/api/datasets/{dataset_id}/batches/{batch_id}/closure-preview`
- POST `/api/datasets/{dataset_id}/batches/{batch_id}/closure-limitations`
- POST `/api/datasets/{dataset_id}/batches/{batch_id}/closure`
- GET `/api/datasets/{dataset_id}/batches/{batch_id}/export-closed`
- GET `/api/datasets/{dataset_id}/batches/{batch_id}/closure-summary?revision_id={revision_id}`
- GET `/api/datasets/{dataset_id}/batches/{batch_id}/closure-members?group_key={group_key}&scope_sha256={scope_sha256}&offset=0&limit=50`

Antecedente C1: el esquema 22 requirió respaldo/actualización offline. El vigente es 26; no ejecutar sobre
bases operativas dentro de esta tarea. Guía y paquete para revisión independiente del usuario:
[Revisión C1](docs/REVISION_C1.md). No se ejecutó revisión Astra durante C1 por decisión explícita.

## C2: nueva revisión del mismo lote

En Salida, **Consultar historial de revisiones** permite descargar cada cierre y abrir
una revisión posterior indicando motivo y confirmación expresa. Requiere rol de revisión,
predecesora cerrada con captura C1, versiones vigentes y ninguna revisión abierta.
No duplica el Excel ni sus filas; conserva vínculo, responsable, fecha, cierre/hashes,
fuentes anteriores/disponibles y referencias a decisiones/propuestas históricas.

La revisión nueva parte de las filas originales, sin heredar correcciones, selección de
capturas JSON, vínculos, declaraciones temporales/unidades, alcance de prestador, decisiones,
propuestas ni fundamentos de limitaciones como vigentes. Deben confirmarse de nuevo.
Las fuentes registradas siguen disponibles; registrarlas no analiza ni modifica un cierre.
Los controles se ejecutan sólo por acción explícita. Las comparaciones usan una única
revisión por lote (abierta o última) y no duplican cantidades/cobertura por tener historia.
La reutilización asistida de trabajo entre revisiones no se implementa en C2.

Rutas autenticadas adicionales:

- GET/POST `/api/datasets/{dataset_id}/batches/{batch_id}/revisions`
- GET `/api/datasets/{dataset_id}/batches/{batch_id}/export-closed?revision_id={revision_id}`

Sin parámetro, la descarga elige el último cierre por ordinal. Una alerta de revisión
anterior remite a su captura congelada mediante rechazo 409; no mezcla sus datos con la
revisión actual. El export provisional y los controles operativos se refieren a la actual.
El manifiesto posterior incorpora la procedencia de apertura. El ZIP anterior se entrega
sin recalcular, incluso después de nuevos análisis o cierres.

Migración 21: vistas de selección, propiedad por revisión de las historias de evidencia y
datos de trabajo separados. La migración conserva los datos existentes y exige respaldo
previo/actualización offline; se probó sólo con bases ficticias. No ejecutar migraciones
operativas en este bloque. Paquete/evidencia y límites: [Revisión C2](docs/REVISION_C2.md).
El usuario informó Windows correcto para C2 auditado (76f18c3, 224 Python + 39 JS);
no valida los cambios R1–R7. Windows del SHA nuevo y revisión independiente siguen pendientes.

## Correcciones de auditoría R1–R7

Paquete funcional: [matriz, decisiones técnicas, regresiones y límites](docs/REVISION_R1_R7.md).
Corrección posterior vigente: [portabilidad y cierre de recursos](docs/REVISION_PORTABILIDAD.md).
Windows de 89571d9 falló (226/239 Python, 13 errores); el nuevo SHA requiere repetirlo.
El formato `closure-input-v2` conserva una captura compartida y dependencias pertinentes
por miembro; los fundamentos abiertos legacy requieren reconfirmación expresa. Los cierres
anteriores y sus ZIP siguen intactos. Salida permite consultar miembros paginados y el resumen
congelado de una revisión concreta. Los antecedentes indican su revisión/cierre de origen y
no acreditan vigencia. Las descargas registran preparación de respuesta, no recepción del cliente.

El backup toma un snapshot SQLite/objetos coordinado entre procesos. Preserva y clasifica extras
sin registrarlos como originales; no los mueve ni elimina. Las releases nuevas vinculan commit,
hashes/inventario y esquema real. El paquete limpio lee blobs por OID, sin convertir EOL
mediante git archive; un inventario discordante sigue siendo un error. El ensayo arranca desde la aplicación extraída en proceso aislado;
no equivale a recuperación ante desastre ni a validación de cifrado/ACL en Linux.
Un fallo al configurar SQLite cierra la conexión; el apagado comunica hilos aún vivos.
P01 registra cierres y estados antes de su limpieza estricta, sin omitir autenticación. Detalles y ejemplo
de paquete de código limpio en el documento de revisión. No usar fuentes operativas en estas pruebas.

## Arranque de una demostración local, no ejecutado por esta preparación

Crear una cuenta propia por CLI; nunca reutilizar contraseñas ficticias de tests.
Windows:

```powershell
$env:TFG_DATA_DIR = Join-Path (Get-Location) '.tmp/demo-data'
$env:TFG_PUBLIC_ORIGIN = 'http://127.0.0.1:8000'
$env:TFG_LOCAL_HTTP = '1'
.\.venv\Scripts\python.exe -m app.cli add-user --username demo-admin --role admin
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Linux local:

```sh
export TFG_DATA_DIR="$PWD/.tmp/demo-data"
export TFG_PUBLIC_ORIGIN=http://127.0.0.1:8000
export TFG_LOCAL_HTTP=1
.venv/bin/python -m app.cli add-user --username demo-admin --role admin
.venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Los generadores `python -m scripts.create_b02_demo` y `create_b03_demo` crean sólo ejemplos
inventados en .tmp; dependen de helpers de tests y por ello requieren requirements-dev.
En nube no reutilizar el modo HTTP local para una URL pública: usar origen HTTPS exacto,
cookies seguras, almacenamiento privado persistente y acceso al puerto autorizado. No se
configuró nada de ello aquí. SQLite usa WAL; la persistencia y concurrencia deben probarse
con el volumen elegido. Evitar réplicas o varios workers hasta validar su coordinación.

## Consultas y respuestas externas RN26

Desde Detalle de una prestación, abrir **Consultas y respuestas externas**.
Permite registrar consultas y aclaraciones recibidas fuera del sistema, con emisor
informado y registrador separados. No envía mensajes ni modifica alertas o dinero.
[Contrato, cierre, migración y límites](docs/CONSULTAS_EXTERNAS.md).

El esquema vigente es 26. Se requiere respaldo y actualización offline de bases
anteriores. Para verificar este incremento completo (datos ficticios exclusivamente):

```sh
.venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs tests/web_medical_consultations.test.cjs
.venv/bin/python -m pip check
```

En Windows usar `.\.venv\Scripts\python.exe` según la instalación de esta copia.
El resultado Linux no acredita Windows ni aceptación humana.

## Antecedente: correcciones U2/U1/D1 de la PR #7

Rama vigente: `feat/consultas-respuestas-externas`; base `feat/rn14-human-review`.
Validar el SHA remoto completo del informe final, en una copia nueva; no usar `main`
ni seguir una rama móvil. [Procedimiento Windows](docs/VERIFICACION_WINDOWS.md).
Ese incremento usaba esquema 25, sin migración adicional ni dependencias nuevas.
Windows informado para `91a69cff9c94e4acfba7a081dc49fb44ce8c8b8c` es antecedente;
no valida el nuevo SHA. Registrar los resultados reales, sin presuponer cantidades.

Ensayo opcional de navegador real, con Playwright/Chromium disponibles en el entorno:
`node tests/browser_write_outcomes.cjs`. Usa fixtures ficticios, servidor loopback
127.0.0.1:18783 y elimina bases/cuentas al terminar; produce evidencia excluida en
`.test-results/`. `TFG_BROWSER_PYTHON` y `TFG_CHROMIUM` permiten indicar ejecutables
existentes. No instalar dependencias nuevas ni abrir puertos públicos para acomodarlo.
`--baseline-u2` sirve sólo el JS original de 91a69cff para demostrar el duplicado;
no cambia el checkout ni opera datos reales. Este ensayo no sustituye las siete suites.

## Q1/Q2: alcance de consultas y recepción histórica

El candidato vigente usa esquema 26. En internación no se crean consultas nuevas;
se conserva historia, respuestas a consultas existentes según reglas vigentes y
replay exacto. No se amplía el bloqueo a otras exclusiones. Una respuesta externa
puede tener fecha informada de recepción anterior al registro de la consulta;
la fecha de registro sigue siendo del servidor. No se cambian datos históricos.
La migración 25→26 requiere respaldo previo y reemplaza sólo el trigger de fechas.
Validar el SHA completo de la entrega con el procedimiento Windows vigente y el
runner protegido. El navegador sin filtros ejecuta cinco U1/U2 más q1_q2, y tres
casos de fecha. aa9db193 sigue como antecedente validado por el usuario; el nuevo
SHA requiere su propia validación Windows y aceptación humana.
