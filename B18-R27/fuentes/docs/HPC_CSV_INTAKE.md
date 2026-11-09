# CSV de plataforma HPC: contrato observado v1

Se admite el CSV UTF-8 (BOM opcional), delimitado por coma y escapado CSV estándar, incluida cabecera entrecomillada estándar, con las 21 columnas exactas definidas en `app/hpc_csv_adapter.py`. Límite: 5.000 registros y límite general de bytes de fuentes. No se consulta la plataforma ni se descargan adjuntos.

## Recorrido

El operador carga `.csv` por la misma pantalla de autorizaciones. Se conserva el original por SHA-256. La previsualización transforma a A1, conserva el CSV como fuente autoritativa y expone conteo y localizadores de registros en cuarentena. Confirmar incorpora original, manifiesto y A1 derivado con la transacción y verificaciones existentes. Renombrar el archivo no duplica la captura. No comienza análisis ni aprueba vínculos.

- Se exige total declarado coincidente y órdenes no vacías/únicas (presencia y duplicados comparados sin espacios exteriores, original conservado); ante duplicidad se rechaza interpretar el archivo, conservando original.
- Solo órdenes de imágenes y capturas `usable` / `Si`, sin advertencias y con afiliado. Las demás se muestran en cuarentena, sin participar en correspondencias. Una captura sin registros utilizables no se importa como evidencia vacía.
- `fecha_orden` ISO debe coincidir con `fecha_orden_original` día/mes/año. No representa fecha de prestación, autorización ni incorporación al consolidado.
- Las prácticas se separan por el patrón observado `código de diez dígitos  --  descripción,`. Las comas dentro de las descripciones no son separadores por sí solas. Se conservan códigos completos y textos monetarios, sin inferir cantidades o precios. No se admite el formato si faltan comienzo o terminador reconocibles; segmentos con aspecto de código/separador que no cumplen el contrato llevan toda la fila a cuarentena, nunca se absorben silenciosamente como descripción. Los códigos repetidos se conservan y requieren revisión.
- `movimientos` queda íntegro como texto en una resolución de alcance desconocido. No se extraen de texto libre aprobaciones por práctica, estados efectivos, cantidades ni precios autorizados. Historial, médico, diagnóstico y demás detalles permanecen en el original privado. El A1 no duplica datos clínicos que no necesita.
- `csv_record` es posición lógica del registro CSV (cabecera=1), no número físico de línea: una celda puede contener saltos de línea.
- Cobertura siempre parcial/no verificada. La última fecha de captura UTC no implica captura única ni exhaustividad. El total de órdenes del archivo no acredita que abarque toda la plataforma.
- Flujo por rango de fechas observadas; exportaciones con rangos diferentes son flujos diferentes y deben seleccionarse explícitamente. No se fusionan para concluir cobertura completa.

## Correspondencia

Los códigos de plataforma de diez dígitos no se recortan para coincidir con códigos de otro sistema. Requieren correspondencia/equivalencia documentada cuando no hay igualdad completa. Coincidir afiliado, descripción o fecha no acredita por sí solo autorización individual. La ausencia de una orden/práctica en esta captura parcial no prueba falta de autorización.

## Pruebas

`tests.test_hpc_csv_intake` usa exclusivamente registros inventados: formato, cuarentena visible, fechas discrepantes, duplicados, códigos completos/repetidos, comas, API, original inmutable, confirmación y repetición idempotente. La inspección real y sus agregados quedan fuera del código y paquete. No se realizó comprobación visual de navegador ni instalación Windows de este incremento.
