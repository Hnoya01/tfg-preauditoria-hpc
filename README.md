# Preauditoría administrativa de facturación - Imagenes

Prototipo de Trabajo Final de Grado. El administrativo cruza la factura con las autorizaciones y revisa las prestaciones observadas. El auditor confirma el cierre y descarga el detalle de los débitos. La demo genera datos ficticios en el equipo.

## Video de demostración

Pendiente de publicación. El enlace al video se agregará en esta sección.

## Ejecutar en Windows

1. Descargue el [ZIP revisado de la entrega](https://github.com/Hnoya01/tfg-preauditoria-hpc/releases/download/B18-R27/B18-R27-mesa-Windows.zip) y extráigalo.
2. Con Python 3.12 instalado, abra PowerShell en la carpeta `B18-R27\fuentes` y ejecute:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
   .\.venv\Scripts\python.exe -m pip check
   ```

3. Abra `ABRIR-DEMO.cmd` y mantenga su ventana abierta. El navegador mostrará la demo local.
4. Ingrese como `demo-administrativo`. La clave se genera en `.tmp\presentacion-R27\credenciales-demo.txt`. Elija «DEMO FICTICIO · recorrido administrativo y auditor» y abra `FICTICIO_presupuesto_TAC.xlsx`.
5. Siga la [guía de la demo](B18-R27/fuentes/GUIA-DEMO-R27.txt) para revisar las dos TAC, pasar la factura al auditor y descargar el Excel. Para terminar, presione Ctrl+C en la ventana del iniciador.

[Código del prototipo](B18-R27/fuentes/) · [Guía de defensa](B18-R27/fuentes/docs/DEFENSA_R27.txt)
