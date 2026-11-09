@echo off
setlocal
cd /d "%~dp0"
set "demo_python=%TFG_BROWSER_PYTHON%"
if not defined demo_python set "demo_python=%~dp0.venv\Scripts\python.exe"
if not exist "%demo_python%" (echo Falta Python del entorno. Siga los pasos de GUIA-DEMO-R27.txt para preparar .venv. & pause & exit /b 1)
if not exist ".tmp\presentacion-R27\app.sqlite3" (
  "%demo_python%" -B -m scripts.create_r27_demo
  if errorlevel 1 (pause & exit /b 1)
)
echo Acceso ficticio: demo-administrativo. Clave local en .tmp\presentacion-R27\credenciales-demo.txt
"%demo_python%" -B -m scripts.start_r22_demo --name presentacion-R27 --abrir %*
set "demo_exit=%errorlevel%"
pause
exit /b %demo_exit%
