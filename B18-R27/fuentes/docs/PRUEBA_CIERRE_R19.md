# Prueba del cierre de Imágenes en Windows

La copia R19 tiene una factura ficticia lista para **demo-auditor** en `.tmp/demo-cierre-auditor`. El administrativo ya envió sus dos decisiones. La factura preparada sigue sin cerrar; el Excel de ejemplo en `.test-results-r19/Debitos-TAC-ficticias.xlsx` salió de otra factura desechable.

1. Ingresá como **demo-auditor**. La contraseña de esta demo está en su archivo local `credenciales-demo.txt`. En Planilla abrí **FICTICIO_presupuesto_TAC.xlsx**.
2. Verificá las dos TAC de $450.000 cada una: el 02/08 llega con $250.000 de débito administrativo y el 04/08 con $0. En el resumen deben figurar $900.000 facturados en Imágenes, $250.000 a confirmar y $650.000 netos.
3. En la primera TAC elegí **Ajustar**, ingresá `200000,00` y escribí tu motivo final. Pulsá **Guardar ajuste**. Debés ver $200.000 a confirmar y $700.000 netos. La decisión administrativa de $250.000 se conserva. Si coincidís con la segunda decisión, no hace falta editarla.
4. Elegí **Cerrar factura y confirmar $200.000,00**. Aceptá la confirmación. La factura debe decir **Cerrada**, sin botones de edición. Con **Descargar Excel de débitos** obtenés tres columnas: orden, importe final (ARS) y motivo final. Para este ejemplo hay una sola fila: orden ficticia 2, $200.000 y el motivo que guardaste. La segunda TAC permanece en pantalla, no en el Excel.
5. Reabrí la factura: podés descargar de nuevo el mismo archivo. El cierre y el débito son locales al prototipo.

**Inicio manual** en PowerShell (en esta PC; no inicia ni cambia otras demos). El bloque pide al sistema un puerto de loopback y pasa ese mismo puerto a Uvicorn. Si lo ocupa otra aplicación entretanto, Uvicorn falla sin cerrarla. Abrí la URL que imprime la terminal. Para detener este servidor usá Ctrl+C en esa misma terminal.

```powershell
# Desde la carpeta fuentes de una copia preparada de R19.
$pythonR19 = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$env:TFG_DATA_DIR = (Resolve-Path -LiteralPath '.tmp\demo-cierre-auditor').Path
if (!(Test-Path -LiteralPath (Join-Path $env:TFG_DATA_DIR 'app.sqlite3') -PathType Leaf)) { throw 'Falta la demo R19' }
$portProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
try { $portProbe.Start(); $portR19 = $portProbe.LocalEndpoint.Port } finally { $portProbe.Stop() }
$env:TFG_PUBLIC_ORIGIN = "http://127.0.0.1:$portR19"
$env:TFG_LOCAL_HTTP = '1'
Write-Output $env:TFG_PUBLIC_ORIGIN
& $pythonR19 -B -m uvicorn app.api:app --host 127.0.0.1 --port $portR19
```

Para repetir desde el pase sin reemplazar la demo, elegí un nombre nuevo y ejecutá `python -B -m scripts.create_review_journey_demo --cierre-auditor --name NOMBRE-NUEVO` desde estas fuentes con el mismo intérprete. El generador se niega a sobrescribir un directorio existente. Apuntá `TFG_DATA_DIR` únicamente al directorio nuevo.

**Pruebas reproducibles desde estas fuentes:** `& $pythonR19 -B scripts/verify_r19_audit.py`; para JavaScript, `$js = Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object FullName; node --test @js`; para la prueba de navegador, `$env:TFG_BROWSER_PYTHON = $pythonR19; node tests/r19_browser_smoke.cjs`. El navegador arranca y apaga un servidor temporal sobre 127.0.0.1 y usa otra factura ficticia.

