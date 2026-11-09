# B18-R27 · Versión de entrega del prototipo HPC

La prueba de Windows abrió una factura nueva desde el Excel y el CSV ficticios. Se confirmó el alcance HPC de esa factura con el administrador y se ejecutó el análisis desde la aplicación. El administrativo vio dos TAC del mismo paciente, ordenadas por fecha, en la bandeja de Imágenes. La del 02/08 mostró $450.000 facturados, $200.000 de presupuesto y $250.000 a revisar. Se verificaron las cuatro decisiones, el motivo requerido para las alternativas y el paso de la primera TAC a Revisadas al guardar. La segunda TAC del 04/08 conservó la referencia a la realización que había usado el aval. El CSV ficticio completo permitió proponer $450.000 por esa fila. El cierre administrativo entregó ambas decisiones por $700.000 y bloqueó la edición administrativa.

Con la cuenta de auditor se ajustó la primera TAC a $200.000, se verificó el neto de Imágenes de $250.000 y se confirmó el cierre por $650.000. Chrome descargó el Excel. Se abrió con openpyxl y se comprobaron las dos filas, los valores numéricos y el motivo final de la primera. Al recargar se conservó el cierre y desapareció la acción de confirmar. El resultado de ejemplo queda en la carpeta de resultados del navegador. La demo de presentación queda al inicio con cero decisiones, pases y cierres. Es una prueba técnica con identidades ficticias. Queda la aceptación del operador.

### Revisión para la mesa examinadora

La revisión documental de R27 aclara el primer inicio en una PC nueva, actualiza el enlace al manifiesto y describe el prorrateo por unidades sin aval. El iniciador usa el entorno de esta copia o el intérprete indicado en TFG_BROWSER_PYTHON. El esquema y las reglas evaluadas corresponden a R27.

### Cotejo del lote de agosto

Se verificaron localmente el hash de la facturación y del CSV, la interpretación del CSV y la fuente HPC del lote. Sobre una copia independiente de la validación privada se registró, mediante el servicio del administrador, la correspondencia dirigida 187013 → 1870130000, de una unidad por estudio. La evidencia procede de la práctica individual del catálogo HPC. Dos ítems distintos cubrieron las dos unidades de una fila que pasó de pendiente a cubierta. La correspondencia se registra para esa fuente. No se incorporó un alias global por prefijo. La comparación reproducida en memoria y la lectura de la base privada nueva dieron el mismo resultado.

| Resultado excluyente | Prestaciones | Lectura administrativa |
| --- | ---: | --- |
| En término, completamente cubiertas por aval | 154 | 150 principales y 4 adicionales. La autorización por sí sola no acredita precio ni RN10. |
| En término, afiliado no identificable | 3 | Propuesta total de $57.855,74 en conjunto, para decisión humana. |
| En término, cantidad con importe por verificar | 11 | Diez parciales y un total teórico, $286.481,14 en conjunto. El CSV no acredita la ausencia de otro aval. |
| En término, demás casos a cotejar | 295 | 108 sin coincidencia suficiente en la fuente, 74 adicionales que requieren estudiar el principal o la unidad, 104 con movimientos de orden a interpretar y 9 con identidad de práctica o cantidad ambigua. |
| Fuera de término | 9 | Propuesta por plazo de $184.571,48 en conjunto. Para agosto, el 17/07 entra y el 16/07 queda fuera. |
| Total | 472 | 463 en término. Cero decisiones reales guardadas. |

La comprobación recorrió todas las páginas de Imágenes, concilió las filas con los originales, verificó las unidades asignadas a 167 ítems distintos y comprobó por separado la capacidad de los adicionales. Ningún ítem superó su cantidad autorizada. La copia privada contiene cinco registros CSV en cuarentena y carece de declaración de cobertura completa. Una resolución posterior sigue como movimiento a cotejar, con ID y fechas. Los PDF clínicos y su asociación automática continúan diferidos.

### Reproducción y alcance de las comprobaciones

Desde fuentes y con el Python del proyecto:

- `python -B scripts/verify_r25.py --entrega`. Windows, 180 ejecuciones de prueba Python (168 identificadores distintos), todas aprobadas. Hay clases de fixture que el cargador descubre más de una vez. Se cubrieron la importación, el presupuesto, las cantidades, movimientos posteriores, correcciones, versiones, autorizaciones, vigencia, pase, ajuste y cierre. Un ensayo previo detectó que la prueba de capturas antiguas omitía RN19 entre las reglas afectadas por la versión. Se verificó esa expectativa contra la regla de 45 días y se repitió la selección. La suite histórica completa, incluido el caso que requiere Git, no formó parte de esta corrida.
- `node --test tests/web_*.test.cjs`. 159 pruebas aprobadas. Una prueba nueva incluye el texto de revisión y el importe orientativo con CSV parcial.
- `node tests/r27_delivery.cjs` con TFG_BROWSER_PYTHON apuntando al Python del proyecto. Chrome en Windows usa una copia descartable de la demo, un puerto local libre y descarga dentro de esa copia. En la primera pasada se identificó que el conjunto vacío de la fixture carecía del código de la TAC. Se completó el catálogo ficticio de esa carga. También se bloqueó la edición de la planilla mientras se actualiza, para que una fila vieja no pueda abrirse durante la transición.
- `python -B -m scripts.check_r27_imaging --validacion RUTA_PRIVADA_ORIGEN --csv RUTA_CSV` verifica las 472 y el consumo por ítem en memoria. La opción `--guardar-copia-privada NUEVO_DIRECTORIO_PRIVADO` prepara un destino exclusivo, registra la correspondencia, comprueba integridad y vuelve a verificar sus resultados. Entrega únicamente agregados. No hay acceso a sistemas institucionales.

Principales cambios en app/csv_rules.py, csv_components.py, row_decisions.py y practice_board.py, la planilla y la carga en web/, las fixtures y pruebas R27, el iniciador local, la guía y este estado. Se mantiene el esquema 42. El alcance y la regla explícita de 45 días respecto del TP anterior se consultan en [Decisiones](DECISIONES.md). El recorrido reproducible está en [la guía de R27](../GUIA-DEMO-R27.txt).

## Antecedente B18-R26 · Plazo de facturación HPC

Decisión del 09/11/2026. La fecha del Excel se compara con el último día del período confirmado del lote. Hasta 45 días inclusive está en término. Una fila ambulatoria anterior al límite permanece en la planilla para su revisión. RN19 informa las fechas y los días transcurridos. Para una prestación de Imágenes HPC con total positivo, la propuesta por plazo es el importe de la fila una sola vez, incluso si concurren otros motivos. La decisión administrativa, el pase y el cierre del auditor conservan sus permisos e historial. La fecha de autorización y la de incorporación al consolidado corresponden a controles distintos. La decisión de R26 que amplía el TP escrito está registrada en [Decisiones](DECISIONES.md).

En la verificación de agosto, las 357 imágenes del cotejo R25 (01/08 a 25/08) quedaron en término. Al revisar todas las filas originales aparecieron otras 115 imágenes antes excluidas por mes. De ellas, 106 están en término y 9 fuera de término. La planilla mostró 472 imágenes en revisión, 463 en término por fecha y 9 con un total de ARS 184.571,48 propuesto por plazo. El filtro de pendientes devolvió las mismas nueve filas. La verificación reutilizó la validación R25 en solo lectura y trabajó en memoria. Son resultados del plazo de presentación, no una nueva validación de las autorizaciones ni un cierre económico.

En la demo de agosto, la TAC del 17/07 entra a los 45 días. La TAC del 16/07 entra en el filtro **Facturación fuera de término**, aunque esté autorizada. Pasaron 46 días. El importe de $100.000 corresponde a toda la fila con cantidad dos. No se guarda decisión hasta la intervención del operador. Se verificaron la aceptación ficticia, el traslado a Revisadas y el total sin duplicar. En Chrome se comprobó el importe, el fundamento del detalle y el filtro. La demo preparada queda sin decisiones, separada de los datos de validación.

Reproducción desde `fuentes` con el entorno aislado del proyecto:

- `python -B scripts/verify_r25.py --plazo` ejercita importación, elegibilidad, controles, planilla, decisiones, pase, cierre y regresiones de autorizaciones. Pasaron 64 pruebas Python seleccionadas y 158 pruebas web JavaScript, sin fallos ni omisiones en la ejecución final. El primer ensayo sintético había usado una única orden para dos fechas de realización. Se reemplazó por dos órdenes independientes para que ambas TAC tengan aval y la prueba mida únicamente el efecto del plazo.
- `python -B -m scripts.create_r25_demo --plazo` prepara la demo en una copia nueva. En esta entrega ya está preparada. `node tests/r25_presentation.cjs --plazo` reproduce el recorrido en Chrome Windows con `TFG_BROWSER_PYTHON` apuntando al Python del proyecto. El ensayo usa un duplicado descartable de esa demo y un servidor temporal en loopback.
- `python -B -m scripts.check_r26_dates --validacion-r25 RUTA_PRIVADA_R25` verifica la cohorte previa, todas las imágenes de la planilla y el filtro de plazo. Devuelve solo agregados. La base de origen debe ser una validación finalizada con su informe de filas correspondiente.

Archivos principales: `app/eligibility.py`, `app/invoice_x1.py`, `app/controls.py`, `app/practice_board.py`, `app/row_decisions.py`, la planilla y detalle en `web/`, y `tests/test_r26.py`. Se conserva el esquema 42. No se realizó aceptación con un operador ni se ejecutó la suite histórica completa.

## Antecedente B18-R25 · Autorizaciones y propuestas de revisión HPC

Copia separada de R24, esquema 42. La demo ficticia se prepara con scripts/create_r25_demo.py y se abre con ABRIR-DEMO.cmd. El guion está en [GUIA-DEMO-R25.txt](../GUIA-DEMO-R25.txt).

El CSV registra la última decisión individual identificable. Las autorizaciones de varias prácticas conservan sus unidades. Los precios sin atribución individual quedan pendientes. Se asigna un aval previo vigente por orden de vencimiento entre órdenes equivalentes y se registra su ID y consumo. Una orden posterior se muestra como candidata para el administrativo, con fechas e importe si está documentado. La reasignación consume una sola vez, comprueba versiones y permisos y reabre la fila que perdió el aval. Una derivación a otro prestador o un rechazo por un aval anterior que no aparece requieren CSV completo para proponer el total. La falta de identificación del afiliado se evalúa de forma independiente. El plazo RN10 se comprueba por fila usando la fecha de incorporación de las filas que el comprobante identifica. Una propuesta administrativa no confirma el débito institucional.

Archivos de dominio principales: app/csv_movements.py, hpc_csv_resolutions.py, hpc_csv_adapter.py, csv_rules.py, csv_actions.py, csv_coverage.py, csv_components.py, csv_budget.py, csv_export.py y authorization_assessment.py. Integración en app/api.py, db.py, authorization_matching.py, practice_board.py, row_decisions.py y web/row_decision.js, workbench.js y sheet_actions.js.

Validación sobre una base privada nueva: 357 filas de Imágenes incluidas; ARS 14.371.657,67 facturados. Pasaron de 83 a 110 con aval (108 principales y 2 adicionales); 27 ganaron cobertura y ninguna la perdió. Otras 3 tienen propuesta total por afiliado no identificable. Quedaron 244 pendientes de cotejo. Se preservaron las 165 reglas de prueba R24 y los hashes de los originales. No se certificó completitud del CSV real ni se guardaron decisiones administrativas. El informe agregado y la comparación por transición quedan junto a la base privada.
 
Reproducción: python -B scripts/verify_r25.py para la selección sintética. tests/r25_presentation.cjs comprueba la reasignación y el comprobante en Chrome contra una copia descartable de la demo. scripts/validate_r25_local.py exige un directorio privado vacío y la referencia R24 en lectura. scripts/compare_imaging_runs.py vuelve a calcular en modo de lectura cada versión con su motor y exige igualdad de factura, CSV y filas. Pendientes de validación externa: alcance de las derivaciones, unidades y proyecciones sin respaldo, período completo de exportación y aceptación con operadores.

Comprobaciones de R25 en Windows: 160 pruebas Python de la selección, 158 JavaScript, cero fallidas u omitidas. En Chrome se verificaron la propuesta de $100.000, el ID y las fechas de la TAC, la transferencia del aval y el registro grupal de incorporación. La validación fue técnica y con datos ficticios para la interfaz.

## Antecedente B18-R24 · Correspondencias, adicionales y unidades

Se preparó una copia separada de B18-R23. El [guion de la demo](../GUIA-DEMO-R24.txt) describe el conjunto de mamografía y radiografía. `ABRIR-DEMO.cmd` inicia la base ficticia `.tmp/presentacion-R24` en un puerto libre de loopback.

## Implementado y comprobado

- El administrador registra y retira relaciones verificadas. Cada versión conserva cuenta, fecha, fundamento, fuente, localizador, tipo y unidad. El guardado de un conjunto de cambios es indivisible y exige versión vigente. El administrativo y el auditor consultan las reglas. El servidor rechaza escrituras de revisión sin función administradora.
- Las relaciones distinguen misma práctica, familia de variantes, adicional y atributo de la orden. Cada fila conserva su código original. Una familia permite buscar variantes compatibles. Los códigos completos de dos variantes diferentes conservan identidades propias al asignar autorizaciones.
- Las cantidades se asignan en unidades del estudio autorizado. La regla documentada de mamografía por lado convierte un estudio bilateral en dos lados. Se mantiene una sola disponibilidad de la autorización entre filas, fechas y facturas.
- Los adicionales se relacionan con un único principal de la misma factura, orden, afiliado y fecha. Las exposiciones requieren una cantidad documentada. «Frente y perfil» aporta dos exposiciones cuando la orden tiene un único estudio principal, aunque el atributo aparezca antes del estudio en el CSV.
- Una orden con varios estudios y atributos sin una relación explícita mantiene pendiente la cantidad del adicional. Las áreas subsiguientes conservan su unidad y requieren aclaración de su alcance. El enlace esófago/videodeglución se excluyó de las propuestas para equivalencia directa.
- La comparación monetaria conserva los importes de fila del Excel. La conversión de unidades de autorización conserva el presupuesto como total, sin multiplicar nuevamente lo facturado. Los adicionales pendientes conservan pendiente su propuesta por ausencia de aval.
- Las reglas forman parte de las dependencias y del historial exportado. Cambiar una regla actualiza el cotejo al refrescar y puede invalidar decisiones dependientes. Los controles versionados conservan su mecanismo de reanálisis explícito.
- El esquema nuevo es 41. Se utilizaron bases nuevas. Una base anterior requiere el mecanismo existente de respaldo coherente y migración fuera de línea. La historia antigua se conserva. Las relaciones antiguas incompatibles con el tipo o la unidad actual requieren confirmación.

## Cruce real reproducido

La validación final utiliza exclusivamente la base nueva `%LOCALAPPDATA%/TFG-HPC-Privado/R24-validacion-20261109-final/datos/app.sqlite3`. Los informes agregados están en su directorio superior. La primera ejecución preliminar está separada en `R24-validacion-20261109`.

Se incorporaron los originales mediante los mecanismos del proyecto y se registraron las reglas derivadas del cuadro cotejado el 09/11. El proceso comprueba la base destino, bloquea comunicaciones y subprocesos y verifica los hashes de los originales. El Excel tiene 26.038 filas, 13.005 incluidas, 357 de Imágenes por ARS 14.371.657,67.

| Estado de autorización y unidades | Cantidad |
|---|---:|
| Prestaciones principales con aval y cantidad cubierta | 81 |
| Adicionales con aval del principal y exposiciones acreditadas | 2 |
| Rechazo individual atribuible | 0 |
| Ausencia de aval con cobertura completa de exportación comprobada | 0 |
| Pendientes | 274 |
| Total | 357 |

Los 274 pendientes comprenden 87 casos sin cobertura de exportación suficiente para concluir ausencia de aval, 83 correspondencias o asignaciones ambiguas, 41 situaciones temporales, 61 adicionales con principal o cantidad por aclarar y 2 coberturas parciales de cantidad.

La comparación de salida automática pasa de 33 renglones en R23 a 83 en R24. R24 incorpora las familias y unidades y revisa los enlaces que el cuadro identificó como inadecuados. Los 83 renglones corresponden a 81 estudios principales y dos adicionales. Cada adicional comparte el respaldo de su principal y conserva su cantidad propia.

Se registraron 165 reglas en la validación local, con su respaldo. Hay 122 relaciones de familia, 16 directas, 7 reglas de componentes y 20 atributos de órdenes. Son declaraciones locales para este cotejo administrativo de HPC. La referencia económica y las condiciones específicas conservan su comprobación por prestación.

Una verificación independiente en lectura reprodujo los 357 estados, comprobó que las asignaciones no exceden las cantidades de sus fuentes, que una autorización no se reutiliza en otra ocasión y que los dos adicionales acreditados señalan un principal con el mismo respaldo. Los originales conservaron sus hashes. Hay cero decisiones humanas sobre las prestaciones reales.

El CSV conserva su cobertura incompleta. Para evaluar la ausencia de aval del conjunto se necesita acreditar una exportación desde el 02/06/2026. La fecha de incorporación al consolidado sigue siendo necesaria cuando RN10 requiere establecer la secuencia temporal.

## Pruebas ejecutadas

- Python en Windows con el ejecutor protegido. La selección final pasó 152 pruebas, con cero fallos, errores u omisiones. La selección focalizada pasó 35 y comparte casos con la principal. Resultados en `.test-results-r24/python-summary.json` y `.test-results-r24-nuevo/python-summary.json`.
- JavaScript del proyecto. Pasaron 158 pruebas, con cero fallos u omisiones.
- Chrome local, en una copia ficticia descartable. `tests/r24_presentation.cjs` verificó el cierre del auditor, dos decisiones, Excel/PDF, nueva revisión y presupuesto de la eco, además de las correspondencias, retirada e historia, dos lados cubiertos por un estudio, no reutilización en la segunda mamografía y adicional con proyecciones documentadas. El administrativo pudo consultar sin controles de escritura. El servidor temporal se cerró al finalizar.
- Se corrigió la apertura prematura del panel de correspondencias durante el cambio de conjunto. Su botón espera la carga de la fuente y la prueba de navegador pasó desde el botón normal.
- La demo preparada conserva cuatro conjuntos ficticios y cero decisiones. Las escrituras de la prueba de navegador se realizaron en su duplicado.

Para reproducir se utiliza el entorno existente con `python -B scripts/verify_r24.py`, `python -B scripts/verify_r24.py --nuevo` y las pruebas `*.test.cjs`. El guion de Chrome requiere `TFG_BROWSER_PYTHON` y Chrome o Edge. El validador `scripts.validate_r24_local` exige un destino privado vacío y rutas de insumos locales autorizados.

## Archivos y límites

Los módulos nuevos son `app/hpc_correspondence_catalog.py`, `app/csv_allocation.py` y `app/csv_components.py`. Se modificaron las correspondencias, las dependencias de autorizaciones, el cotejo CSV y de presupuestos, la bandeja, las decisiones, la API y el esquema. La interfaz añade tipos y unidades al panel de correspondencias y al detalle. Se añadieron pruebas, validador y guiones de demo de R24.

Quedan pendientes la aceptación con operadores, las correspondencias sin respaldo suficiente, la resolución de las ambigüedades y las fuentes temporales faltantes. La suite histórica completa y una nueva medición de rendimiento no se ejecutaron. La asociación automática de informes médicos y OCR conserva el alcance diferido.

---

# B18-R23 · Correspondencias y decisiones del CSV de HPC

La copia R23 está separada de R22. La demo ficticia utiliza `.tmp/presentacion-R23`. El arranque se realiza con `ABRIR-DEMO.cmd` y el [guion de uso](../GUIA-DEMO-R23.txt). El servidor de presentación escucha únicamente en loopback.

## Comportamiento incorporado

- El administrador registra y retira correspondencias específicas entre los códigos completos del Excel y del CSV. El registro conserva el catálogo, su hash, las secuencias de códigos, el motivo, la cuenta y la historia. Se reutiliza en las facturas HPC del mismo conjunto y fuente.
- La lectura v6 reconoce una decisión fechada de la plataforma sobre los ítems listados. Una aprobación sin salvedades cubre la cantidad de cada ítem de la orden. Un comentario detallado en una orden con varias prácticas requiere delimitar el alcance. Las derivaciones y las contradicciones quedan identificadas.
- La asignación agrupa los códigos confirmados como una misma identidad para comprobar las unidades y las ocasiones. Una orden consumida por un código conserva su consumo cuando aparece otra factura o el código equivalente.
- La presencia en el CSV se muestra como Hallada cuando la correspondencia registrada permite identificar la práctica. El estado de autorización y el precio tienen columnas propias.
- La interpretación anterior del CSV permanece histórica. El lector solicita la reinterpretación explícita de las capturas afectadas. Se utilizaron bases nuevas de esquema 40 para esta entrega.
- El catálogo específico respalda las correspondencias de este incremento. Las categorías amplias y las coincidencias por prefijo requieren cotejo documental. La pantalla incluye únicamente los pares con vínculo específico verificable del catálogo.
- Se conservan los controles económicos, la decisión humana por prestación, las revisiones, los permisos, el pase administrativo y el cierre del auditor. La historia de correspondencias se incluye en las capturas exportadas.

## Validación nueva con datos reales

La base privada nueva está en `%LOCALAPPDATA%/TFG-HPC-Privado/R23-validacion-20261108/datos/app.sqlite3`. El informe agregado está en su directorio superior. El proceso comprueba el destino antes de las operaciones, bloquea comunicaciones y subprocesos, y verifica los hashes de los originales al terminar. El ensayo utiliza 26.038 filas originales, 13.005 incluidas, 357 de Imágenes por ARS 14.371.657,67.

| Resultado de autorización por prestación | R22 | R23 |
|---|---:|---:|
| Cobertura completa reconocida | 0 | 33 |
| Rechazo individual atribuible | 0 | 0 |
| Falta de aval con cobertura de exportación comprobada | 0 | 0 |
| Pendientes | 357 | 324 |

Los pendientes de R23 comprenden 3 prestaciones con cobertura parcial de cantidad, 8 con evidencia temporal por aclarar, 6 con correspondencia registrada y asignación o resolución ambigua, 156 con candidatos por prefijo sin correspondencia específica registrada y 151 sin candidato por afiliado y prefijo.

Se registraron 17 pares específicos respaldados por la identidad compartida del catálogo original. Los 16 que aparecen entre los candidatos de la factura y el CSV aportado abarcan 50 prestaciones. El registro adicional carece de candidato utilizable en ese cruce. Se trata de un cotejo administrativo local de códigos, con fuentes conservadas. Las declaraciones de moneda, unidad, vigencia económica y condiciones se verifican de forma independiente.

Una comprobación independiente en lectura reprodujo los 357 estados y comprobó que las 33 prestaciones con cobertura completa utilizan 33 autorizaciones distintas. Se conservaron los originales y se registraron cero decisiones humanas sobre el lote real. La cifra de 33 describe el reconocimiento de autorización y cantidad. Las decisiones sobre diferencias monetarias requieren el recorrido humano.

El CSV aporta solicitudes entre julio y agosto. Para evaluar la ausencia de aval de todas las prestaciones se necesita una exportación con cobertura comprobada desde el 2/6/2026. RN10 compara autorización e incorporación al consolidado. Las situaciones que requieren esa fecha permanecen pendientes.

## Pruebas y límites

Pasaron 140 pruebas Python de la selección funcional y 158 JavaScript. Después se ejecutaron 23 pruebas focalizadas en el nuevo comportamiento, incluidas las declaraciones individuales anteriores. Las selecciones comparten casos. La ejecución final se registra en `.test-results-r23/python-summary.json` y la focalizada en `.test-results-r23-nuevo/python-summary.json`.

La prueba `tests/r23_presentation.cjs` utilizó un duplicado ficticio y Chrome local. Verificó dos decisiones, cierre del auditor, Excel/PDF, nueva revisión, presupuesto exclusivo para la eco, reconocimiento de la primera TAC con códigos distintos, consumo de su aval, gestión de correspondencias y actualización de la planilla al retirar una. Cerró el servidor temporal. La demo de presentación conserva cero decisiones y cero cierres.

Para reproducir se utiliza el entorno existente con `python -B scripts/verify_r23.py`, `python -B scripts/verify_r23.py --nuevo` y las pruebas JavaScript del proyecto. La prueba de navegador requiere `TFG_BROWSER_PYTHON` y Chrome o Edge. La validación real se ejecuta con `scripts.validate_r23_local`, una carpeta privada nueva y las fuentes locales autorizadas.

Se modificaron `app/hpc_csv_resolutions.py`, `app/hpc_csv_adapter.py`, `app/authorization_matching.py`, `app/csv_coverage.py`, `app/db.py`, `app/api.py`, `app/provisional.py`, `web/app.js` y `web/index.html`. Se añadieron `app/code_correspondences.py`, `web/code_correspondences.js`, las pruebas de R23, el validador, el generador y el iniciador de su demo. Las dos expectativas de importación CSV anteriores se actualizaron a la regla del usuario sobre aprobación de los ítems listados.

La suite histórica completa y la aceptación por operadores quedan pendientes. El rendimiento de R22 documentado abajo corresponde a su medición anterior. La asociación automática de informes médicos y OCR sigue diferida.

---

# B18-R22 · Entrega del recorrido de Imágenes HPC en Windows

Demo local: [guion de presentación](../GUIA-DEMO-R22.txt) y [ABRIR-DEMO.cmd](../ABRIR-DEMO.cmd). La base ficticia está en `.tmp/presentacion-HPC`. Hay dos conjuntos independientes, uno con las TAC y otro con ecografía y resonancia. El servidor usa únicamente 127.0.0.1. La selección de fuentes y el análisis de una revisión se confirman expresamente.

| Requisito | Caso verificado | Resultado |
|---|---|---|
| Cantidad y ocasión | Dos TAC juntas, otra fecha, dos órdenes distintas, CSV parcial y límites de 60/61 días | 2 de 2 autorizadas en la misma ocasión. Las unidades sobrantes no pasan a otra fecha. Con una sola unidad para dos facturadas por $200.000 se proponen $100.000 cuando la extracción cubre el período. Una coincidencia ambigua no consume unidades. |
| Fechas | Prestación 2/8, autorización 3/8 y consolidación 4/8, ausente, anterior o del mismo día | Se reconoce la secuencia válida. Sin precisión suficiente queda pendiente. Una autorización posterior al consolidado queda observada. Se comprueban horas comparables y no se completa la hora de una fecha. |
| Presupuestos | Orden mixta del mismo afiliado, con resonancia en convenio y eco por presupuesto | El operador registra el total de la eco y su respaldo. En pantalla figuran $120.000 de convenio para la resonancia y $250.000 a revisar para la eco ($450.000 menos $200.000). Los importes no se distribuyen. Un presupuesto explícitamente total para dos unidades se usa una sola vez. |
| Bandeja | Pendientes de Imágenes, motivo, prioridad y monto antes de paginar; Abrir planilla después de recibir los archivos | La factura abre desde la lista según función. Excel/CSV se preparan en una pantalla. La selección del CSV no acredita exhaustividad. La factura completa es de consulta. El administrador tiene acceso a solicitudes desde la lista. |
| Decisión y cierre | Copia de la demo, con dos TAC: propuestas de $250.000 y $450.000. El auditor ajusta la primera a $200.000 | Una decisión por prestación. Dos decisiones al pase, cierre por $650.000, neto de Imágenes $250.000. Excel con dos prestaciones, orden, importe y motivo. PDF de cierre y nueva revisión del mismo Excel sin sobrescribir el cierre anterior. |
| Reportes | Informe provisional, informe cerrado, varias páginas, acceso revocado, descarga histórica | El reporte de observaciones se elabora desde la captura de revisión. El Excel se descarga con la función auditora. Los informes médicos, su asociación automática y OCR siguen diferidos. |

El pase administrativo permanece bloqueado mientras haya prestaciones de Imágenes pendientes en cualquier página o filtro. El cierre del auditor conserva el respaldo en una transacción. Si llega evidencia nueva, un usuario administrativo habilitado inicia otra revisión. Las filas originales se comparten, las decisiones previas quedan históricas y campos, fuentes y vínculos requieren reconfirmación. Para los cierres de Imágenes creados antes de R22 se utiliza únicamente el recibo histórico conservado; lo que no se capturó entonces queda identificado.

## Resultado del cotejo local con fuentes reales

Período agosto de 2026. El Excel incorporado contiene 26.038 filas, 13.005 dentro del alcance del período, 357 de Imágenes, facturadas por $14.371.657,67. La clasificación usa los mecanismos de R22. Se verificó la interpretación del CSV contra su original. Las fuentes conservaron sus hashes. El análisis usa la nueva base privada fuera del repositorio; no se incorporó material real en las pruebas, la demo, el historial del proyecto ni este informe.

| Estado por prestación | Cantidad |
|---|---:|
| Autorización acreditada para esa fila | 0 |
| Rechazo acreditado para esa fila | 0 |
| Sin aval con cobertura comprobada | 0 |
| Pendiente de cotejo | 357 |

El recuento corregido encontró 206 filas con afiliado identificable, prefijo de seis dígitos y fecha de solicitud dentro de los 60 días previos. En 151 filas faltó esa coincidencia. El primer resumen histórico había contado una fila de más al agrupar dos identificaciones no interpretables. Ninguna fila tuvo coincidencia por afiliado y código completo en la interpretación seleccionada.

Dentro de las 206 prestaciones hay 80 pares distintos entre el código facturado de seis dígitos y el de diez del CSV. En 50 prestaciones el catálogo declara un vínculo específico (16 pares distintos). En 104 solo declara una categoría amplia y en 52 no se halló un vínculo declarado entre los candidatos. En las 154 prestaciones con vínculo de catálogo, el lector actual no extrajo una resolución individual de autorización o rechazo para los ítems candidatos examinados. Un candidato se cuenta aunque la misma orden aparezca en varias búsquedas. Estos recuentos describen el trabajo de cotejo, sin consumir unidades ni decidir prestaciones.

El CSV tiene 2.531 líneas físicas sin el encabezado, correspondientes a 2.475 registros lógicos, de los cuales se incorporaron 2.470 órdenes. Los registros restantes se conservan en el original. Las fechas de orden observadas van del 1/7 al 31/8. Las prestaciones de Imágenes van del 1/8 al 25/8; para cubrir retrospectivamente todas se necesitan resoluciones desde el 2/6 y evidencia de exhaustividad. Si se evalúa una autorización posterior a la prestación también hace falta acreditar su relación temporal con el consolidado. No se registraron decisiones humanas sobre la factura real.

## Verificación y límites

- Pasaron las 127 pruebas de la selección principal de Python y las 22 de la selección complementaria. Ambas terminaron sin fallos ni omisiones y comparten algunos casos. La complementaria incluye otra factura con prestador sin confirmar que utiliza el mismo CSV. El resultado está en `.test-results-r22-cierres/python-summary.json`. Pasaron las 158 pruebas JavaScript, sin fallos ni omisiones.
- Navegador Windows: `tests/r22_intake.cjs` comprueba entrada de Excel y CSV y la vista del administrador. `tests/r22_presentation.cjs` utiliza un duplicado de la demo, con las dos cuentas de revisión, descarga de archivos, nueva revisión y vinculación de presupuesto. Se abrió y leyó el Excel, y se leyó y renderizó el PDF ficticio. El caso de varias páginas se verifica por separado. Artefactos en `.test-results-r22`.
- Rendimiento en Chrome con 13.000 filas ficticias, 357 de Imágenes, 100 órdenes CSV y catálogo HPC. Apertura 4,82 s. Mediana de 20 cambios de filtro 1,26 s, máximo 1,58 s (20/20 dentro de 2 s). Guardar y seguir 3,28 s. El contador pasó de 357 a 356 y se abrió otra prestación. Detalle en `.test-results-r22/volumen.json`. La apertura inicial y el guardado llevan más de dos segundos. No se certificó el objetivo de consultas en dos sesiones simultáneas.
- Para reproducir en fuentes con el entorno del proyecto: `python -B scripts/verify_r22.py`, `python -B scripts/verify_r22.py --cierres`, y en PowerShell `node --test (Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object FullName)`. Los guiones de Chrome requieren `TFG_BROWSER_PYTHON`. La base ficticia de volumen se genera una vez mediante `python -B -m scripts.create_review_journey_demo --volumen --name medicion-final-13000`.
- Archivos principales: `app/csv_coverage.py`, `app/csv_item_quantity.py`, `app/csv_budget.py`, `app/image_budgets.py`, `app/practice_board.py`, `app/board_projection.py`, `app/invoice_audit.py`, `app/image_reports.py`, `app/revisions.py`, `app/api.py`, `app/db.py`, `web/invoice_home.js`, `web/workbench.js`, `web/row_decision.js`, `web/invoice_audit.js` y `web/revisions.js`. El esquema nuevo es 39. Una actualización de bases anteriores requiere el procedimiento existente de respaldo y migración fuera de línea. Se utilizaron bases nuevas.
- No se ejecutó la suite histórica completa ni una prueba de aceptación con operadores. El porcentaje de ahorro de trabajo, la sensibilidad y la precisión siguen pendientes de medición con una referencia independiente. R22 está preparada para la demostración. La correspondencia de los códigos de la factura real con los códigos de órdenes sigue pendiente de documentación.

---

# B18-R18 · Cerrar y pasar al auditor

La planilla muestra «Cerrar y pasar al auditor» a la cuenta administrativa. Se habilita cuando el recuento de Imágenes de toda la factura llega a cero pendientes. El servidor vuelve a comprobar la evidencia, el estado de la revisión, las versiones y los permisos al confirmar. El buscador, la página seleccionada y los filtros por motivo no reducen ese recuento. La revisión requiere clasificación HPC verificable y un análisis terminado para ofrecer un recuento de cierre.

El pase guarda la versión de cada decisión de Imágenes, incluido «Sin débito», su motivo y los datos de la prestación. Se confirma en una sola transacción. Un reintento de la misma operación devuelve el mismo comprobante. La cuenta administrativa queda con acceso de consulta. La cuenta con función de auditor ve «Facturas recibidas» para su conjunto, la suma de los débitos administrativos y las decisiones con fecha, orden, práctica, importe y motivo. Una factura ya recibida sigue mostrando la versión de la decisión que se entregó.

Para probarlo en Windows, usar la demo nueva de esta copia en `.tmp/demo-r18-pase`. Ingresar como demo-administrativo, aceptar los $250.000 de la TAC del 02/08, elegir «Sin débito» con motivo para la del 04/08 y confirmar «Cerrar y pasar al auditor». Cerrar sesión e ingresar como demo-auditor. La factura aparece con dos decisiones y $250.000 de débito administrativo. El ajuste final por el auditor, el cierre definitivo y el Excel son la siguiente etapa.

En Windows pasaron 43 de 43 pruebas Python seleccionadas y 158 de 158 pruebas JavaScript, sin omitidas. En Chrome se verificaron el bloqueo del cierre con una TAC pendiente, el pase con ambas decididas, la consulta posterior del administrativo y la recepción por el auditor. La prueba mixta confirmó que una observación pendiente de Laboratorio no impide el pase. La demo preparada quedó con dos filas, cero decisiones y cero pases.

El esquema 36 añade los comprobantes de pase y las filas entregadas. Solo se usaron bases nuevas y ficticias. Para repetir la selección Python desde fuentes, ejecutar `python -B scripts/verify_r18_handoff.py`. Para JavaScript, ejecutar `node --test (Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object FullName)` en PowerShell. Con `TFG_BROWSER_PYTHON` apuntando al ejecutable del entorno, `node tests/r18_browser_smoke.cjs` verifica el recorrido de las dos cuentas en una demo aparte. El servidor de prueba se cierra al terminar.

---

# B18-R17 · Decisión administrativa por prestación

En Imágenes, cada fila pendiente abre las cuatro opciones debajo de la prestación. Aceptar usa el importe y el fundamento calculados en el servidor. Parcial requiere un importe mayor a cero y menor al facturado. Parcial, total y sin débito requieren motivo. Una corrección exige motivo y conserva la versión anterior con su autor. La pestaña Revisadas permite abrir la decisión y corregirla mientras la revisión está abierta.

«Guardar y seguir» registra la decisión y abre la siguiente pendiente del filtro. En la demo, la primera TAC tiene $450.000 facturados y un presupuesto de $200.000. Aceptar guarda $250.000 y abre la TAC del 04/08. Al revisar la última, la planilla informa que terminó esa vista. «Dejar pendiente y seguir» permite avanzar sin registrar una decisión. La historia identifica las correcciones.

El esquema 35 incorpora las versiones de decisiones por revisión y fila y la asignación de la función administrativa por conjunto. El servicio de permisos acepta el campo opcional `invoice_duty` con `administrative` o `auditor` para colaboradores con rol reviewer. La demo asigna ambas cuentas. La aplicación revalida el permiso, la revisión abierta, la versión de datos y la evidencia. Si cambia el respaldo de la decisión, la fila vuelve a Pendientes. Las decisiones de este bloque pertenecen a la revisión administrativa y se conservan para el futuro pase al auditor.

Demo lista en `.tmp/demo-r17-decisiones`. Para crear otra desde fuentes, ejecutar `python -B -m scripts.create_review_journey_demo --presupuesto --name otra-demo-r17` con un nombre nuevo. Seleccionar la factura ficticia de presupuesto con demo-administrativo y abrir «Revisar» en la TAC del 02/08. La demo utiliza una base nueva de esquema 35. Los datos y las bases anteriores permanecen en sus carpetas.

Pruebas reproducibles en Windows desde esta copia con datos ficticios:

- `python -B scripts/verify_r17_board.py` comprueba decisiones, permisos, evidencia, importes y bandeja. El resultado queda en `.test-results-r17/python-summary.json`.
- `node --test (Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object FullName)` comprueba la regresión JavaScript desde PowerShell.
- Con `TFG_BROWSER_PYTHON` apuntando al ejecutable del entorno virtual, `node tests/r17_browser_smoke.cjs` prueba el recorrido completo en Chrome o Edge con un perfil, servidor loopback y demo propios.

Resultados en Windows: 37 de 37 pruebas Python seleccionadas y 156 de 156 pruebas JavaScript aprobadas, sin omitidas. El recorrido en Chrome se completó en una base ficticia separada y cerró su servidor. La demo preparada conserva las dos prestaciones pendientes para la prueba del operador.

El pase administrativo al auditor, el cierre final y su Excel siguen pendientes de implementación. La prueba con operadores y la validación del cotejo sobre el CSV real corresponden a etapas posteriores.

---

# B18-R16 · Primera entrega de las decisiones de pantalla

**Probado en Windows con datos ficticios.** La factura abre la planilla en Imágenes con observaciones. Ver factura completa muestra todas las áreas y todos los estados de alcance, incluidas las filas excluidas e indeterminadas; es una vista de consulta sin botones de decisión por fila. Los motivos visibles cuentan prestaciones únicas antes de paginar, pueden solaparse y se calculan con los demás filtros activos. La revisión se inserta inmediatamente debajo de la fila y solo se abre una a la vez. La TAC repetida muestra en el contexto los antecedentes identificados por el cotejo existente.

La planilla separa facturado, convenio HPC, presupuesto autorizado, diferencia a revisar y propuesta humana. El importe ausente no se muestra como cero. Si difieren los totales comparables de referencia y presupuesto, se indica «Elegir referencia» y no se deriva un débito de esa diferencia. La columna de convenio puede mostrar un candidato y lo identifica como tal. El párrafo de presupuesto identifica la orden, el usuario que registró el movimiento (sin atribuirle otra función), fechas, facturado y exceso. No se ampliaron las reglas de interpretación del CSV.

**Prueba reproducible.** En esta copia, la demo ya preparada se llama `.tmp/demo-r16-imagenes`. Para generar otra, con nombre nuevo: `python -B -m scripts.create_review_journey_demo --presupuesto --name prueba-r16-nueva`. El caso parte de un nomenclador ficticio con código exacto, una TAC de ARS 450.000 y un presupuesto individual de ARS 200.000 sin arancel HPC: se ven ARS 250.000 a revisar y ninguna propuesta guardada. La cuenta administrativa y su contraseña generada quedan solo en la carpeta privada de esa demo. No arrancar contra una base de otra versión.

**Verificación.** `python -B scripts/verify_r16_board.py`: 30/30 pruebas Python de planilla, consulta por alcance, conteos, valoración y presupuesto. `node --test (Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object FullName)` (PowerShell): 156/156. Prueba en Chrome: con la variable `TFG_BROWSER_PYTHON` apuntando al ejecutable del entorno, `node tests/r16_browser_smoke.cjs` generó su propio ejemplo y verificó el ingreso, Imágenes, las columnas, la apertura bajo la TAC, el párrafo del CSV, la consulta sin acciones y el regreso. Cerró el servidor local. No se ejecutó toda la suite Python ni se hizo aceptación con un operador real.

**Siguiente entrega.** Guardar una sola decisión por prestación con cuatro opciones e importe; elegir y guardar la referencia cuando difieran; conservar motivo, historia, versión y rol. Pendientes y Revisadas deberán contar decisiones por prestación, más allá de los avisos individuales. Después: cierre administrativo, revisión/ajuste final del auditor y exportación, lista inicial de facturas y carga conjunta del Excel y CSV. La base de R16 no incorpora nuevos campos ni migraciones de negocio. La asociación automática de informes PDF sigue diferida.

---

# B18-R15 · Presupuesto individual de la orden HPC

En Excepciones se muestra la diferencia positiva entre el **total original de la fila** del Excel y el **total expresamente aprobado para esa realización** en el CSV HPC. Conserva por separado el convenio, el aval de la práctica y el débito propuesto. La señal es de lectura: no escribe decisiones ni propuestas. El filtro Aval CSV → Presupuesto por revisar incluye excesos y presupuestos indeterminados; el detalle explica el caso en un párrafo, con orden, fechas y registro del CSV. Los demás controles siguen disponibles por separado.

Se usa el original verificado de una captura CSV v3 seleccionada y vigente; no se reescribe su interpretación ni se migra la base (esquema 34). Para calcular, el lote debe tener alcance HPC confirmado y la fila debe corresponder al mismo afiliado, código completo, descripción, una realización y un único aval utilizable en los 60 días. El movimiento debe declarar expresamente el total individual y la moneda ARS/pesos. Una simple mención de precio de listado no crea una excepción de presupuesto. Cotizaciones, importes comunes, moneda ambigua, correcciones, cantidades no comparables, asociaciones dudosas o aval reutilizado no generan una diferencia numérica. No se presume que el presupuesto prevalezca sobre el convenio. El texto libre y órdenes con varias prácticas pueden requerir cotejo; no se acreditó cobertura de todos los formatos reales.

Demo reproducible en una **carpeta nueva**: `python -B -m scripts.create_review_journey_demo --presupuesto --name mi-prueba-presupuesto`. Abrir FICTICIO_presupuesto_TAC.xlsx → Excepciones → TAC TRIDIMENSIONAL → Detalle. Facturado ARS 450.000 el 02/08, presupuesto ARS 200.000 del 02/07, exceso ARS 250.000; sin propuesta. El catálogo ficticio contiene HPC sin tarifas, para comprobar que el importe procede exclusivamente del CSV.

Pruebas: `python -B -m unittest tests.test_csv_budget tests.test_csv_validity tests.test_csv_reviews tests.test_csv_item_resolutions tests.test_column_board tests.test_monetary_gate` (32 aprobadas); suite Node `tests/*.test.cjs` (155 aprobadas). Chrome/loopback con una copia de la demo: Excepciones y filtro, sin débito propuesto, tres accesos al párrafo, sin desplegables. En Windows, el primer intento de generar la demo no pudo crear los enlaces internos del almacenamiento dentro del sandbox (WinError 5); la demo completa en una carpeta nueva y las pruebas de integración se verificaron con las operaciones de archivo nativas habilitadas. Queda pendiente aceptación del operador. No se usaron datos reales, no se inició un servicio permanente y no se probó toda la suite Python.

Cambios: lectura de presupuesto en `app/csv_budget.py`, correspondencia, cotejo y bandeja; presentación en planilla, filtro y panel; generador ficticio y pruebas de presupuesto/planilla. Siguiente validación: contrastar los formatos autorizados que usa el operador en la práctica y comprobar que los casos dudosos no le crean falsas diferencias.

# B18-R14 · Revisión centrada en una observación

Revisar abre una observación prioritaria. Para RN13 muestra Total informado, Suma de componentes y una explicación de la diferencia en lenguaje directo. La selección completa de controles se consulta en Otros controles. Las consultas de aval y referencia, las prestaciones relacionadas y Siguiente caso se encuentran en ese apartado. El respaldo técnico se carga al desplegarlo. La historia se ofrece cuando tiene registros. Las herramientas avanzadas se cierran al abrir Revisar.

El formulario muestra Confirmar, Descartar y Consultar auditor según la función y estado permitidos por el servidor. Motivo y respaldo es un único campo obligatorio para indicar qué se comprobó y en qué se basa la decisión o consulta. El mismo texto humano se envía en los dos campos existentes de fundamento y respaldo. La historia presenta una sola vez ese texto cuando coincide. Los registros anteriores con textos distintos conservan ambos. Cada envío corresponde a la observación seleccionada. El reintento exacto conserva identificador y cuerpo. Guardar y seguir mantiene el recibo y la navegación versionada.

Comprobación propia en Windows y Chrome con la factura de 3.000 órdenes ficticias: una observación inicial, tres decisiones disponibles sin preselección, un campo y ningún dato técnico cargado de entrada. Campo y Guardar visibles al 125 % de zoom. Guardado con avance y respuesta perdida simulada con reintento exacto y una sola decisión persistida. Aprobaron 154 pruebas JavaScript y 16 Python de decisiones, avales y propuestas. El guion browser_observation_workflow se adaptó al campo único y al selector desplegable. La ejecución propia de navegador usó el guion CDP de esta copia. Pendiente la aceptación del operador. Esquema 34.

# B18-R13 · Encuadre e identificación de la planilla

La cabecera separa Prestación facturada, Autorizaciones y documentos, Importes y Revisión. Las dos filas de encabezados comparten una rejilla de columnas explícita. Las acciones se conservan a la derecha al desplazar horizontalmente. Los encabezados y el paciente permanecen visibles al desplazar verticalmente. Cada grupo de paciente muestra nombre, afiliado y cantidad de prestaciones con separación visual entre grupos. La fecha y la orden están separadas de la descripción, código y cantidad.

Las marcas tienen fondo y borde dentro de la celda. Los colores se acompañan con texto breve. Las filas conservan una banda alternada y líneas horizontales. El estado de fuentes y los filtros avanzados se consultan a demanda. Buscar cierra el panel de filtros avanzados y conserva los criterios seleccionados.

Las facturas con más de una página abren la planilla ampliada para disponer de más altura. La factura y la identidad de quien revisa siguen en la cabecera. Mostrar menú recupera la navegación y conserva filtros y página. Ampliar planilla vuelve a la vista de trabajo. Es una decisión de presentación reversible, pendiente de aceptación del operador.

Pruebas propias del incremento en Windows: 154 JavaScript aprobadas. Con Chrome se verificó una factura ficticia de 3.000 órdenes, 750 pacientes y 750 órdenes de autorización CSV: página de 50 prestaciones, continuidad del paciente en la página siguiente, filtro de 750 avales utilizados y filtro de 1.500 códigos TAC. Se verificaron las doce columnas y sus encabezados alineados al 100 % y al 125 % de zoom real. En el modo ampliado entraron cuatro filas completas al 100 % y dos al 125 % en el área de navegador ensayada. Honorarios y derechos opcionales ampliaron correctamente el encabezado de importes y conservaron visibles las acciones. Las comprobaciones corresponden a datos ficticios.

Preparación reproducible: `python -m scripts.create_columns_volume_demo --name demo-3000-ordenes`. Los tres lotes ficticios conservan su historia y archivos. No hay nueva migración de datos. Esquema 34.

# B18-R12 · Planilla de revisión por columnas

La tabla separa fecha, prestación y código, coincidencia en fuentes, aval individual, informe PDF, autorización PDF, facturado, referencia de convenio, diferencia, débito propuesto y revisión. Las marcas incluyen texto. Un PDF aportado y pendiente de lectura tiene tilde y estado Por leer. La falta de adjunto o coincidencia muestra una cruz neutral. Las autorizaciones individuales indeterminadas conservan el signo de pregunta. Los rechazos explícitos se distinguen con texto y color.

Documentos y autorizaciones abren su detalle desde la marca. El valor abre la referencia económica. Las acciones Revisar y Detalle quedan visibles en la última columna. Registrar o corregir categoría se ofrece desde Detalle. Las fuentes, códigos completos, cantidad y fila se conservan allí y en el contexto de la prestación. Los filtros de aval CSV, valores, informe y autorización PDF están visibles junto a la búsqueda. El filtro de aval se calcula antes de paginar. Su estado Para revisar excluye avisos de reutilización ya revisados con esa evidencia.

La columna Débito propuesto reutiliza la evaluación de vigencia de la última propuesta humana de esa prestación. La diferencia exploratoria conserva su columna independiente. Una propuesta ausente muestra raya y Sin propuesta. Se conservaron importes de fila y cantidades. El formato monetario de pantalla conserva decimales sin usar flotantes. Esquema 34.

La demo nueva se genera con `python -m scripts.create_columns_demo --name demo-columnas`. Usa la TAC ficticia, catálogo HPC sintético y un PDF ficticio adjuntado para ilustrar su estado Por leer. Incluye dos facturas. La aceptación del operador sigue pendiente. La asociación automática de informes continúa diferida.

# B18-R11 · Seguimiento de excepciones y avales CSV

Al guardar, la ficha identifica la prestación, los motivos que la mantienen en Excepciones y cuántos controles del análisis están sin conclusión o sin evaluar. Una captura seleccionada con registros apartados genera un aviso por factura. La falta de coincidencia tiene una marca neutral.

Para una TAC cuyo aval ya respalda otra prestación, abrir **Revisar → Consultar aval CSV**. El operador puede **Marcar aval como revisado** con motivo. Solo se retira ese motivo de Excepciones para la evidencia revisada. En Todas se conserva el cotejo y su historia. Otra observación mantiene la prestación en la bandeja. Si cambia la evidencia, se vuelve a evaluar si corresponde mostrar el aviso. Un nuevo aval que respalde la segunda TAC deja de generar el motivo de reutilización.

Esquema 34. El historial del aval conserva autor, motivo, fuentes y prestaciones relacionadas. El cierre y la exportación de la revisión incluyen esa constancia. En copias de datos existentes, con el servidor detenido, usar el procedimiento local de respaldo y actualización. Restaurar código requiere una base compatible. La aceptación con operadores sigue pendiente.

Escenarios ficticios independientes: `python -m scripts.create_review_journey_demo --name demo-altas --categorias` y `python -m scripts.create_review_journey_demo --name demo-tac --tac`. El cotejo guiado de informes sigue disponible. Su asociación automática continúa diferida.

# B18-R10 · Corregir categoría y solicitar un alta

En una revisión HPC abierta, Corregir categoría guarda una nueva versión para el mismo código y conjunto. Exige una categoría distinta, motivo y celda verificable en un XLSX. Detalle → Ver historia de categoría muestra autor, fecha, motivo, hoja, fila, columna, huella y acceso al archivo de cada versión. Las revisiones cerradas solo consideran versiones anteriores a su cierre. El cambio es de clasificación y no requiere ni crea un arancel.

Desde Detalle → Solicitar alta al administrador, el operador elige Categoría sin arancel o Alta en convenio HPC y escribe el motivo. La planilla muestra las solicitudes pendientes del conjunto. El administrador puede preparar el registro correspondiente o rechazar la solicitud. Para vincular un alta ya registrada, se comprueba el código y, si es de convenio, la fuente y la existencia de una práctica propia activa. La respuesta conserva responsable y motivo. El operador puede consultar la respuesta en Solicitudes de alta. Este circuito es interno y conserva el alta directa de categorías de B18-R9.

Preparar demo nueva: python -m scripts.create_review_journey_demo --name demo-altas --categorias. En factura A usar el nomenclador ficticio inicial (Imágenes) y luego Nomenclador-corregido.xlsx (Otras prácticas), hoja Prácticas, celda A2. La factura B usa el mismo código con otra descripción; el catálogo de prueba tiene cero aranceles. Las solicitudes de convenio se prueban por separado y siguen requiriendo documentación económica.

Esquema 33. Con el servidor detenido, usar el procedimiento backup-and-upgrade de app.cli al preparar una actualización. Las categorías del esquema 32 pasan a ser versión 1, con sus documentos intactos. Restaurar código no revierte la base. Pendiente la aceptación del operador.

# B18-R9 · Registrar categoría sin arancel

En una factura abierta con alcance HPC confirmado, una cuenta admin o reviewer con acceso al conjunto puede abrir Todas las prácticas y registrar una categoría desde una fila sin clasificar. Se conservan el código y la descripción efectivos de la factura. El operador elige Imágenes u Otras prácticas y señala archivo XLSX, hoja y celda del código. El servidor comprueba el código completo en la celda; la interpretación de la categoría corresponde al operador. La declaración conserva archivo privado, SHA-256, localizador, usuario y referencia de la factura.

Se aplica por código exacto a facturas HPC del mismo conjunto, incluidas importaciones posteriores. Las declaraciones no se propagan por descripción ni prefijo. Una contradicción conserva la práctica sin clasificar. Un respaldo que ya no sea íntegro deshabilita la clasificación documentada. Detalle permite consultar su procedencia. No se crea arancel, autorización, propuesta ni equivalencia. Esta entrega admite altas únicas; no incorpora correcciones de declaraciones ya guardadas.

Esquema 32. Para una base existente se requiere el procedimiento fuera de línea backup-and-upgrade de app.cli; restaurar el código no revierte la base. Para reproducir con datos inventados: python -m scripts.create_review_journey_demo --name demo-categorias --categorias. Seleccionar la factura A, abrir Todas las prácticas y usar el Nomenclador-ficticio.xlsx de la demo, hoja Prácticas, celda A2. Comprobar la misma categoría en la factura B y el respaldo en Detalle. El catálogo ficticio usado para confirmar HPC contiene cero aranceles.

# B18-R8 · resultado de Guardar y seguir

El recibo identifica la prestación y la fila recién guardada. Se calcula junto con la siguiente página en la misma lectura de la factura y con las reglas de Excepciones completas, aunque el filtro activo o la página oculten esa fila. Enumera los motivos pendientes o informa que la prestación salió de Excepciones. Al final del recorrido se conserva el recibo en la ficha. Una lectura incompleta o de otra versión no acredita la salida.

Para reproducir el ensayo en Windows, generar una demo nueva con python -m scripts.create_review_journey_demo --name demo-recibos --tac. En la factura A resolver la diferencia de suma RN13 de la TAC (fila 2) y luego la de la consulta (fila 4). La TAC conserva el motivo de aval CSV; la consulta sale de Excepciones. El guardado explícito y su historia siguen usando las operaciones de B18-R7. No cambia el esquema de datos.

# B18-R7 · revisión por prestación

La ficha abre con práctica, fecha e importe; debajo identifica afiliado, factura y fila. La fila abierta se indica en azul, las observaciones en ámbar, el guardado confirmado en verde y un error de registro en rojo, con texto en cada estado. El operador elige una acción explícita entre las admitidas para la observación y su función, indica motivo y respaldo, y guarda. La comprobación de una respuesta perdida reenvía la misma operación con su clave original.

Para el cotejo de 60 días, si un aval localizado ya respaldó una única prestación anterior, se muestran las fechas verificadas de resolución y prestación. El detalle «Ver las dos prestaciones» identifica ambas facturas y filas. Una práctica localizada sin declaración individual concluyente se muestra como pendiente de confirmación. No cambia el esquema ni la regla de autorización. En una copia nueva, el recorrido se prepara con python -m scripts.create_review_journey_demo --name demo-tac --tac.

Prueba de Chrome en Windows con facturas y un CSV ficticios: resolución del 02/07, TAC del 02/08 y segunda TAC del 04/08; comparación de las dos prestaciones, ficha, resolución y avance, derivación al auditor, coincidencia sin autorización individual y recuperación de respuesta perdida sin duplicar la decisión. Pendiente la aceptación humana en los equipos de los operadores.

# B18-R6 · actualización de la bandeja

La consulta agrupa los patrones de resultados de controles dentro de su propia lectura; distingue las reglas que deben actualizarse en cada fila. Relee decisiones, derivaciones, valores y cotejos CSV. Para las dependencias de autorización puede reutilizar el componente del análisis registrado, después de acreditar una igualdad completa y volver a verificar las huellas de filas, alcance, fuentes, ediciones y vínculos. Se conserva en memoria un máximo de 32 pares de huellas. No se guardan fichas de pacientes ni decisiones en esa lista. Una firma distinta exige reconstrucción. No cambia el esquema de base.

En Windows, sobre 13.000 prestaciones ficticias con CSV y catálogo HPC, la mediana de actualización tras guardar pasó de 4,88 a 3,59 s en ensayos pareados por estado de partida. Guardar y seguir completo pasó de 7,76 a 4,48 s. La primera comprobación sin huella previa puede costar más. Se comprobó la equivalencia con B18-R5 y la vigencia de la bandeja tras tres guardados. La aceptación con el operador queda pendiente.

# B18-R5 · tiempo de Guardar y seguir

La resolución y la decisión asociada comparten la comprobación de vigencia dentro de una única transacción. La consulta de la bandeja incorpora la ficha siguiente, con su historia y la misma versión de la revisión. Se calculan los detalles de presentación solo para la página que se muestra. Las decisiones, los filtros y el alcance se vuelven a leer; no se conservan resultados entre solicitudes. El esquema continúa en 31.

En Windows con 13.000 prestaciones, CSV de 100 órdenes y catálogo HPC ficticios, la mediana del clic a la siguiente ficha fue de 8,46 s frente a 21,24 s en la ejecución de control con B18-R4. Se comprobaron tres ciclos de guardado y se contrastaron filas, total e historia con lecturas independientes. Se mantiene pendiente la aceptación del operador con su flujo normal.

# B18-R4 · revisión por excepción

La bandeja inicial muestra el motivo de cada excepción a partir del control vigente, el cotejo CSV, la derivación o la comparación de valores. Las diferencias de valores siguen siendo exploratorias. Las fuentes faltantes o no seleccionadas se anuncian juntas para la factura, incluso si ningún caso cumple el filtro. En Excepciones y Derivadas se muestran ocho columnas. La planilla completa y el detalle conservan los datos de origen. Los filtros específicos están en Más filtros.

Al confirmar Guardar y seguir, el sistema conserva la historia de la observación y solicita la siguiente prestación del mismo recorrido. Las otras observaciones permanecen disponibles. Si el servidor rechaza el guardado o no confirma su resultado, no avanza. La consulta del último caso conserva la ficha. El esquema de datos no cambia.

Verificado en Windows con fuentes ficticias: apertura, motivo de diferencias de suma, aviso de fuentes a nivel factura, presentación compacta, cinco vistas, guardado seguido de avance en orden descendente y rechazo simulado sin avance en Chrome. La selección Python abarca bandeja, observaciones, vigencia CSV y valores. JavaScript conserva la cobertura de las vistas de consulta y la planilla completa. La aceptación humana y el tiempo de respuesta con un lote representativo están pendientes.

# B18-R3 · bandeja de excepciones de la factura

Al seleccionar una factura importada se abre Revisión, en Excepciones y para todas las áreas elegibles. La bandeja reúne avisos pendientes, resultados por actualizar, derivaciones en curso, incidencias de aval CSV y diferencias exploratorias de importe. La ausencia de filas no certifica cobertura ni conformidad. Las vistas rápidas reinician filtros y conservan el orden elegido. Todas las prácticas permite volver a la planilla y consultar otros alcances.

Desde Revisar, Siguiente caso busca la siguiente prestación según los filtros y el orden actuales, incluso en otra página o si la prestación resuelta ya salió de la vista. La navegación es de lectura. El guardado sigue siendo explícito; un cambio concurrente requiere revisar de nuevo. Posibles imágenes sigue siendo una lista para comprobar, sin reclasificación automática.

Cambios en app/api.py, app/practice_board.py, app/authorization_matching.py, web/index.html, web/workbench.js, web/observation_workflow.js y web/style.css. Pruebas de regresión en tests/test_practice_board.py, tests/test_csv_validity.py y tests/web_workbench.test.cjs. Se actualizaron dos extractores de funciones usados en pruebas JS. Verificación en Windows con facturas ficticias: bandeja inicial de cuatro excepciones, cinco vistas rápidas y guardado explícito de RN13; la fila resuelta salió de la selección y Siguiente caso conservó el orden descendente. El servidor local se cerró. Sin migración adicional. Pendiente de aceptación por el operador y medición de tiempos con una factura de volumen representativo.

# Vigencia operativa del CSV HPC

Decisión del usuario: límite de 60 días. Para el cotejo de la planilla se cuentan días calendario desde la resolución explícita por ítem del CSV hasta la realización del Excel (días 0 a 60 inclusivos). Nunca se sustituye esa resolución por la fecha de orden ni se exige fecha de realización en el CSV. Una autorización explícita de ítem aporta evidencia de al menos una unidad. El cotejo recorre las filas elegibles de las revisiones actuales del conjunto en orden de realización, independientemente de la página, el filtro o el orden de importación. Un cruce inequívoco muestra la primera realización respaldada y el localizador utilizado a las siguientes. Empates, identidades o cantidades ambiguas quedan para revisión. Es evidencia administrativa de lectura; RN10 sigue teniendo su regla temporal propia. No se escribe una asignación institucional ni se generan débitos.

# Corrección local de B18

El CSV v3 marca para revisión los bloques individuales no interpretables y las cláusulas condicionales. Las capturas v2 conservan sus originales e historia. Para utilizar el resultado corregido, volver a abrir la vista previa del original, confirmar una nueva interpretación, seleccionarla en el lote abierto y actualizar el análisis explícitamente. La grilla separa el estado declarado del ítem CSV de la correspondencia con la fila.

La comparación exploratoria por código exacto utiliza el convenio documentado y la unidad confirmada del lote. La modificación no cambia el esquema 31. Se corrigió el cierre de conexiones SQLite de los fixtures Windows.

# Ampliación aislada: señales de práctica y autorización

7 de noviembre de 2026. La planilla separa presencia de práctica (afiliado y código completo, candidato por catálogo, incompatible, no localizado o sin evaluar) de estado individual declarado en fuente (autorizado, rechazado, pendiente, derivado o no determinable). Una tilde no genera decisión de auditoría ni débito. La falta de coincidencia no se interpreta como rechazo.

Solo una correspondencia completa unívoca o un vínculo humano vigente puede presentar un estado individual explícito, sin resoluciones ambiguas/reemplazos pendientes. Sin fuente vigente o identidad suficiente no se muestra «no localizada». Los candidatos de catálogo, aun con historial AUTORIZADO, no reciben autorización individual.

Para el CSV observado se muestran por separado las menciones AUTORIZADO/RECHAZADO del campo de movimientos de las órdenes candidatas. Son historial de orden(es), NO un estado actual ni una resolución por práctica; se conservan estados mixtos sin escoger el último texto. Cuarentenas y cobertura parcial mantienen los límites de B14. No cambia el adaptador, los originales, controles, importes ni esquema30.

Probado con casos ficticios de presencia, ausencia, resolución individual, ambigüedad, vínculo desactualizado, fuentes no seleccionadas e historial CSV mixto. Aceptación visual y Windows pendientes. No se implementó asociación automática de informes PDF.

# Ampliación aislada: modos de vista y selección múltiple

7 de noviembre de 2026. La planilla expone los modos existentes (general, trabajo pendiente, información faltante/sin evaluar y avisos revisados) y permite elegir varios controles RN09–RN19. `rules_match=any` muestra prestaciones que satisfacen cualquiera; `all` exige todos en la misma prestación. Resultado y motivo deben coincidir dentro de cada control. Sin selección se conservan todos los controles. `rule` singular sigue compatible con clientes anteriores, pero no se combina con `rules`.

Son filtros de lectura, no selección de reglas a ejecutar ni decisiones automáticas. Se mantienen los estados no evaluados, filtros documentales/económicos, familia de imágenes, agrupación y paginación. Los filtros de distintas dimensiones se combinan por intersección. Cambiar el filtro no cambia la evidencia, el análisis ni la decisión humana. No hay nuevos filtros separados de laboratorio o consultas, ni asociación automática de informes.

Implementado y probado con datos ficticios en copia B12 final; aceptación visual Windows pendiente. Detalle de ejecución en `.test-results/modes/REPORTE.md`.

# Ampliación aislada: recepción local Sync

Incorporación de paquetes prepareImageDay histórico 0.4 por el panel JSON, con original privado, A1 derivado trazable y cobertura parcial/no validada. Sin conexión hospitalaria ni automatización PDF. Ver `HPC_SYNC_INTAKE.md` para contrato, controles, pruebas y límites. Esta ampliación no acredita el intercambio actual ni aceptación Windows.

# Estado de la copia para nube

## Explicación de la diferencia de suma, 01/11/2026

Ajuste solicitado durante la verificación de 7767dfd: mostrar total informado, suma y
diferencia con dirección explícita. Se expone el difference_ars existente del control
sin modificar su signo ni la regla. Para 10+20 frente a 39: total 39,00, suma 30,00,
diferencia −9,00 (suma menos informado); el total supera la suma en ARS 9,00.
El formateo usa cadenas decimales exactas, conserva datos faltantes y no genera débito.
Prueba JavaScript de ambos signos, magnitudes grandes y datos insuficientes; recorrido
Chromium añade captura de la suma a ambas resoluciones. El informe final identifica
el SHA de la verificación agregada posterior a este ajuste.

## Revisión visual del recorrido, 01/11/2026

Antecedente conservado: `61af5ff77ecce607cc78d1ca6d7a17e6600d4a51`.
El coordinador recuperó el ZIP y el parche, verificó sus hashes e inspeccionó las
capturas y las maquetas originales. Señaló panel lateral alto, pérdida del encabezado,
lista extensa de pendientes y resolución deshabilitada al consultar. No fue aceptación.
Se implementa una franja inferior que reserva espacio en la grilla; mantiene identidad,
importe y acciones visibles. Los filtros se conservan y reaparecen al cerrar la revisión.
Pendientes en resumen desplegable, campos de resolución sólo para resolver, pregunta
administrativa primero en Auditor, fila seleccionada y grupos con factura/prestador
comprobado (o indicación explícita de que falta comprobarlo). No se alteran permisos,
estados ni reglas económicas. Se añade al contrato de lectura de grilla el prestador
ya registrado; no se infiere del archivo.

Demo ampliada: 12 prestaciones, tres afiliados ficticios y otra factura para la posible
repetición; cuentas individuales reviewer. Hay filas sin indicios, que siguen mostrando
información insuficiente por fuentes faltantes. No se fabricó una evaluación exhaustiva
ni una autorización para que la demo pareciera libre de pendientes.

Chromium del candidato: encabezado, acción y formulario sin desplazamiento propio a
1440×900 y 1366×768, con siete y cuatro filas completas visibles respectivamente.
Consulta, solicitud/aporte, resolución parcial, atribución a ambas cuentas, reenvío tras
respuesta perdida y siguiente sin decidir comprobados. Capturas inspeccionadas aquí.
81 pruebas JavaScript del candidato aprobadas. La entrega adjunta resultados agregados
sobre el SHA final, sin atribuirle la validación Windows del antecedente.

Defecto detectado al inspeccionar el cierre parcial: el replay actualizaba el panel pero
no la grilla. Se refresca también la grilla después de confirmación y se comprueba que
la observación resuelta no figure en el conteo pendiente. Se mantiene la distinción entre
guardado confirmado, rechazado e incierto. Los primeros ensayos visuales fallaron por
esperar texto ahora desplegable y por insuficientes filas visibles; se conservan los logs
ui-browser-first y ui-representative-first a fourth. No se rebajó la exigencia de tres filas.
La columna de acciones se amplió tras detectar recorte del botón Detalle en las capturas.

Library: el intento anterior del helper múltiple falló antes de transferir por red; no fue
una denegación. La ruta nativa de un archivo recuperó parche y ZIP versión 0. Esta entrega
reemplaza el mismo ZIP con guardia de versión y conserva el antecedente. Las maquetas
siguen sin píxeles locales: esta iteración se apoya en la inspección y descripción del
coordinador, no afirma que este ejecutor las haya abierto. Sin push/PR/merge/despliegue.
Windows del SHA nuevo, aceptación humana y sincronización académica siguen pendientes.

## Incremento local administrativo/auditor, 01/11/2026

Base exacta `a7ad15756cb187d2130ddf13e963adec4eb630a8` comprobada contra
rama remota feat/consultas-respuestas-externas y PR #7; main conservaba dcaa391.
Rama aislada `feat/recorrido-admin-auditor`, sin push, PR, merge ni despliegue.
[Guía funcional, permisos reales, transiciones, migración y prueba de usuario](RECORRIDO_ADMIN_AUDITOR.md).

Implementado: resolución administrativa de suma/convenio/autorización sin localizar
con respaldo; derivación concreta al Auditor; solicitud/aporte de información sin
resolver; cierre por observación sin segunda aprobación ni cierre de lote; grilla
agrupable, motivo pendiente actualizado, historia compartida, bandeja entre facturas,
resolución transaccional e idempotente con versiones/evidencia y operaciones inciertas.
Se reutiliza reviewer por conjunto para ambas funciones internas; no hay separación
adicional de permisos entre ellas ni acceso médico por fragmentos. No se concedieron
facultades a cuentas reales. Demo nueva con cuentas individuales ficticias, aislada
y sin sobrescribir bases existentes. Esquema 27 aditivo con respaldo previo obligatorio.

Verificación Linux del candidato: suite protegida 317 descubiertas, 315 aprobadas,
2 omisiones Windows (AES-GCM/.NET y ACL NTFS), sin fallos ni errores. JavaScript
81/81. Focal de circuito y migración histórica 12/12. Chromium: recorrido nuevo
completo (pedir/completar, cierre parcial, respuesta perdida y replay después de
reabrir sin duplicación) y seis escenarios previos U1/U2/Q1/Q2 aprobados, sin errores
JS ni peticiones externas. pip check correcto. Generador de demo ejecutado en un
directorio nuevo `.tmp/verificacion-recorrido`. Capturas administrativo/auditor y
cierre parcial inspeccionadas; el commit de entrega se vuelve a comprobar con las
mismas suites y deja sus códigos de salida en `.test-results/final-exit-codes.json`.

Evidencia: `.test-results/increment-second-summary.json`, `python.log`,
`focal-final.log`, `js-third.log`, `observation-browser.json`,
`browser-fourth.log`, `browser-regression-second.log`, `administrativo.png`,
`auditor.png` y `cierre-parcial.png`. El informe final identifica el SHA probado.

Primeros fallos conservados: suite inicial 321 descubiertas (incluía seis casos
importados dos veces), 315 aprobadas, cuatro fallos y dos omisiones. Tres fallos
compartían expectativa antigua del esquema de recuperación; se actualizó a 27.
La migración histórica 25→26 se fijó explícitamente a 26, preservando su aserción.
Se quitó la duplicación de descubrimiento; no se suprimieron pruebas funcionales.
Primera focal de reutilización esperaba alta 201 ante reanálisis idéntico (el servidor
reutiliza con 200); se corrigió el escenario incorporando un cambio independiente
que realmente exige otro análisis, y se verifica conservación de la resolución.
Primera prueba de navegador detectó actualización tardía de panel tras cambiar
función: corregida comprobando contexto y función. Otro intento detectó URL relativa
en la comprobación HTTP del guion: corregida a loopback absoluto. La regresión visual
detectó botones recortados en columna estrecha: se amplió y apilaron, sin force click.
La carga de vigencia por fila se sustituyó por una captura compartida por lote.
Logs iniciales separados: `increment-first-summary.json`, `observation-third.log`,
`browser-first.log`, `browser-second.log`, `browser-regression.log`.

Windows de a7ad157: **reportado por el usuario**, 306 Python, 78 JavaScript y seis
escenarios Chromium; no ejecutado ni logs inspeccionados en este entorno. No acredita
el nuevo commit. Windows del incremento, aceptación de Hernán y sincronización del
TP académico original quedan pendientes. Se conserva REQUISITOS_TP literal.

Bloqueo de referencias visuales: Library resolvió los dos IDs de 08/09 v2, pero el
helper vigente devolvió `download failed` para cada transferencia y su único
reintento explícitamente local. No hubo píxeles disponibles para inspección; no se
sustituyeron las referencias ni se eludió la transferencia. Esto limita el cotejo con
las maquetas, aunque se pudo implementar y comprobar la interfaz real. No hubo
rechazo de auto-review ni cambios reales, comunicaciones externas o débitos.



## Candidato Q1/Q2, 31/10/2026

Base aa9db1936f9bda1bc02cbe562604a558c285338b: validación Windows completa informada
por el usuario (303 Python, 76 JS, cinco cierres, tres fechas y cinco Chromium).
Es antecedente aprobado; no valida este nuevo cambio funcional. Aceptación humana
pendiente. La causa del fallo histórico de barrera permanece indeterminada.

Q1 bloquea sólo creación nueva en internación usando classify; no bloquea otras
exclusiones ni respuestas existentes. Permisos, versión y replay exacto se conservan;
la historia expone capacidad y motivo. UI conserva historia y operaciones inciertas.
Q2 admite recepción histórica manteniendo fecha informada y registro del servidor.
La migración 26 reemplaza sólo medical_response_open, sin cambiar migración 25,
columnas, datos, cierres o disparadores de inmutabilidad. Mantiene fecha no futura,
zona horaria y normalización; no añade precisión ni reinterpreta registros anteriores.
Se añade cobertura de migración con backup/rollback, historia I, replay, fechas,
exportaciones y navegador real. El guion conserva los cinco U1/U2 y tres casos de
fecha; añade q1_q2 con historia de internación y respuesta previa al registro.

Validación Linux en copia aislada `.tmp/q1q2-verification`, preservando las
anteriores: runner protegido final 306 Python, 304 aprobadas y 2 omisiones Windows
(AES-GCM/.NET y NTFS), sin fallos/errores. Siete suites JS 78/78; focal JS 35/35;
focal Python de correspondencia 20/20; recuperación integrada y transportes con/sin
proxy 3/3. Incluye migración 25→26 con respaldo obligatorio, rollback del trigger,
comparación de todas las tablas previas, integridad/FK, ZIP previo intacto, replay
histórico y rechazo de contenido distinto. La recuperación del esquema nuevo
conserva correspondencia histórica y ZIP cerrado con fingerprint verificado.

Chromium 154.0.8037.57 y Playwright 1.62.1: seis escenarios completos aprobados
(cinco U1/U2 más q1_q2), sin pageerrors ni solicitudes externas; fechas canónicas
3/3. Q1/Q2 conserva consultas existentes, registra una respuesta histórica y
verifica un evento/incremento de versión, sin alterar controles, decisiones,
propuestas reales ni cierres. pip check correcto; inventario 159/158 y paquete
de fuentes con esquema 26 comprobados. La aceptación humana y Windows del nuevo
SHA quedan pendientes; no se trasladan las aprobaciones de aa9db193 al candidato.

Fallos conservados y diagnóstico: primera focal 19/20, un error del fixture por
nombre de Excel con tilde en cabecera ASCII; afectó también al sexto escenario
Chromium, antes del producto. Se corrigió sólo el nombre ficticio. Segundo intento
Chromium: cinco U1/U2 pasaron y q1_q2 se detuvo al seleccionar un filtro oculto;
se corrigió abriendo Más filtros mediante UI, sin force ni omitir comprobaciones.
Primera suite completa: 306 ejecutadas, 301 aprobadas, tres fallos y dos omisiones;
los tres fallos provenían de la misma expectativa del esquema 25 en recuperación.
Se actualizó a 26 y se repitieron recuperación 3/3 y suite completa, con resultados
finales anteriores. Ninguna aserción funcional se relajó para buscar verde.

Evidencia en la copia aislada: `.tmp/first-results`, `.tmp/second-results` conservan
los intentos previos; `.test-results/python.log`, `python-summary.json`,
`full-final-output.log`, `focal-corrected-summary.json`, `recovery-corrected-summary.json`,
`node-first.log`, `focal-node.log`, `pip-check.log`, `browser-final.log`,
`browser-datetime.json`, `u1-u2-final-browser.json` y capturas conservan resultados.
El único cambio adicional a los archivos previstos fue la expectativa explícita
de esquema en tests/test_audit_fixes.py. No se modifican dependencias, reglas
monetarias, fuentes reales ni metadatos de la PR; no hay merge ni despliegue.
Windows final: una copia nueva del SHA completo publicado, guía vigente
VERIFICACION_WINDOWS.md, runner completo, siete JS, pip/inventario, seis escenarios
Chromium sin filtros y tres fechas. Conservar primera corrida; si falla, registrar
y diagnosticar sin repetir para buscar verde. La guía mantiene antecedentes separados.


## Incorporación del parche Chromium, 31/10/2026

Base exacta `55094736a5e2487165157eaa2acf7629e70542bd`, misma rama y PR #7 borrador.
El parche aprobado sólo modifica el ensayo Chromium y el registro de estado;
se actualiza además el inventario. Producto, lock y aserciones U1/U2 intactos.
La descarga Library del parche y del informe falló. Se leyeron completos ambos
textos: 88 y 176 líneas. El texto del parche normalizó cinco CRLF de contexto de
ESTADO; se restituyeron conforme al archivo base. Reconstrucción: 6297 bytes,
SHA256 `7fd15f7287b33b4edbe2a7b7563b5721fdeaa9fc3725d57f91275cf8b63b434f`,
idéntico al hash informado; git apply --check aprobó antes de aplicarlo.
No se presenta como descarga binaria exitosa. Informe leído de 11564 bytes.

El antecedente Windows siguiente pertenece al parche local anterior a este commit.
No acredita Windows del nuevo SHA. Se conserva la causa histórica indeterminada
del error de barrera; Q1/Q2 y aceptación humana continúan pendientes.

Validación del candidato en copia aislada `.tmp/chromium-verification`, sin
sobrescribir evidencias anteriores: runner protegido 303 Python, 301 aprobadas,
2 omisiones Windows (AES-GCM/.NET y NTFS), cero fallos/errores. Siete suites JS
76/76; focales de la guía 33 JS y replay histórico Python 1/1; pip check correcto.
Chromium 154.0.8037.57, Playwright 1.62.1, Node 24.19.0, Python 3.12.14,
SQLite 3.53.1, Linux. Primera corrida Chromium corregida: cinco escenarios U1/U2
aprobados, sin pageerrors ni solicitudes externas. Cobertura de fechas 3/3 en UTC:
fill crudo :00 registró Malformed value; :01 y sin segundos funcionaron; todos
los fill canónicos conservaron validez, equivalencia temporal y valueAsNumber.
No se sustituyó fill por asignación nativa para el envío. El guion final tiene
blob `21e97bcfc6ae0d388eedf90f15220afcfba075ce`, igual al parche revisado.
Inventario regenerado: 159 entradas, 158 hashes/tamaños. Se verifica además contra
el índice y mediante paquete de fuentes antes de publicar. Sólo tres archivos
cambian: ensayo Chromium, este registro e INVENTARIO.json. Ninguna dependencia
ni lógica de producto cambia. No se actualiza la descripción de la PR.

Evidencia local bajo la copia aislada: `.test-results/python-summary.json`,
`python.log`, `node.log`, `focal-guide-node.log`, `focal-replay.log`, `pip-check.log`,
`browser-first-candidate.log`, `browser-datetime.json`, `u1-u2-final-browser.json`
y capturas. Los cinco servidores finalizan con salida 0 y el navegador se cierra
según las comprobaciones del guion. Las pruebas anteriores permanecen en su ruta.
Windows final: usar el SHA completo del informe de publicación en una copia nueva,
seguir docs/VERIFICACION_WINDOWS.md (runner completo, siete suites, pip, inventario)
y ejecutar `node tests/browser_write_outcomes.cjs` sin filtro ni --baseline-u2,
con el Chrome/Playwright disponible y python del venv indicado. Conservar primera
corrida y browser-datetime.json: deben aprobar tres casos canónicos y cinco
escenarios; un error rawFill deliberado no es un fill canónico aprobado. No
trasladar los 303/303 Windows del SHA base ni el éxito del parche local al SHA nuevo.

## Antecedente Windows: parche local del ensayo Chromium, 31/10/2026

Base 55094736a5e2487165157eaa2acf7629e70542bd, sin commit nuevo ni publicación.
En Windows 11 build 26300, Chrome 156.0.8078.74 y Playwright 1.62.1 se reprodujo
la normalización de datetime-local: `14:11:00` se lee como `14:11`, válido, pero
el fill literal falla; `14:11:01` y `14:11` funcionan. Se midió en un campo
equivalente y en el formulario real, con selector único y step 1. El DOM de la
primera falla no se conserva completo: su explicación es consistente con estas
reproducciones y el código, sin afirmar una captura retrospectiva de ese DOM.
El ensayo conserva la hora local y canonicaliza sólo segundos cero; añade tres
casos deterministas con validez, equivalencia temporal y fill real. Producto y
aserciones U1/U2 existentes intactos. Los cinco escenarios Chromium aprobaron;
76 JavaScript y pip check también. Evidencias en `.test-results/browser-datetime.json`,
`u1-u2-final-browser.json`, `browser-first-corrected.log`, capturas y `node.log`.
Los 303 Python del SHA base son antecedentes contrastados con archivos; no se
repitió la suite completa para este parche de ensayo ni se generó un release.
Inventario sin regenerar: antes de aprobar integralmente un nuevo SHA se debe
actualizar y verificar su inventario y ejecutar la suite protegida completa.
Q1/Q2, aceptación humana, integración y despliegue siguen fuera del alcance.

## Ensayo de cierres concurrentes: guarda global, 31/10/2026

Alcance exclusivo: `tests/test_audit_fixes.py`, auxiliar y regresiones en `tests/`,
inventario y esta documentación. Base publicada `e6715449c1cdc347fcc1de8d32ee55263014134f`.
No cambia `app/`, `web/`, `scripts/`, esquema 25, U1/U2 ni Q1/Q2.

Evidencia Windows recibida, no inspeccionada como archivos aquí: 299 Python,
298 aprobadas y 1 error, cero omisiones; `FICTICIO missing release barrier`, sin
TimeoutError ni otra excepción encadenada. JS76 y cinco escenarios Chrome aprobados;
recuperación, AES-GCM/NTFS, proxy, migración/rollback e inventario aprobados.
La sonda posterior pasó: respaldo 5,016 s; esperas 5,037/5,017 s; SQLite+objetos
9,4 ms; ACL Prepare/Snapshot 1,008/1,029 s. Sus 58 evidencias originales se conservan.
**Causa original indeterminada**. No se atribuye a Windows, antivirus o disco.
El ensayo era idéntico al de 91a69cff; no demuestra una regresión del producto.

Fragilidad corregida: el timeout local de cada trabajador abarcaba espera del otro
trabajador más todo el respaldo. Ahora las señales expresan sólo el orden funcional.
Un proceso aislado contiene ambos trabajadores y el respaldo; el padre impone un
presupuesto operacional global de 60 s. Es un límite explícito de ocupación del
ensayo, coherente con las sondas aisladas existentes de 45/60 s, y superior al
respaldo de 5,016 s informado; no es una tolerancia contractual del producto ni una
estimación de la causa del error. Superarlo falla y conserva diagnóstico, nunca
habilita un cierre. Limpieza: grupo de procesos POSIX o Job Object Windows con
KILL_ON_JOB_CLOSE, instalado antes del handshake; se verifica fin del job y se
recoge el proceso con esperas acotadas de hasta 5 s cada una. Si falla la contención,
no se inicia el trabajo; no hay alternativa sin aislamiento.

Se mantienen dos publicaciones preparadas, respaldo con dos objetos no registrados
y cero cierres, liberación posterior al respaldo, resultados closed/409, reintento,
restauración con fingerprint igual y dos cierres finales. Ante fallo del respaldo,
la liberación cancela los trabajadores sin confirmar cierres. La primera excepción
se registra antes de esperar limpieza; un bloqueo posterior no la sustituye.

Regresiones: trabajo variable del respaldo sin deadline local ni cierre adelantado;
señal ausente y respaldo bloqueado con expiración inyectada tras el checkpoint;
deadline real independiente; fallos de trabajador/respaldo y limpieza bloqueada.
Un descendiente nativo retiene un bloqueo SQLite: tras detener el árbol se comprueba
que el bloqueo se liberó. La inyección sólo adelanta la guarda; no desactiva los
60 s reales. Control negativo intencional: reintroducir wait(10) hace fallar las
dos variantes de carga sin esperar 10 s; fuente restaurada inmediatamente.

Primera ejecución focal local conservada: 4 pruebas, 3 aprobadas y 1 fallo del
nuevo arnés al intentar leer MIME del host al importar openpyxl en el hijo. Se
corrigió con la misma inicialización MIME Linux del runner, sin ampliar permisos.
La siguiente focal pasó 4/4; después se agregó cobertura independiente del deadline.
Logs locales: `.test-results/closure-focal-first*`, `closure-focal-corrected*`,
`closure-negative-local-deadline.log` y directorios únicos `closure-concurrency-*` /
`closure-probe-*` con fases, primera causa, stderr y resultado. No contienen fuentes
reales; la entrada con sesión ficticia se elimina tras terminar el proceso.
Validación local completa: 303 Python descubiertas, 301 aprobadas y 2 omisiones
específicas de Windows (AES-GCM/.NET y NTFS); 76 JavaScript aprobadas en siete
archivos, sin fallos ni omisiones; pip check sin dependencias incompatibles.
Inventario: 159 entradas, 158 hashes/tamaños; producto sin cambios respecto de
la base. Tras esa ejecución se hizo explícito el cierre de la conexión SQLite de
la propia sonda antes de renombrar en Windows, y el cierre de stdin del supervisor;
se verifican nuevamente la focal y la suite protegida sobre esos ajustes.
La nueva implementación de Job Object y el SHA final requieren Windows nuevo;
no trasladar la aprobación histórica a este artefacto.

## Correcciones U2/U1/D1 de la auditoría de 91a69cff, 31/10/2026

Base auditada `91a69cff9c94e4acfba7a081dc49fb44ce8c8b8c`, rama
`feat/consultas-respuestas-externas`, PR #7 borrador contra `feat/rn14-human-review`.
Windows de 91a69cff informado por el usuario: 298 Python y 63 JS sin fallos/omisiones,
migración 24→25, recuperación con/sin proxy, AES-GCM/NTFS, inventario 156/155 y árbol
limpio. Es antecedente externo; no valida las correcciones actuales. No se reabre
Windows aprobado de f903bad. Q1/Q2 (filas excluidas y fechas históricas) no cambian.

U2: las operaciones inciertas conservan cuerpo exacto, clave, versiones y fecha
normalizada en memoria de la sesión, por conjunto/lote/fila/revisión/formulario.
Reconstrucción, navegación interna y cierre/reapertura recuperan esa misma operación;
las consultas de una revisión anterior sólo permiten comprobar el cuerpo histórico.
No se editan campos de una operación pendiente ni se copian como borrador nuevo.
Doble clic/en curso comparte exclusión. La respuesta tardía actualiza la operación
sin sobrescribir otra vista; cambio de sesión/logout y revocación retiran evidencia.
No se deduplica por texto ni cambia el backend. Cerrar/recargar el documento avisa
si quedan operaciones pendientes; no se guardan textos ni credenciales en disco.
Después de abandonar la página, consultar historia antes de iniciar otra operación.

U1: POST y refresco se tratan por separado en RN14 y aplicabilidad (incluido retiro).
Un POST confirmado bloquea el formulario aunque falle la lectura: muestra guardado
confirmado y pantalla pendiente. Un resultado de POST desconocido bloquea reenvíos,
conserva campos y ofrece sólo GET de historia con autoría/cálculo/fundamento. Una
lista vacía no se interpreta como rechazo; puede haber escritura todavía en curso.
La lectura no atribuye automáticamente un registro de otro actor a esta petición.
El refresco de procesamiento propaga errores sólo cuando lo solicita este circuito.
D1: README y guía Windows indican siete suites, esquema 25 y SHA exacto del informe
final de PR #7; conservan antecedentes diferenciados, sin fijar cantidades futuras.

Evidencia propia antes/después: tres fallos DOM sobre código original (U2 y U1 en
RN14/HPC), conservados en `u1-u2-before-corrected-harness.log`. El primer harness U2
ponía una aserción dentro del transporte, que la UI capturaba como error: se movió
fuera del transporte y se conservó también `u1-u2-before.log`. No se relajó el caso.
Chromium + HTTP real con JS original 91a69cff reprodujo U2: dos IDs/respuestas/eventos.
Con la corrección: un ID, una respuesta, un evento y un incremento de versión.
POST201+GET fallido y POST de respuesta perdida se probaron también en RN14 y HPC,
con historia consultada sin otro POST. Las tablas de propuestas reales, controles,
decisiones y cierres permanecieron idénticas; las simulaciones permanecen separadas.
La primera ejecución Chromium completa tuvo un fallo del harness al seleccionar
una fuente en una pestaña oculta: se selecciona ahora como preparación del escenario,
antes de abrir el formulario; se conservaron log/captura iniciales. El envío del
formulario, el transporte y la comprobación del resultado usan Chromium y HTTP reales.
Harness reproducible: `tests/browser_write_outcomes.cjs`; variante `--baseline-u2`.
No es una ejecución de las sondas originales ni aceptación humana.

**Bloqueo de adjuntos:** Library resolvió PDF de 13 páginas y ZIP de 63113 bytes,
pero el helper soportado devolvió `download failed` para ambos, también tras el
único reintento con destino local explícito. No se materializaron bytes legibles;
no se leyó el informe PDF ni se inspeccionaron/ejecutaron las sondas del ZIP. Se
trabajó con la descripción detallada U2/U1/D1 del encargo y reproducciones propias.
No se inventaron URLs, se cambió de entorno ni se usó otra vía para la descarga.
La revisión contra esos originales sigue pendiente y debe completarse antes de dar
por atendida íntegramente la auditoría externa.

Validación local final: **299 Python descubiertas, 297 aprobadas, cero fallos/errores
y 2 omisiones Windows** AES-GCM/.NET y NTFS. Runner protegido completo, incluida
migración 24→25, cierres, recuperación/activación y sondas restauradas con/sin proxy.
**76 JavaScript aprobadas**, sin fallos/omisiones (13 nuevas); un caso Python nuevo
comprueba replay histórico tras cerrar sin segundo evento ni incremento de versión.
`pip check` correcto; Python 3.12.14, SQLite 3.53.1, Node 24.19.0. La suite Python
completa aprobó en la primera ejecución; los últimos ajustes exclusivos de interfaz
se comprobaron con suite JS completa y Chromium. Inventario final: 157 entradas,
156 hashes/tamaños; sin cambios en locks, fuentes históricas ni esquema/backend.

Chromium final: cinco escenarios aprobados (U2, RN14 confirmado/incierto, HPC
confirmado/incierto), cero errores de página y cero peticiones externas. Los errores
de red fueron inyectados expresamente después del commit o durante el GET de refresco.
Evidencia excluida de Git: `u1-u2-python.log`, `u1-u2-python-summary.json`,
`u1-u2-js-final.log`, `u2-before-browser.json`, `u1-u2-final-browser.json`,
`u1-u2-browser-final-3.log`, `u1-u2-pip-check.log` y `u1-u2-attachments.json` en
`.test-results/`. El informe final identifica el SHA publicado y CI verificado;
las pruebas locales no son aprobación de CI ni una lectura de los adjuntos bloqueados.
No se invocó Astra. Windows del nuevo SHA, aceptación humana y revisión focalizada
independiente pendientes; sin nuevas dependencias, migraciones, fusión o despliegue.
Los apartados siguientes conservan la evidencia histórica.

## Consultas y respuestas externas, 30/10/2026

Rama `feat/consultas-respuestas-externas`, base remota verificada
`7b841af7fd41e6c79be77ecbbacd001b8cc12a01`, destino `feat/rn14-human-review`.
Implementado RN26 externo: consultas por prestación, respuestas múltiples con emisor
informado y registrador separados, contexto/fechas/historial inmutables, permisos y
versiones, reenvíos idempotentes. UI en Detalle; correspondencia incluida en salida
provisional/cierre sin resolver alertas ni modificar autorizaciones o importes.
Esquema 25 aditivo. [Alcance, uso y recuperación](CONSULTAS_EXTERNAS.md).

Linux: **298 Python descubiertas, 296 aprobadas, cero fallos/errores y 2 omisiones
Windows** (AES-GCM/.NET y ACL NTFS). **63 JavaScript aprobadas**, cero omisiones.
Runner oficial protegido completo; 16 Python y 7 JS nuevas. `pip check` correcto.
Python 3.12.14, SQLite 3.53.1, Node 24.19.0; venv dedicado reutilizado, sin nuevas
dependencias ni cambios de locks. Inventario final: 156 entradas, 155 hashes/tamaños.
Migración 24→25 con respaldo y fallo SQL/reversión, preservación de cierre v24,
respaldo/restauración del nuevo circuito y comparación de fingerprint/ZIP aprobados.

Chromium loopback aprobó consulta y respuesta desde UI, autores diferenciados y HTML
inerte, sin errores de página ni peticiones externas. Base, cuenta y servidor de
ensayo retirados. El primer recorrido detectó falta de Content-Type JSON al guardar;
corregido con aserción JS, suite JS completa y recorrido final aprobados. La suite
Python completa aprobó en su primera ejecución; no se repitió por el ajuste exclusivo
JS. La focal inicial tuvo un error en el INSERT del fixture de migración, corregido
sin relajar controles; se quitó la importación que duplicaba pruebas heredadas.
Evidencia local excluida: `.test-results/consultations-python.log`,
`consultations-python-summary.json`, `consultations-node-final.log`,
`consultations-browser.json`, `consultations-browser.png` y `consultations-pip-check.log`.
Los intentos iniciales se conservan. Sólo datos ficticios.
Windows del SHA nuevo, aceptación humana y acceso médico restringido siguen pendientes.
La aprobación Windows de f903bad no se reabre ni se atribuye al nuevo incremento.
No fusión ni despliegue. Los apartados siguientes conservan evidencia histórica.

## Revisión humana RN14 y simulación separada, 29/10/2026

Base a376491354aa90ecf47a328c05eed29860695079, PR #5 en borrador; rama nueva
feat/rn14-human-review con destino feat/hpc-row-applicability. El usuario autorizó
simulación separada, pruebas y publicación con PR borrador; sin fusión ni despliegue.
No se invoca Astra. Windows de a376491 y aceptación humana UI siguen pendientes;
los resultados de versiones anteriores no validan este incremento.

Preview y guardado explícito de un componente total por fila elegible con diferencia
positiva RN14, después de confirmar su hallazgo con evidencia. Reutiliza monetary_gate,
proposal_versions y la entrada de freshness, conservando el formato anterior. La
referencia v3 usa la captura por fila, código completo/equivalencia, versión de valor,
fundamento de aplicabilidad, decisión y evidencia exactas. No relaja el guardador v2.
El ajuste conserva automático, importe revisado, cálculo y fundamento. Descartada/no
concluyente excluyen el componente sin borrar historia; un nuevo fundamento exige
revisión pertinente. No sustituye otros componentes ni genera débitos automáticos.

El modo proviene del servidor y de la declaración A1 persistente. Las simulaciones se
guardan en rn14_simulation_versions, con FK separadas de procedencia, y no se suman a
propuestas/totales reales. API, pantalla, ZIP y cierre exponen sus importes en campos
de simulación DEMO separados. Declarar ficticio un lote no renombra su historia real.
Esquema 24 aditivo, con respaldo/rollback ficticios y protección de historia; no migró
datos operativos. Los cierres anteriores y sus bytes se preservan.

Linux: 282 descubiertas (265 + 17), 280 aprobadas, cero fallos/errores y dos
omisiones Windows AES-GCM/ACL. JavaScript: 56 aprobadas (49 + 7), sin omisiones;
pip check correcto. Venv dedicado reutilizado, sin dependencias nuevas ni locks
modificados. Inventario: 150 entradas, 149 hashes/tamaños coincidentes; históricos
y SOURCE_HASHES preservados. La primera focal falló por un helper de versiones y
se conserva su log; suite completa final aprobada en su primera ejecución.
Chromium loopback completó confirmación del hallazgo, simulación $2, ajuste $1,50
y descarte, sin análisis implícito, importes reales, HTML activo ni peticiones externas.
Cierre/sucesora y respaldo/restauración ficticios conservaron tablas de simulación,
FK de procedencia, fingerprint y ZIP. No certifica Windows, aceptación humana o
recuperación ante desastre. [Paquete y resultados](REVISION_PROPUESTAS_RN14.md).
Los apartados siguientes conservan la evidencia histórica de sus respectivos bloques.

## Aplicabilidad económica HPC por fila, 28/10/2026

Incremento sobre f903bad58c176312e3637fd1394d78d22addc8ec, rama
feat/hpc-row-applicability; base de la PR apilada: feat/new-batch-review.
El usuario informó Windows de f903bad: 248 Python y 43 JS aprobadas, sin omisiones,
pip check correcto y recuperación con/sin proxy con hashes conservados. Es evidencia
de la base aportada por el usuario, no una ejecución propia ni validación del nuevo código.
La aceptación humana de interfaz se difiere al fin de semana; no está aprobada.

Implementados registro versionado de aplicabilidad por fila, permisos/versiones,
dependencias selectivas y resultados RN14/RN15 con fórmula explícita. El catálogo y
las versiones ingresadas siguen siendo candidatos hasta registrar la aplicación
documentada. Guardar no ejecuta análisis ni confirma propuestas o débitos. La nueva
revisión no hereda esa aplicación y la consulta cerrada usa historia sin recalcular.
Un acuerdo específico aceptado identificado se conserva sin cuantificar e impide
sustituirlo silenciosamente por el general. Normas especiales/adicionales fuera del bloque.

Esquema 23 aditivo, sin modificar cierres o referencias anteriores. Respaldo y
actualización offline obligatorios en bases existentes; sólo migraciones ficticias aquí.
Linux final: 265 descubiertas (248 de la base + 17 nuevas), 263 aprobadas,
cero fallos/errores y dos omisiones Windows AES-GCM/ACL. JS: 49 aprobadas
(43 + 6), sin fallos/omisiones; pip check correcto, 21 versiones exactas del lock.
Venv dedicado reutilizado, sin instalación ni descarga nueva ni cambios de locks.
Chromium loopback aprobó guardado sin análisis, cálculo explícito $32−$30=$2,
HTML inerte y retiro/invalidez sólo de la fila dependiente, sin errores de página.
El respaldo/restauración sintético conservó una referencia registrada y el ZIP cerrado.
Inventario vigente: 146 entradas, 145 hashes/tamaños, autoentrada sin autohash;
SOURCE_HASHES y preparación original conservados. Commit funcional validado y subido:
4a0d685053e5f5d9593eec88c750f4a52f4798a7. La creación de la PR borrador fue
rechazada por el control automático por falta de autorización específica, incluso
tras verificar repositorio privado y ausencia de PR. No se creó ni se eludió ese bloqueo;
se requiere confirmación específica para esa escritura remota. El informe final
identifica el último SHA de documentación, con código funcional idéntico. Windows del nuevo SHA,
revisión independiente y aceptación humana siguen pendientes.
Evidencia, fallos iniciales y límites: [paquete económico](REVISION_ECONOMICA_HPC.md).
No se invocó Astra ni se inició un incremento de propuestas monetarias.
Los apartados siguientes se conservan como evidencia histórica de sus respectivos bloques.

## N1/N2 local: transporte y motivos, 28/10/2026

HEAD e3e114b75b67f3872a2780fd039c3d5230b70c90, rama feat/new-batch-review.
Modificaciones locales sin staging, commit, push, cambios de PR, fusión o despliegue.
La publicación fue excluida de este encargo tras su denegación anterior; no se intenta
por otra vía. Paquete actual: [REVISION_N1_N2.md](REVISION_N1_N2.md). Sin datos reales
ni nuevos revisores invocados. El diff y su hash identifican el incremento; no hay SHA nuevo.

Evidencia externa recibida sobre e3e114b: revisión comunicó 243 Python aprobadas,
1 fallo N1 y 2 omisiones Windows de 246; 41 JS aprobadas. Recuperación HTTP local
independiente conservó cierres, historia, hashes y revocación. Windows del usuario:
246 Python y 41 JS aprobadas, pip check y 21 versiones exactas correctos; P01 con
40 conexiones cerradas y cero managers vivos. No son resultados del código local nuevo
ni demuestran el retenedor del antiguo WinError 32.

N1 reproducido: HTTPX heredaba SOCKS y requería socksio opcional. Sin proxies pasó;
con un proxy centinela loopback falló antes del arreglo. Los dos clientes HTTP del
probe ahora usan trust_env=False. Sin cambios globales de proxy ni dependencias;
aserciones, cuarentena, activación, permisos, revocación y hashes conservados.
Dos regresiones ejecutan SU aplicación restaurada con y sin las variables proxy,
con guardia de red externa y cero conexiones al proxy centinela.

N2: descripciones administrativas junto al código original en encabezados y filas
del alcance activo/congelado. Etiquetas conocidas conservan significado/FICTICIO;
códigos desconocidos o ausentes son explícitos, sin inferir rechazo/aprobación.
Renderizado textContent y propiedades propias: constructor/__proto__/HTML literal
no se interpretan. No cambia reglas, fundamentos, API ni ZIP congelados.

Linux: 248 descubiertas (246 + 2 N1), 246 aprobadas, cero fallos/errores y dos
omisiones Windows AES-GCM/ACL, sin fallos esperados ni éxitos inesperados. JS: 43
aprobadas (41 + 2 N2), sin fallos/omisiones; pip check correcto y 21 versiones exactas.
Venv dedicado reutilizado; Python 3.12.14, SQLite 3.53.1, Node 24.19.0, Git 2.52.0.
Sin instalaciones nuevas ni cambios de proxy global/dependencias/locks.
Chromium loopback: motivos administrativos/códigos visibles, filas 2/RN20 y RN21,
ocho fundamentos, confirmación expresa, cierre congelado y dos descargas anteriores
idénticas; sin errores de página. Los temporales y servidor se retiraron.
Inventario local: 142 entradas/141 hashes, autohash excluido; originales históricos
preservados y archivos ajenos rechazados por la verificación. Diff completo y resumen
en .test-results/n1n2-changes.patch y n1n2-summary.json; evidencia previa preservada.

Windows de este diff y aceptación de interfaz con personas pendientes. Pruebas de
navegador no equivalen a aceptación. Se conservan fallos antes de la corrección;
intermitencia histórica de procesos y WinError 32 separados. SOURCE_HASHES.json,
PREPARACION.md, locks y ramas base intactos. No se inicia otro incremento.

## Antecedente: portabilidad y cierre P01 de e3e114b

## Corrección de portabilidad y cierre P01, 27/10/2026

Rama feat/new-batch-review; PR #4 en borrador contra feat/revision-close
(1fe27aad4a364a56f3f45e88667310df08f01310). Base de este bloque:
89571d9d53872c9ae3f5ff870f96f6131665ff08. El informe final identifica el SHA nuevo.
Paquete vigente: [REVISION_PORTABILIDAD.md](REVISION_PORTABILIDAD.md); conserva
como antecedente la matriz y resultados R1–R7 siguientes. No se invocaron revisores,
no se fusiona ni despliega, no se modifica Git global ni las ramas base.

Windows comunicado por el usuario para 89571d9: 239 ejecutadas, 226 aprobadas,
13 errores, cero omisiones; 41 JS, pip check y lock correctos. Doce errores convergen
en la comprobación del inventario de release (once al preparar backup, uno al
inspeccionar el paquete histórico); no son doce restauraciones fallidas independientes.
El restante es WinError 32 al eliminar app.sqlite3 en tearDown de autenticación P01.
Los logs no identifican el retenedor ni prueban conversión CRLF por sí mismos.

La conversión se reprodujo en Git sintético: checkout limpio, core.autocrlf false/true,
blob LF invariable y archive convertido a CRLF. El paquete nuevo enumera el árbol y
lee blobs por OID; conserva hashes estrictos, esquema, historia y control de tipos/rutas.
No se reescribe el inventario a partir de bytes accidentales del checkout.

Dos defectos de recursos se reprodujeron con fallos/barreras deterministas y se corrigieron:
conexión SQLite sin cierre explícito si fallaba un PRAGMA de inicialización; apagado
que retornaba después de join sin comprobar si quedaban hilos vivos. No demuestran
la causa del WinError original. P01 conserva clientes/trabajadores y sus comprobaciones
de autenticación, registra conexiones/hilos antes de limpieza y exige cierre completo.
No se toleran errores de eliminación ni se añaden sleeps o tiempos mayores.

Código/tests: d68faa7c377e83806a5ac212934af27e844688d1. Linux: 246 descubiertas
(239 + 7 nuevas), 244 aprobadas, 0 fallos/errores y 2 omisiones Windows AES-GCM/ACL,
sin fallos esperados ni éxitos inesperados. JS: 41 aprobadas; pip check correcto.
16 focales de empaquetado/recursos/P01 aprobaron. Python 3.12.14, SQLite 3.53.1,
Node 24.19.0; venv aislado reutilizado, 21 versiones exactas, sin instalaciones nuevas.
P01 registró en esta suite 34 conexiones explícitamente cerradas y tres coordinadores
terminados antes de eliminar la base; no es prueba Windows ni de handles externos.
Inventario de 140 entradas/139 hashes generado desde blobs del índice y comprobado
contra el paquete final; autohash excluido. Evidencia portable-* y p01-resources.jsonl
local excluida de Git. No se modificaron los tests de interrupción de procesos.

La focal de procesamiento tuvo dos fallos antes de barreras preparation/publication:
activity_lost en validating, cero filas, proceso terminado con código 0. Ambos pasaron
en ejecución dirigida posterior en serie; no se declara resuelta la intermitencia ni
se relaciona con WinError 32. Se preservaron logs, tiempos, leases y aserciones.

Windows del SHA nuevo, revisión independiente y aceptación de usabilidad pendientes.
Guía: VERIFICACION_WINDOWS.md. Misma máquina no equivale a recuperación ante desastre.
SOURCE_HASHES.json, PREPARACION.md y locks históricos intactos; no se inicia otro bloque.

## Antecedente: R1–R7 antes de la corrección de portabilidad

## Correcciones R1–R7: entrega para revisión, 27/10/2026

Rama feat/new-batch-review, PR #4 en borrador contra feat/revision-close
(1fe27aad4a364a56f3f45e88667310df08f01310). Base auditada:
76f18c37d9601641c555c6f10dae64b0360c8ad2. El informe final identifica el SHA del
paquete completo; código/tests: 8102eaa6aba903725038ed6a0e9250ae62ee45ce.
No se atribuyen estos cambios al commit anterior. Main, MIME,
PR #2 y C1 intactos. Sin fusión, auto-merge, despliegue, datos reales ni revisores
invocados. Revisión independiente final a cargo del usuario.

Paquete vigente: [REVISION_R1_R7.md](REVISION_R1_R7.md), con matriz antes/cambio/regresión,
archivos y decisiones técnicas. R1: formato selectivo closure-input-v2 y captura
compartida. R2: extras preservados/clasificados y snapshot coordinado con publicación.
R3: release con commit/árbol/esquema e inventario, recuperación desde SU código extraído.
R4: miembros paginados y resumen/limitaciones congelados. R5: antecedentes por revisión
con enlace de origen, sin herencia vigente. R6: evento de preparación de respuesta,
no recepción del cliente. R7: snapshot/revalidación de las tres consultas auditadas.

Esquema 22 aditivo, con respaldo y actualización offline de bases existentes.
Migración sintética 21→22, rollback, integridad/FK y cierre real de la versión anterior
comprobados: ZIP histórico idéntico; fundamentos legacy abiertos exigen reconfirmación.
No se migraron bases operativas ni se reescribió historia. Los extras tienen cuarentena
lógica privada, no se borran ni mueven; originales registrados ausentes/alterados siguen
bloqueando el respaldo. Eliminación definitiva fuera del alcance.

Verificación Linux: Python 3.12.14 / SQLite 3.53.1; 239 descubiertas (224 + 15 nuevas),
237 aprobadas, 0 fallos/errores, 2 omisiones Windows AES-GCM/ACL, ningún fallo esperado
ni éxito inesperado. Node 24.19.0: 41 aprobadas (39 + 2 nuevas), sin fallos/omisiones.
pip check correcto; 21 versiones declaradas del lock, venv aislado reutilizado, sin
instalaciones ni descargas nuevas. No se relajó el hook MIME, permisos ni aserciones.

Ensayo integral: rollback postpublicación → extra preservado → conciliación repetible →
cierre → nueva revisión con análisis explícito/decisiones/fundamentos → segundo cierre →
backup → restore → arranque desde application extraída en proceso aislado y loopback.
Cuarentena bloquea antes de activar; activación interrumpida/repetida, sesión antigua
revocada, login nuevo ficticio, permiso viewer denegado y hashes de ambos ZIP intactos.
Dos cierres con backup concurrente y reintento seguro comprobados. Es un ensayo de
misma máquina/runtime; no acredita recuperación ante desastre o equipo vacío.

Chromium real: fila 2/RN20 y RN21 visibles y coincidentes con el ZIP, ocho fundamentos,
confirmación expresa, segundo cierre, descarga seleccionada del primero dos veces
idéntica; historia Confirmada/Descartada de revisiones 1/2 y correcciones con origen.
Sin errores de página; temporales y servidor retirados. Usabilidad pendiente del usuario.

Windows comunicado por el usuario: 224 Python + 39 JavaScript sin omisiones sobre
76f18c37d9601641c555c6f10dae64b0360c8ad2. Es evidencia de C2 anterior; **no valida
R1–R7**. Nueva comprobación Windows exacta pendiente: VERIFICACION_WINDOWS.md (239/41),
incluyendo nuevo cerrojo nativo y AES-GCM/ACL. No se invocó Astra para esta corrección.
La intermitencia histórica de procesos conserva logs y causa no determinada; una pasada
correcta actual no demuestra su eliminación. Evidencia local audit-* en .test-results/,
excluida de Git. Inventario final: 136 entradas/135 hashes, autohash excluido, sin
faltantes ni extras; SOURCE_HASHES.json, PREPARACION.md y locks históricos intactos.

Dictámenes separados: demo sintética comprobada, aceptación de interfaz pendiente;
integración preparada para revisión, sin fusionar; recuperación de misma máquina
comprobada con límites anteriores. No se declara completo ni apto para producción el TP.
No se inicia otro incremento.

## Antecedente: C2 antes de las correcciones de auditoría

C2 implementado el 27/10/2026 en feat/new-batch-review, desde C1
1fe27aad4a364a56f3f45e88667310df08f01310 (PR #3). PR en borrador dependiente,
base feat/revision-close. Código/tests final: f7e45842272a7cd8844951be6a04b7f2beb178df.
Main, MIME, PR #2 y C1 se mantienen intactos. Sin fusión, despliegue, datos reales
ni otros incrementos. Astra/revisión independiente y Windows pendientes por decisión
expresa del usuario; no se invocaron revisores.

## C2: nueva revisión, historia y exportaciones conservadas

| Requisito | Implementado y comprobado con datos ficticios | Límite |
| --- | --- | --- |
| RF16/RN30 | Apertura expresa con motivo, responsable y predecesora cerrada; versiones y unicidad; cierre anterior intacto | No reabre revisiones ni modifica su exportación |
| MD02/MD05 | Una importación y filas originales compartidas; una representación operativa por lote; cantidad no duplicada entre revisiones | No se duplica un Excel como otra facturación |
| MD06/MD07 | Procedencia de apertura y fuentes; decisiones/propuestas históricas identificadas; ningún resultado/decisión heredado vigente; captura antes del análisis explícito | Reconfirmar correcciones, alcances JSON/prestador, vínculos, declaraciones y fundamentos; no hay reutilización asistida entre revisiones |
| MD12/RNF01 | Rol, CSRF/origen, versiones/predecesora y commit atómico; duplicados, obsolescencia y revocación rechazados | Sesiones/permisos existentes, sin nuevas credenciales ni servicios |
| RF12/RN31 | Descarga por revisión y último cierre; dos cierres direccionables; mismo hash tras abrir/reanalizar | Lectura del archivo conservado, no recálculo con fuentes nuevas |
| RN28 | Datos de trabajo separados, consumidores y comparaciones seleccionan revisión actual; capturas cerradas históricas | Reanálisis de la actual siempre explícito; cierres conservan sus limitaciones |

Verificación final: Python 3.12.14/SQLite 3.53.1 Linux, 224 descubiertas = 214 anteriores
+ 9 C2 + 1 diagnóstico de procesos; 222 aprobadas, 0 fallos/errores, 2 omisiones Windows AES-GCM/ACL. Node v24.19.0:
39 aprobadas = 34 anteriores + 5 C2, cero fallos/omisiones. pip check correcto; 21 versiones
exactas del lock. Venv aislado reutilizado, sin nuevas instalaciones/descargas ni cambios a locks.

Migración 21 probada con respaldo ficticio v20, rollback ante SQL inválido, conservación de
valores, integridad y FK correctas. El esquema normal exige respaldo/actualización offline;
no se tocaron bases operativas. La comparación de work_fields en el fixture anterior usa
su clave lógica al ser ahora vista; las demás comprobaciones históricas se conservan.

Chromium en loopback: historial, confirmación de apertura, segunda revisión sin análisis
automático, análisis explícito, dos filas y dos alertas pendientes, captura anterior rotulada
histórica y ZIP anterior idéntico. Sin errores de página; temporales y servidor retirados.
Esto no es aceptación de usabilidad ni acreditación del TP completo.

Investigación de la intermitencia del ensayo de interrupción: la traza original sólo
conservó el timeout del padre; no permite atribuir el motivo de aquella ejecución.
Comparación dirigida C1/C2 con bases nuevas: 10/10 pasan en cada versión; una demora
inducida de 0,75 s después de claim reproduce en ambas la pérdida de vigencia de 0,6 s
antes del primer heartbeat. Quedan interrupted/activity_lost, sin resultados publicados.
Esto demuestra fragilidad preexistente del ensayo, no la causa del fallo original ni
un límite propio de Linux. No hay evidencia suficiente para un cambio de producción.

Ahora el timeout conserva estado técnico y vida/código de salida del hijo sin datos
sensibles. Se mantienen las mismas esperas y aserciones de crash. Una nueva regresión
sin pausas probabilísticas confirma rechazo seguro de una vigencia vencida antes de ejecutar.
Trece pruebas dirigidas de procesamiento y la suite final de 224 pasaron con las dos
omisiones Windows. Se conserva el fallo anterior; no se presenta como resuelto por repetición.

Paquete para revisión humana, comandos, evidencia y riesgos: [REVISION_C2.md](REVISION_C2.md).
Windows debe probar el SHA exacto del informe final mediante [la guía](VERIFICACION_WINDOWS.md).
INVENTARIO.json se actualiza para el paquete; SOURCE_HASHES.json y PREPARACION.md se preservan.
No hay otro bloque de implementación iniciado por continuidad implícita.

## Antecedente C1: registro al cierre de aquel bloque

C1 implementado el 27/10/2026 en feat/revision-close, desde
0d244d28cb56529da53dbf39b3969b291201e94b. Entrega preparada para PR en borrador dependiente
de PR #2, base fix/recovery-review-history. Main, MIME y la rama de PR #2 no se modifican.
Revisión independiente Astra PENDIENTE por decisión explícita del usuario: no se invocó
ningún revisor durante C1. No hay fusión, despliegue, datos reales ni implementación C2.

## C1: alcance implementado y probado

| Requisito | Implementación y comprobación sintética | Límite |
| --- | --- | --- |
| RF11/RN29 | Preview de pendientes/controles/limitaciones; confirmación expresa; cierre bloqueado por alertas pendientes o procesamiento activo | No certifica toda la factura ni aprueba débitos |
| MD08 | Un fundamento versionado por causa/alcance, asociado a todos sus controles, incluso sin resultado; reutilización y confirmación del fundamento vigente | RN20–RN22 se declaran sin implementación y aplicabilidad sin verificar; no se evalúan ni se presentan como no aplicables |
| MD11/MD12 | Manifiesto y archivo privado preparados antes; permisos/versiones/fundamentos revalidados; referencia, estado y auditoría en una transacción | Conflictos/rollback pueden dejar archivo privado huérfano visible, nunca cierre parcial |
| RF12/RN31 | Descarga de bytes conservados, hash verificado, decisiones/propuestas/fuentes/cobertura congelados; sin recalcular con fuentes posteriores | Exportación provisional sigue separada y se rechaza para revisión cerrada |
| RNF01 | Rol de revisión, origen/CSRF y comprobación final de acceso a descarga; respuesta revocada sin evidencia | No cambia el sistema de roles ni habilita acceso médico |
| RF16/RN30 | Se conserva revisión cerrada sin reabrirla | C2 nueva revisión NO implementado ni autorizado en este bloque |

Pruebas finales sobre código/tests dbd8e15fdc67e836751efa9d375b92b7a170788b:
- Python 3.12.14 Linux: 214 registradas (205 anteriores + 9 C1), 212 aprobadas, 0 fallos,
  0 errores, 2 omisiones Windows AES-GCM/ACL; sin fallos esperados ni éxitos inesperados.
- Node 24.19.0: 34 aprobadas (28 anteriores + 6 C1), sin fallos ni omisiones.
- pip check correcto. Sin nuevas dependencias ni cambios a locks.
- Migración aditiva 20 probada con base ficticia v19, respaldo íntegro, rollback ante SQL
  fallido, datos anteriores conservados, integrity_check y foreign_key_check correctos.
  La regresión v18 anterior conserva versión inicial explícita y verifica esquema final.
  No se migraron bases operativas. Bases existentes requieren backup-and-upgrade offline.

Casos: alertas pendientes y fundamentos ausentes bloquean; cierre con controles sin ningún
análisis sólo después de identificar/justificar/confirmar limitaciones; cambio de alcance
invalida fundamento; conflictos de preparación y fallo de auditoría no dejan cierre parcial;
fuente de valores ficticia registrada después no modifica el ZIP; descarga no invoca evaluadores;
escritura sobre revisión cerrada y acceso revocado rechazados. Las aserciones existentes no se
relajaron para obtener aprobaciones. La ejecución inicial de C1 sin rutas dio 404 (reproducción).

La interfaz conserva versiones/alcances en las acciones, descarta respuestas de otro lote,
exige seleccionar expresamente las limitaciones y no reintenta escrituras automáticamente.
Guardar un fundamento conserva borradores de otros alcances sin cambios; conflictos mantienen
el texto y piden actualizar. Refresco/logout/cambio de contexto retiran evidencia anterior.

Chromium real en 127.0.0.1:18766 con datos inventados: login, siete fundamentos compartidos,
siete confirmaciones explícitas, cierre y dos descargas idénticas; sin errores de página.
Base, usuarios, archivos descargados y servidor temporales retirados al terminar. La evidencia
no es aceptación de usabilidad del usuario ni prueba de capacidad máxima.

Evidencia local (excluida de Git): .test-results/c1-python.log, c1-python-summary.json,
c1-node.log, c1-web.log, c1-before.log, c1-targeted-final.log, c1-source-change.log,
c1-browser.json, c1-preview.png, c1-closed.png y c1-inventory-check.json.
Paquete para revisión del usuario: REVISION_C1.md. Windows: VERIFICACION_WINDOWS.md, usando
el SHA completo del informe final, copia nueva y los cinco archivos node:test. Objetivo Windows:
214 Python y 34 JavaScript; todavía no ejecutado. Las dos omisiones Linux no validan equivalentes.

## Entrega y límites

El cierre congela datos, decisiones, versiones de propuestas y cobertura sin ampliar reglas
monetarias. Conserva controles no concluyentes/no ejecutados como tales y no sustituye trabajo
pendiente por aprobaciones. Registro de limitaciones y cierre protegidos como historia inmutable.
La carga máxima de cierre no fue medida: preview y ZIP se construyen en memoria y la confirmación
revalida bajo transacción. Volumen persistente, recuperación externa y caída física siguen pendientes.
No se hicieron cambios en la PC del usuario ni se usaron fuentes operativas.

Inventario de C1: 122 entradas, 121 hashes y el manifiesto sin hash propio. SOURCE_HASHES.json,
PREPARACION.md y todos los locks históricos intactos. Sólo queda la revisión independiente y
la comprobación Windows/aceptación del usuario; no se iniciará C2 por continuidad implícita.
Los antecedentes siguientes conservan la evidencia y pendientes de los bloques anteriores.

## Antecedente: jornada H2/H1/H3 y cierre documental

Jornada del 27/10/2026. Rama fix/recovery-review-history desde da90f51ac1782d9711a4fe8c25e7c5fd85690a5a
(PR MIME #1, en borrador). Main dcaa39174259e8df05cff4f0b2baa81b92beae55 no se modifica.
Reproducciones y verificación exclusivamente con datos ficticios. Aceptación funcional y Windows pendientes.

## Cambios y evidencia de la jornada

- H2: guardia común antes de abrir conexiones operativas; una restauración pendiente/incompleta
  no puede arrancar ni modificar la base. Se exige manifiesto/READY/recibo/evento de activación
  concordantes. Activación revoca sesiones y permite recuperar una interrupción posterior al commit
  con recibo escrito atómicamente. La API respeta workers deshabilitados en directorios restaurados.
  Se verificaron arranque normal, sesión revocada, recibo no confirmado, extracción interrumpida y
  segundo ciclo backup/restore/activate. Los marcadores no son una defensa contra un operador
  capaz de reescribir base y archivos. app/recovery_guard.py y scripts/recovery_data.py.
- H1: alert_detail utiliza una sola captura WAL y revalida permiso/versión antes de entregar.
  Las dos regresiones reproducían respuesta indebida en el código anterior y ahora la rechazan
  (conflicto o sesión revocada). No se generalizó el cambio a practice_detail ni a todas las consultas.
- H3/MD07: migración aditiva 19, tablas analysis_history y analysis_history_results separadas de
  control_runs. Captura durable antes de evaluar; resultados preparados durables antes de publicar.
  Conflictos mantienen respuesta de rechazo y estado histórico. Capturas incompletas pueden quedar
  captured/prepared; nunca se seleccionan como último análisis operativo ni habilitan decisiones.
  La consulta GET paginada requiere reviewer y revalida acceso. Se mantiene el plazo existente de
  publicación antes de persistir resultados y se permite paginar todo el tamaño máximo admitido.
  No se añaden pantalla de historia ni reglas económicas. app/analysis_history.py y app/controls.py.
- Migración: base sintética v18 con usuario/conjunto conservados, respaldo íntegro v18, actualización
  explícita a v19, integrity_check y foreign_key_check correctos. No se migraron bases operativas.
  Las bases antiguas siguen exigiendo backup-and-upgrade offline antes de iniciar la API.

Pruebas nuevas: 6 recuperación, 2 concurrencia de alertas, 5 historia/migración/lease/paginación,
1 recorrido integrado. Resultado final: 205 registradas (191 anteriores + 14 nuevas), 203 aprobadas, 0 fallidas,
0 errores y 2 omisiones Windows; sin fallos esperados ni éxitos inesperados. JavaScript: 28
aprobadas, sin fallos ni omisiones. pip check correcto. Python 3.12.14, Node 24.19.0, Linux.
Evidencia local excluida de Git: .test-results/jornada-python.log, jornada-python-summary.json,
jornada-node.log, h2-before.log, h2-final.log, h1-before.log, h1-final.log,
h3-targeted.log, h3-review-fixes.log y jornada-integrated-test.log.
No hay nuevas dependencias ni cambios a los locks.

Revisión independiente Astra:
- H2 a535acfa y pruebas complementarias 42cb732: sin hallazgos bloqueantes. Limitó expresamente
  la evidencia de interrupción a simulación, no caída física durante escritura del archivo.
- H1/H3 42cb732..5ff56df: dos P2 encontrados (lease al persistir y offset máximo); ambos resueltos
  en 2669b92 y revisados nuevamente sin hallazgos nuevos. Las pruebas son ejecución del agente
  principal; la revisión de Astra es estática. La regresión Windows continúa pendiente.
  La primera suite completa detectó dos regresiones: confusión del manifiesto de respaldo de
  migración con recuperación y preparación del fixture v8 con el evaluador actual. Se corrigió
  la distinción y se preparó directamente la historia v8, conservando todas las aserciones
  originales de preservación/FK/rollback. Cambios 427a3a8/30843ae revisados por Astra sin nuevos
  hallazgos. La primera ejecución fallida se conserva en jornada-full-first*.

## Recorrido y límites de interfaz

Chromium real, loopback 127.0.0.1, cinco filas ficticias: A y C elegibles, I y fuera de período
excluidas, X indeterminada. Excel/A1 se incorporan por API; el catálogo HPC ficticio se registra
con helpers internos y su comparación se comprueba por API. Análisis explícito,
decisión, corrección de cantidad, invalidación RN11, reanálisis y exportación provisional comprobados.
En navegador se inició sesión, seleccionó conjunto/lote, buscó código 123456, guardó una decisión,
recorrió Autorizaciones/Valores/Salida y descargó exportación. Sin errores de página. Usuarios,
sesiones, base y servidor temporales retirados al terminar; ninguna URL pública.
Evidencia local: jornada-browser.json, jornada-integrated.json y capturas jornada-planilla.png,
jornada-autorizaciones.png, jornada-salida.png en .test-results/.
El test tests/test_integrated_journey.py reproduce el recorrido API dentro del runner aislado.
Las capturas no sustituyen aceptación de comodidad por el usuario. No se rediseñó la interfaz.

Decisión para la tarde: el filtro inicial Imágenes puede dejar una vista vacía si no se puede
clasificar el catálogo ficticio. Se comprobó Todas las prácticas sin inferir clasificación.
Recomendación: evaluar una alternativa visible para mostrar todas cuando la clasificación falte;
no cambiar silenciosamente la prioridad de imágenes ya solicitada por el usuario.

## Balance objetivo de interfaz y cierre del alcance autorizado

Revisión de capturas existentes, sin nueva ejecución de navegador ni cambios funcionales:

| Aspecto | Evidencia objetiva | Límite / decisión pendiente |
| --- | --- | --- |
| Navegación | Secciones visibles y pestaña activa en las tres capturas | No acredita navegación por teclado ni accesibilidad completa |
| Planilla | Dos filas elegibles A/C, búsqueda 123456, importes y decisión No concluyente visibles | Cinco filas sintéticas no acreditan comodidad con cientos de casos |
| Motivos/evidencia | Avisos junto a la fila y botón Detalle; protección y contenido de detalle comprobados por tests API | Motivos y etiquetas se truncan visualmente; no se inspeccionó exhaustivamente el detalle en navegador |
| Autorizaciones | Captura recibida identificada y mensaje explícito: importar no ejecuta análisis ni aprueba cobertura | La captura no muestra todo el panel desplazable; no acredita aceptación del formulario completo |
| Exportación | Descarga completada, salida provisional y límites monetarios visibles | No es cierre ni exportación definitiva; mensaje de éxito usa el área de mensajes general |
| Clasificación | Todas las prácticas muestra filas; catálogo ficticio no permite verificar clasificación de imágenes | Conservar la prioridad de imágenes; evaluar alternativa visible cuando la clasificación falte |

Decisiones agrupadas para la tarde: (1) conservar Imágenes como selección inicial y ofrecer
una acción visible Todas las prácticas cuando falte clasificación (recomendado), o mantener
el comportamiento actual; postergarlo no impide pruebas, pero conserva la posible vista vacía.
(2) Evaluar si la densidad, abreviaturas y acceso a Detalle resultan cómodos; recomendación:
revisar las capturas antes de rediseñar, conservando la planilla existente. (3) Ejecutar Windows
sobre el SHA completo del informe de cierre siguiendo VERIFICACION_WINDOWS.md; su resultado
permanece pendiente, no se reemplaza por las dos omisiones Linux.

El recorrido pedido quedó comprobado por evidencia API y navegador complementarias, no por
una carga integral realizada únicamente desde navegador: Excel/A1 por API, registro HPC con
helpers internos y comparación por API, controles explícitos, revisión/decisión, cambio de
cantidad, invalidación RN11, reanálisis y exportación provisional. El código funcional y tests
siguen exactamente en 9577ed8; el cierre posterior sólo completa documentación e inventario.
No se repite la suite por estos cambios documentales. La evidencia Linux corresponde a ese
código y no constituye una ejecución Windows. La guía recibe el SHA completo final del informe
para comprobar el paquete exacto sin seguir ramas móviles ni tocar la copia operativa.
La guía y este balance fueron revisados estáticamente por Astra, sin hallazgos bloqueantes.
El inventario de cierre enumera 117 archivos: 116 hashes comprobados y el propio manifiesto
sin hash. SOURCE_HASHES.json, PREPARACION.md y todos los locks permanecen intactos.

## Cobertura y siguiente incremento

| Área | Evidencia de esta jornada | Pendiente |
| --- | --- | --- |
| RF01–RF04: Excel + A1 + valores | Recorrido integrado sintético, originales/historia conservados | Intercambio real A1, cobertura e identidad documental |
| RF05/RF07–RF09, RN25/RN28: controles y revisión | Análisis explícito, invalidación y decisiones con versiones | Validación de negocio sobre fuentes autorizadas; no todos los requisitos quedan acreditados |
| RF10/RNF05: recuperación | Activación/arranque y ciclos sintéticos | Windows, cifrado/ACL equivalentes Linux, volumen persistente y recuperación externa |
| RF11/RF12/RF16, RN29–RN31/MD11: salida | Exportación provisional con límites y sin aprobación económica real | Cierre formal RN29/MD11, salida cerrada y nueva revisión RN30 |
| RF14/RN27: dinero | Se conserva la separación entre decisiones y respaldo económico | Aplicabilidad económica y aceptación de cálculo; sin débitos automáticos |
| RNF06: interfaz | Planilla/secciones existentes comprobadas en Chromium | Aceptación/usabilidad y preferencia del filtro inicial |

Siguiente bloque propuesto, sin implementarlo aquí: especificar cierre/revisiones contra RN29,
RN30 y MD11 antes de ampliar funciones. El extracto del TP no sustituye casos de uso y criterios
completos ausentes; consultar el original privado sólo con acceso autorizado y para la duda concreta.
La prueba Windows debe usar el SHA completo del informe final y la guía VERIFICACION_WINDOWS.md
en una copia nueva; incluye comprobación de checkout, instalación, criterios y evidencia a devolver.
No hay CI versionado para esta entrega; los resultados informados son comprobaciones locales.
SOURCE_HASHES.json y docs/PREPARACION.md permanecen como evidencia histórica, sin cambios.

## Antecedente: corrección MIME y diagnóstico Linux

Actualización del 27/10/2026: corrección local del runner Linux en revisión, sin integración
ni publicación. Base Git dcaa39174259e8df05cff4f0b2baa81b92beae55; rama fix/linux-mime-runner.
La aceptación funcional del usuario y la validación operativa siguen pendientes.

## Reproducibilidad Linux y corrección MIME

El diagnóstico sobre la base descubrió 178 entradas: 172 aprobadas, 4 errores y 2 omitidas.
Un error de importación sustituyó las 12 pruebas de test_agreement_review; no se ejecutaron.
OpenPyXL y FileResponse intentaban inicializar mimetypes leyendo /etc/mime.types, rechazado
por el hook de aislamiento. Se reprodujo tanto en el venv recibido como en uno nuevo.
No se recuperó el contenido del ajuste install_script/start_skill del onboarding: no se
certifica ese ajuste ni se lo necesita para ejecutar la corrección versionable actual.

scripts/run_synthetic_tests.py inicializa la tabla incorporada de Python sólo en Linux,
después de instalar el hook, vaciando knownfiles y reconstruyendo la tabla con init().
init([]) por sí solo no evita knownfiles en la primera inicialización de Python 3.12.
No se ampliaron rutas permitidas, desactivaron controles ni cambiaron pruebas existentes.
La configuración queda dentro del proceso de pruebas; no modifica el servidor ni Windows.

Se añadieron dos regresiones en tests/test_synthetic_runner.py: procesos independientes
con MIME frío y preinicializado/alterado. Ejecutan main con su hook real y una suite acotada
para no recursar; sólo sustituyen discovery y la ubicación de sus logs temporales.
Comprueban OpenPyXL en memoria, HTML/CSS/JS servidos, tipos PDF/JSON/ZIP y rechazo explícito
de lectura/escritura/eliminación externas y escritura en la instalación del intérprete.
No leen archivos privados; los intentos negativos usan rutas sintéticas inexistentes.

Verificación completa: Python 3.12.14, Linux x86_64, Node 24.19.0, SQLite 3.53.1, pip 25.0.1.
Venv independiente .tmp/validation-venv, sin system-site-packages, preparado en el diagnóstico
con pip install --no-cache-dir --index-url https://pypi.org/simple -r requirements-lock.txt:
21 wheels descargados, 21 versiones exactas del lock, sin dependencias nuevas ni cambios al lock.

Comandos ejecutados desde la raíz:

```sh
.venv/bin/python -B -m unittest tests.test_synthetic_runner -v
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

Resultado del runner: 191 pruebas descubiertas/registradas (189 originales + 2 regresiones),
189 aprobadas, 0 fallidas, 0 errores, 2 omitidas, 0 fallos esperados y 0 éxitos inesperados.
Las 12 pruebas antes bloqueadas volvieron a ejecutarse. JavaScript: 28 aprobadas, sin fallos
ni omisiones. pip check: sin requisitos incompatibles. Evidencia local excluida de Git:
.test-results/linux-mime-python.log, linux-mime-summary.json y linux-mime-node.log.

Las omisiones Windows de AES-GCM y ACL NTFS no validan equivalentes Linux. No se ejecutó
Windows después del cambio; se conserva su camino de inicialización, pendiente de regresión
allí. El hook sigue sin aislar auxiliares nativos/subprocesos de forma general.
El diagnóstico previo comprobó arranque/reinicio básico en loopback con SQLite temporal,
sin usuarios, pero no acredita persistencia durable, recuperación externa ni concurrencia real.
No se usaron fuentes reales ni se publicaron servicios o cambios remotos.

Siguiente tarea: revisión independiente del diff y comprobación Windows antes de integrar;
validación de recuperación/permisos Linux y configuración operativa permanecen como bloques
separados. Este resultado acredita la reproducibilidad sintética, no el proyecto completo.

Ajustes de revisión: ZIP conserva application/zip estricto en Linux; sólo Windows admite
además application/x-zip-compressed, sin modificar su registro ni inicialización.
INVENTARIO.json describe el paquete vigente: 110 entradas, 109 hashes y el propio inventario
sin hash, conservando la convención original. Se actualizan tamaños/huellas de los archivos
modificados y se incorpora la regresión nueva; no se incluyen temporales ni resultados.
Los metadatos de preparación originales quedan identificados como históricos en el inventario;
SOURCE_HASHES.json y docs/PREPARACION.md permanecen intactos. El manifiesto original completo
se conserva en el commit base indicado. No se ha ejecutado una regresión Windows.

## Antecedente: preparación Windows del 26/10/2026

Preparación del 26/10/2026. Esta es la única fuente de estado de esta copia; no reemplaza el
estado privado del proyecto original. Requisitos especificados en REQUISITOS_TP.md;
implementación trasladada sin cambios funcionales; aceptación de usuario y Linux pendientes.

Suite sintética Windows final: 189 aprobadas de 189 ejecutadas; 0 fallidas, 0 errores,
0 omitidas, 0 fallos esperados y 0 éxitos inesperados. Incluye los tests de cifrado y ACL de Windows.
No se modificaron resultados esperados ni se desactivaron controles.
JavaScript: 28 aprobadas, 0 fallidas, 0 omitidas. pip check final aprobado. pypdf en memoria aprobado.
Sintaxis de 73 archivos Python y creación de temporal padre ausente comprobadas.

No ejecutado: Linux, instalación limpia desde índice (DNS bloqueado), navegador interactivo,
publicación, datos reales, cotejo con PDF reales, recuperación externa y acceso remoto multiusuario.
Dos intentos iniciales Python interrumpidos por bloqueo del socket interno de asyncio no tienen
resultado funcional y no cuentan como aprobados. Ver PREPARACION.md.

Siguiente tarea indicada en esa preparación: probar esta misma copia con datos sintéticos en el entorno Linux elegido,
sin reemplazar el lock Windows ni desactivar pruebas o controles. Configuración de nube y accesos
requiere una tarea posterior autorizada. No se creó repositorio ni se publicaron archivos.


## Incremento HPC B1–B3 · 2026-11-07 · copia derivada de 717c81a

Implementado sin migración ni modificación de datos reales:
- Comparación exploratoria: filtrar vigencias antes de resolver ambigüedad; fechas ausentes son indeterminadas, no fuera de convenio.
- Separación del importe registrado visible y la tarifa evaluada/aplicabilidad. Los metadatos nuevos de presentación quedan fuera de la base firmada de referencias; no alteran confirmaciones guardadas ni habilitan débitos.
- Panel de alcance HPC: consulta/historia y confirmación explícita de administrador para lote+fuente, conservando unidad sin verificar. Control optimista de versiones, no escritura en revisión cerrada, protección contra doble clic, navegación tardía y guardado incierto. No ejecuta análisis.
- Clasificación de vista: código completo de orden HPC o nombre exacto del catálogo normalizado por acentos, puntuación, espacios y mayúsculas. Conflicto de evidencias = sin clasificar. No usa prefijos, semejanza ni palabras sueltas; no crea equivalencias económicas, autorizaciones o vínculos. La procedencia de clasificación se devuelve por fila.
- Agrupación visual por afiliado: total y posición sobre todo el resultado filtrado, con continuación entre páginas. Sin identificador no se agrupan personas por nombre.

Verificación reproducible: `python -B -m scripts.run_hpc_delivery_tests` dentro del entorno virtual, y `node --test tests/web_*.test.cjs`. La selección Python conserva las barreras del runner sintético y registra los IDs exactos. Excluye expresamente un caso de ZIP cerrado que requiere Git ausente de la entrega original; en una ejecución previa ese caso produjo error de infraestructura, no un fallo de aserción. El resto de la suite no se presenta como ejecutado.

Pendiente: validación visual y Windows, cobertura de clasificación de la factura real, reglas faltantes de nombres/equivalencias con evidencia, autorización e informes reales, edición masiva porcentual/alta/baja de prácticas. No se afirma que la factura esté auditada ni que el prototipo entero esté listo. Los datos y la base local permanecen en Windows.


### Revisión correctiva R2 · 2026-11-07

Responde al informe de revisión del paquete B1–B3 (SHA256 365c8cd0…): se reprodujeron truncado de instalación, pérdida de edición ajena en rollback, unidad/fuente no visibles y salto de fila por paginación al cambiar versión.

- El instalador del nuevo paquete prepara y verifica cada archivo, sincroniza su escritura y sustituye con `os.replace`. Revalida el destino inmediatamente antes. La reversión automática sólo trata archivos sustituidos por esa ejecución y conserva contenido inesperado. Restauración reanudable, también revalidada antes de cada sustitución o eliminación. No se promete transacción global ni inmunidad a escritores simultáneos: servidor y editores detenidos.
- Importe registrado muestra unidad declarada, moneda cuando consta, fuente, corte, SHA y fechas. Una versión por hora conserva ese rótulo aunque no sea aplicable por práctica. La aplicabilidad y su impedimento siguen separados.
- Al cambiar versión entre páginas se reinicia en página uno con aviso explícito, para no saltar filas que sigan cumpliendo el filtro.
- La clasificación por nombre ahora normaliza únicamente mayúsculas, acentos y espacios: conserva signos y puntuación. Dos áreas distintas, incluso ambas fuera de Imágenes, son ambiguas y quedan sin clasificar. Esta regla sustituye la normalización de puntuación documentada en B1–B3.
- La confirmación directa de alcance por API admite sólo HPC. La consulta de historia permite preparar explícitamente un reintento incierto, relee versiones y requiere nueva confirmación; no reenvía por sí sola.

Validación enfocada: 62 Python y 91 JavaScript aprobadas; selección y logs en paquete. Continúa excluido un caso de cierre dependiente de Git ausente del ZIP. Se añaden pruebas stdlib de instalación/restauración con cortes abruptos y cambios de terceros. No se hizo una nueva prueba Windows ni interacción real de navegador. Los resultados Windows 61/88 del informe corresponden al paquete anterior, no certifican R2.


### Revisión correctiva R3 · 2026-11-07

Reproducidos con fixtures: la referencia original con factor NBU cotejado declaraba ARS/por práctica sin confirmación explícita; amount_cents='S/D' de un catálogo registrado con el validador anterior causaba InvalidOperation al abrir su ficha. Los ensayos negativos de registro comprobaron que también aceptaba NULL, fracciones y valores negativos.

Corrección: el original no declara moneda ni unidad sólo por tener rate_ars/factor NBU. La presentación toma esas declaraciones de una confirmación de aplicabilidad vigente, o mantiene las declaraciones de una versión documentada explícita. Candidato y aplicación siguen separados. No se añadieron campos a la base firmada válida ni se migró la base.

Los registros nuevos V1 exigen amount_cents almacenado como INTEGER no negativo y rechazan con localizador antes de publicar archivos/registro. Para fuentes ya registradas no se reescribe ni revalida destructivamente el original: su ficha conserva literal, hash, corte y localizador, y muestra importe no interpretable sin convertirlo en cero. Comparación y valoración bloquean cálculo para tipos inválidos. Se preservan fuentes previas y firmas de referencias válidas; no se crean propuestas ni confirmaciones durante la consulta.

Las regresiones legacy son exclusivamente ficticias: simulan un registro hecho con el validador anterior y verifican hashes antes/después. Se amplía la selección enfocada con test_p03 para cubrir el registro y consultas V1. No hay nueva validación Windows ni datos reales en este incremento. La inconsistencia entre versiones del convenio en búsqueda/comparación/valoración queda para el siguiente bloque de resolver efectivo común.


Cierre de regresiones R3: 73 Python, 94 JavaScript y 9 pruebas de instalador aprobadas. Se cubren además BLOB e infinitos de fuentes legacy: representación JSON-safe únicamente en memoria con tipo/literal o tamaño+hash, sin modificar objetos. Ficha, búsqueda, historia y comparación permanecen consultables y no cuantifican esos datos. Las confirmaciones históricas explícitas se conservan con etiqueta histórica, sin declararlas vigentes; una confirmación de otra fuente no acredita el candidato seleccionado. Un ensayo de presentación congelada simula sólo el estado de la vista en fixture, no sustituye el caso de cierre completo excluido por Git.


## Bloque B4 · resolver efectivo HPC y nomencladores neutrales · 2026-11-07

Implementado sin migración de esquema:
- `EffectiveHpcValues` resuelve versiones documentadas y valores originales para una fecha. Búsqueda, comparación y referencia económica lo comparten. Una versión tiene su propio inicio, sin quedar recortada por la fecha final del valor original; futuras versiones no se aplican antes de su fecha. Corrección de la misma fecha usa el ordinal más reciente, conservando historia.
- Una versión de importe fijo documentado no depende de que el original tenga fórmula NBU. Se verifica documento/hash, identidad de arancel y unidad; la aplicabilidad por fila sigue requiriendo confirmación explícita. Versión por hora no se compara como por práctica. Respaldo roto bloquea la versión y no hace fallback silencioso al original. Distintos registros de arancel activos siguen siendo ambiguos.
- Se conserva la procedencia opcional de factor de versiones antiguas para no cambiar bases firmadas por ese motivo. Comparación contra módulo R3 congelado en fixture: misma base/hash y confirmación R3 aún vigente. No reescribe referencias ni análisis.
- Clasificación visual incorpora códigos exactos NOMENCLADOR/nomenclador y componente seed.nomencladorImagenes, sin recortar ni traducir códigos, y sin usar importes, practiceIds o equivalencias pendientes del componente. Cada coincidencia muestra traza de fuente/localizador. Colisiones de áreas y nombres ambiguos permanecen sin clasificar. Nada de ello crea una equivalencia económica o una autorización.
- La búsqueda requiere fecha para mostrar una referencia efectiva; conserva el valor original separadamente. La comparación muestra la versión usada. La ficha de versión no hereda una fecha final incompatible del original.

Ensayos sintéticos integrados incluyen precio fijo noNBU con original vencido: búsqueda14.00, comparación28.00 para cantidad2 frente a32.00 (diferencia4.00), y ficha14.00 con la misma versión. No se crearon análisis/propuestas durante consultas. Se conservan diferencias entre seleccionado, aplicable y decidido.

Prueba de navegador preparada con copia ficticia aislada. No pudo ejecutarse: bundle Playwright ausente y Chromium instalado bloqueado por socket local EPERM incluso con ejecución escalada soportada. Servidor ficticio detenido. No se declara validación visual ni Windows. Continúan pendientes actualización porcentual, altas/bajas de prácticas, documentos individuales reales y cobertura integral de factura.

## Adjuntos documentales por fila (esquema 28, implementación cloud)

- PDF de informe o autorización aportado por operador, máximo 10 MiB, original privado por SHA-256 y localizador de fila/importación/revisión. La autorización PDF no sustituye la importación estructurada A1.
- Historia append-only y constancias de lectura manual con autor/fecha. Estados: no aportado, aportado sin revisar, lectura manual registrada. No acreditan autorización ni realización ni generan controles/débitos.
- Permisos reviewer/admin, CSRF, versiones optimistas, comprobación de integridad, idempotencia ante reintento exacto y rechazo de cambios en revisión cerrada. Nombre nunca usado como ruta; descarga attachment con nosniff/no-store; sin previsualización activa/OCR.
- La bandeja muestra el estado de informe y abre panel de originales/historia. Respuestas tardías no se aplican a otra fila; reintento conserva contenido y clave, un conflicto exige actualizar.
- ZIP provisional/cierre incluye `row_documents.jsonl`, originales únicos por hash, metadatos/historia y manifiesto. Cierre conserva bytes aun si la fuente externa cambia; corrupción previa bloquea cierre. Dependencias documentales del cierre incluyen adjuntos y lecturas, sin aprobar RN20–RN22.
- Migración 28 se combina con estado de valores HPC. Base existente exige backup y upgrade offline explícito; nunca actualizar automáticamente al iniciar sobre datos reales. Pruebas usan sólo fixtures ficticios.
- No se afirma inspección clínica ni validación Windows/navegador real. PDFs sólo comprobados por firma/marcador final y hash, no escaneados contra malware; abrir con lector actualizado.

## B5 · administración HPC e informes por fila (2026-11-07)

- Porcentaje con preview ligado a versión/hash, Decimal HALF_UP visible, aplicación atómica e historia por operación. Original requiere declaración expresa ARS/unidad/PDF; sin inferencia automática ni modificación de originales.
- Baja/reactivación fechada con respaldo, historia append-only y resolver común. Sólo bajas verificadas se excluyen de candidatos activos; respaldo ilegible bloquea. Afecta referencias económicas actuales, no controles aritméticos independientes.
- Adjuntos PDF por fila y lectura manual; estados no_aportado/aportado_sin_revisar/revisado_manualmente. No acreditan autorización ni realización clínica. ZIP cierre conserva originales/hash/historia.
- Migración28 conjunta. La base existente exige backup-and-upgrade offline; instalador código no abre ni migra bases. Restaurar código27 tras migrar28 requiere restauración coherente de base/objetos desde respaldo, no downgrade automático.
- Pendientes altas de nuevas prácticas, validación Windows/visual y aceptación operativa real. No se declara la visión completa terminada.

### Bandeja: filtros documentales independientes

- Filtros de informe PDF y autorización PDF por estado de aporte/lectura; no se confunden con A1, aprobación ni cumplimiento clínico.
- Resumen agregado acotado al import y ordinal de revisión antes de filtrar/paginar. Tres consultas SQL constantes, sin consultas por cada fila ni lectura de archivos. Se conservaron permisos y revalidación de versión posterior a snapshot.
- Conteos/pacientes/páginas reflejan filtros combinados; selectores reinician paginación y selección. No aportado sólo significa que no hay PDF vinculado, no que no exista informe o prestación.
- Verificación aislada: 22 Python (4 nuevos más bandeja/adjuntos), 108 JS (2 nuevos); sin datos reales ni QA visual Windows.

## B6 · prácticas propias HPC (2026-11-07)

- Identidades UUID propias, código completo/descripción/familia inmutables, versiones documentadas ARS/unidad/importe/estado/fecha/PDF. No se reescribe V1 ni se inventa una secuencia de catálogo.
- Búsqueda exacta por código y listado por código/nombre exacto, clasificación declarada con trazabilidad; búsquedas por nombre nunca se usan como equivalencia económica.
- Resolver único para lookup, comparación y aplicabilidad. Alta vigente usa únicamente colisión de código completo de catálogo. Antes de la primera vigencia propia se conserva el contrato legado para no invalidar referencias anteriores. Baja vigente/corrupción no habilitan fallback al legado.
- Históricos, actualización individual, baja/reactivación y exportación de JSONL/PDF en captura y cierre. Los importes propios admiten actualización individual y porcentual con UUID explícito; una selección mixta V1/UUID se aplica en una sola transacción y conserva la historia común.
- Mig29 aditiva con guard offline y backup. Se prueba rollback desde28, integridad y conservación de confirmaciones B5 sin cambios. Sin ejecución real Windows/navegador ni aceptación con datos reales.

## Bandeja · referencia y diferencia exploratorias

Columnas separadas muestran referencia y diferencia para revisión, con fuente/hash y declaraciones de moneda/unidad o pendientes. Reutilizan comparación exacta/resolver y la fuente HPC confirmada del lote; no modifican RN14, decisiones ni débitos. Revisión cerrada no consulta valores actuales. Filtro separado de diferencias/coincidencias/sin comparación determinada se aplica antes de paginar, con catálogo/resolver únicos; filtros normales sólo comparan la página. Una diferencia roja sigue siendo candidata condicional, nunca un débito automático. Sin datos reales ni validación visual Windows.

## B7 · enlaces declarados HPC, no equivalencias aprobadas

- Sugerencias por cadena explícita código completo HPC/orden → práctica coherente seq/id única → código HPC/convenio → arancel HPC. No se truncan códigos, agregan ceros, comparan nombres ni usan prestadores ajenos o nomenclador neutral como equivalencia.
- Se conserva código de orden y de arancel, códigos seq, práctica, fuente/hash, documento/página declarados, importe literal y fechas. La relación permanece sin verificar clínicamente; la sola metadata del PDF no acredita lectura de sus bytes.
- Lookup y bandeja muestran candidatos cuando falta coincidencia exacta. No se inyectan en los controles ni en la referencia económica por fila. No hay escritura de mappings ni nueva migración.
- Diferencia exploratoria sólo si existe una versión arancelaria documentada verificable ARS/por práctica y unidad de facturación declarada explícitamente para el lote con nota y hash del Excel original. Si falta unidad/documento, hay colisión, norma especial, baja o importe ilegible, sólo se muestran referencia y motivo, sin diferencia. No es débito ni aprobación clínica.
- Pruebas ficticias del enlace, rechazos, temporalidad, cálculo14×2 frente32, ausencia de escrituras y UI. Aceptación Windows/visual pendiente.

## B8: respaldo documental global (exploratorio)

El administrador puede declarar moneda/unidad y respaldo del importe de un conjunto explícito de tarifas HPC de una fuente inmutable. PDF, página, extracto, condiciones, fechas, autor, SHA del catálogo, SHA del PDF y conjunto de identidades quedan registrados. El conjunto no incorpora altas futuras. Sólo importes directos: cálculos NBU/especiales requieren evidencia específica y no se habilitan mediante este panel.

Se previsualiza y confirma por hash. Retiro conserva historia y bloquea reutilización automática. Reemplazo de declaración activa conserva el conjunto. Tras retiro explícito puede declararse un subconjunto enlazando la retirada mediante replaces_id, nunca agregar tarifas ajenas. Las omitidas siguen retiradas; no recuperan respaldo automáticamente. Nuevas declaraciones superpuestas sin ese enlace se rechazan. Las declaraciones sólo alimentan vínculos exploratorios B7; no modifican RN14, referencias por fila ni decisiones monetarias. El alcance del lote debe declarar la unidad de cantidad antes de calcular diferencias. Revisiones cerradas no se recalculan; el cierre incluye la historia documental.

Migración de esquema 29 a 30: con servidor detenido, ejecutar el comando existente `python -m app.cli --data-dir "RUTA_DE_LA_COPIA_DE_DATOS" backup-and-upgrade`. El comando genera y verifica respaldo antes de migrar; el arranque normal rechaza migración implícita de bases anteriores. No migrar la única copia ni restaurar sólo código sobre base esquema30. Validar primero en copia aislada.

## B9: referencias calculadas del nomenclador de imágenes

Lectura separada de `seed.nomencladorImagenes`, sólo por código completo exacto. Namespace `calculated_nomenclature_references`, sin crear tarifas, identidades HPC ni equivalencias. Se conserva origen (fuente/hash/componente/índice/fila), fórmula, factores, coeficientes, importe registrado, cálculo Decimal exacto y cotejo técnico ROUND_HALF_UP a dos decimales. Este redondeo es únicamente un control aritmético, no una regla contractual acreditada.

Aparece sólo cuando no existe tarifa exacta y no hay vínculo HPC declarado a tarifa. Una referencia exacta o relacionada ambigua, retirada o corrupta no se sustituye por el nomenclador. Duplicados, contradicción de coeficientes, importe inválido/desigual y fechas ausentes se muestran con estado explícito; ningún dato inválido se transforma en cero. Norma, unidad arancelaria, forma de facturación y equivalencia se conservan literalmente como declaraciones del componente, potencialmente incompletas, no conclusiones verificadas.

No atribuye ARS, unidad facturable, respaldo documental de factores, equivalencia clínica ni aplicabilidad económica. No multiplica por cantidad facturada ni calcula diferencias/débitos. No modifica RN14, decisiones, fuentes ni esquema (permanece30).

Comprobación de sólo lectura del componente original:261 códigos/261 filas, sin duplicados.249 importes coinciden con cotejo técnico;12 importes registrados difieren en menos0,01 del cotejo ROUND_HALF_UP. Se preservan y señalan discrepancias, sin cambiar catálogo ni afirmar cuál redondeo contractual corresponde. Hash original intacto. Esta comprobación no es una auditoría de prestaciones ni usa filas nominativas.

## B11 · Cotejo guiado de informes (2026-11-07)

Implementado como ayuda de lectura humana dentro de los PDF de informe por fila:
identidad, fecha, estudio, región, cantidad y mención de contraste se registran por
separado. Por defecto todas quedan «No evaluado». Para cualquier dimensión leída
se exige constancia breve con evidencia y página del PDF en campo separado; una afirmación de
compatibilidad no sustituye la confirmación documental del vínculo. El operador
puede registrar discrepancia o resultado no concluyente. No hay OCR ni evaluación
clínica automatizada. La disponibilidad de un PDF no prueba cobertura exhaustiva.

La ficha genera una constancia textual en el historial inmutable ya existente;
reutiliza permisos, versión, idempotencia, integridad del original y exportación
del cierre. No agrega esquema, tabla, control ejecutado, alerta ni débito. Las
constancias simples anteriores siguen disponibles e intactas. RN20–RN22 siguen
sin ejecución automatizada: esta ficha NO cambia su estado ni convierte lectura
en cumplimiento. La mención de contraste no acredita cantidad ni importe y su
omisión no prueba que no se administró.

Pruebas: 140 JavaScript aprobadas, incluidas seis nuevas de ficha, valores por
defecto, evidencia obligatoria, límites y reintento exacto. Pruebas Python
focalizadas del servicio de documentos se detallan en el informe del bloque.
Pendiente: aceptación visual Windows; captura A1 real; conciliación documental
sobre muestra real con operador. B10 y fuentes/base reales permanecen intactos.

### 2026-11-07 — Declaraciones explícitas por ítem en CSV (delta sobre B15)

El adaptador HPC CSV v2 reconoce solamente un bloque «Resolución por ítems» al
inicio del motivo de un evento válido. AUTORIZAR y NO AUTORIZAR requieren un
código completo único entre las prácticas de la orden. No hereda el estado global,
no recorta códigos y no elige entre declaraciones repetidas o contradictorias.
Cláusulas ambiguas bloquean la publicación de decisiones individuales del bloque.
CORRESPONDEN/NO CORRESPONDE con DER conserva evidencia de derivación separada,
nunca autorización. El manifiesto guarda registro CSV lógico, evento, código,
posición de ítem, fragmento, offsets de caracteres Unicode y SHA-256 del original.

La señal de factura sólo usa una correspondencia compatible y vigente mediante
la barrera ya existente. No crea decisiones humanas, débitos, precios o cantidades.
No migra ni modifica capturas previamente registradas: para incorporar esta nueva
interpretación hace falta preparar una nueva versión de la fuente por el flujo
controlado, conservando originales y dependencias. No se reimportó la base real.

Verificación: 86 pruebas Python focalizadas de importación CSV, extracción,
correspondencia, controles y señales aprobadas; revisión independiente adversaria
con correcciones de contexto y límites del código. Prueba de lectura real agregada:
2470 órdenes, 3693 ítems; una declaración de autorización, una de no autorización,
3691 indeterminados; derivación 13 incluidos, 3 excluidos y 2 indeterminados. Estos
recuentos no representan correspondencias acreditadas con filas de factura.
Pendientes: aceptación visual Windows y revisión humana de las correspondencias.

## B16 — reinterpretación CSV inmutable (2026-11-07)

Integrado adaptador CSV v2 y flujo explícito de nueva interpretación de originales ya importados. Esquema31; migración offline con respaldo, capturas y fuentes versionadas sin duplicar original. Ver docs/REINTERPRETACION_CSV_B16.md. No sustituye selección ni reanaliza automáticamente. No modifica cierres o decisiones. Validación histórica usa derivados registrados y hashes propios. Rechaza recepción antigua que desplazaría una más reciente. Revisión independiente y ensayo real aislado completados; no es validación Windows ni aceptación visual.

## Validación de recorrido y rendimiento posterior a B16 (2026-11-07)

En copia aislada se corrigió el armado del panel: las observaciones de resolución
se obtienen solo para las filas de la página, después de aplicar filtros y ordenar,
y reutilizan el resumen de frescura calculado dentro de la misma transacción.
Antes se preparaban para todas las 13.005 filas incluidas y se recalculaba la
frescura dos veces. No hay caché entre solicitudes, cambio de criterio ni cambio
monetario. Las facetas y los recuentos siguen calculándose sobre el alcance entero.

73 pruebas Python focalizadas aprobadas. Ocho respuestas completas de la copia
real coincidieron por SHA-256 antes y después, incluyendo paginación, agrupación,
criterios ANY/ALL, diferencias, indeterminadas y excluidas. En este equipo cloud,
sin profiler, las consultas pasaron de 3,87–4,74 s a 2,11–2,47 s; es medición local,
no garantía de rendimiento Windows. Se conservaron 357 imágenes y ninguna
diferencia económica determinada en la fuente ensayada: no se confundió la falta
de evidencia con igualdad de valores. Sin cambios en originales, red ni débitos.
La aceptación visual Windows sigue pendiente.

## B18 — vista de imágenes y candidatas (2026-11-07)

El selector de prácticas incorpora «Imágenes + posibles imágenes por revisar».
La vista estricta de imágenes permanece intacta. La nueva vista reúne las filas
clasificadas como imágenes y la lista de posibles imágenes ya señalada para
revisión; no reclasifica esas candidatas, no crea equivalencias y no cambia
valores, autorizaciones ni decisiones. El contador informa cuántas candidatas
quedan entre las prácticas sin clasificar y dónde encontrarlas. No se amplió
la lista de códigos candidatos ni se interpretaron prefijos como equivalencias.

La nueva vista respeta los demás filtros, orden, paginación y alcance. Si el
catálogo falta o su integridad falla, no muestra candidatas como verificadas.
Las candidatas siguen en «Prácticas sin clasificar» y mantienen su advertencia.

Ensayo de clasificación de solo lectura en copia real: 357 imágenes y 32
candidatas, 389 filas accesibles con la vista ampliada. Se mantienen 1.850 sin
clasificar y 10.798 de otras áreas. No se han resuelto clínicamente esas 32
candidatas. Hash de la base conservado, sin red, sin identificadores en resultados.
Pruebas y selección exacta: .test-results/b18-*. La aceptación visual y Windows
siguen pendientes; no se instaló sobre el equipo del usuario.

Verificación B18: 327 pruebas Python y 145 JavaScript aprobadas, sin fallos ni
omisiones dentro de la selección. Se mantiene excluida la prueba económica de
cierre que requiere historial Git; no se ejecutó la suite completa ni navegador.

## B18-R19 — Cierre de Imágenes por el auditor (Windows, copia separada)

Implementado a partir de R18. Las decisiones administrativas entregadas no se editan.
Solo el auditor asignado al conjunto puede cambiar importe o fundamento y confirmar el
total de esa revisión. No tiene que repetir decisiones con las que coincide. El resumen
muestra el total de factura como contexto y calcula el facturado y el neto de todas las
Imágenes incluidas, también las que no generaron observación. Los ajustes guardados
conservan autor, fecha, importe y motivo sin sobrescribir los anteriores. El cierre
revalida el alcance y la evidencia, comprueba la versión y el importe mostrado,
y congela el Excel junto con el estado de la revisión en una transacción.
Una confirmación repetida no crea otro cierre. No hay envío ni aplicación institucional.

Cambios: esquema 37 y servicio de cierre en app/db.py y app/invoice_audit.py; rutas,
pase, alcance de Imágenes y lista de facturas en app/api.py, app/invoice_handoff.py,
app/practice_board.py y app/service.py. Interfaz en web/invoice_audit.js,
web/invoice_handoff.js, web/app.js, web/workbench.js, web/index.html y web/style.css.
Demo y verificación en scripts/create_review_journey_demo.py, scripts/verify_r19_audit.py,
tests/test_invoice_audit.py y tests/r19_browser_smoke.cjs.

Probado en esta copia y con datos ficticios: 52 pruebas Python seleccionadas y 158
JavaScript aprobadas (sin fallos ni omisiones dentro de la selección), además de un
recorrido completo en navegador Windows con descarga y lectura del archivo. Hubo
un único cierre ante dos confirmaciones simultáneas. Se verificaron denegación por
rol, ajuste desactualizado, fallo en la creación del Excel con reversión, evidencia
alterada, cierre por cero y descarga repetible. El recorrido comprobó dos TAC de
450.000 ARS; la primera cambió de 250.000 a 200.000, la segunda quedó en cero,
el neto fue 700.000 y el Excel conservó una fila debitada. El cierre persistió
al recargar. Artefactos en .test-results-r19/python-summary.json, js.log y
Debitos-TAC-ficticias.xlsx. No se ejecutó la suite Python completa, no se migró
una base anterior ni se hizo aceptación con operadores o datos reales.

Siguiente paso: [probar la demo preparada](PRUEBA_CIERRE_R19.md) con demo-auditor.
La demo manual de .tmp/demo-cierre-auditor sigue en auditoría; cuenta con dos
decisiones y ningún cierre. No hay servidor de prueba persistente.

## B18-R20 — Cobertura de autorizaciones de Imágenes HPC

En Autorizaciones se registra una vez por factura si la selección de CSV comprende
todas las resoluciones de Imágenes HPC del período declarado, incluso las de órdenes
anteriores. El período pertenece a esa versión de las fuentes. El sistema verifica
los originales, la integridad de los registros y la ventana inclusiva desde 60 días
antes hasta el día de cada prestación. La exhaustividad la declara el operador.
El número de filas del archivo y las fechas extremas de sus órdenes no la acreditan.

Con cobertura suficiente y sin aval localizable, la planilla propone el importe
facturado de la fila para decisión administrativa. Conforme a RN08, la ausencia
se distingue del rechazo explícito. Una exportación parcial, una orden en cuarentena
o una identidad ambigua dejan el cotejo pendiente. Si una misma prestación factura
dos unidades iguales por 200.000 ARS y hay aval para una sola, se muestra «1 de 2
autorizada» y se proponen 100.000 ARS por la otra unidad. El cálculo se hace sobre
el importe de la fila y requiere un resultado exacto en centavos. Un prefijo o una
descripción parecida solo justifican revisar la relación. Los importes requieren
decisión humana. Cambiar las fuentes o la declaración obliga a revisar lo afectado.

Para la prueba manual se preparó `.tmp/demo-cobertura-csv` en R20. Entrar como
`demo-administrativo`, abrir `FICTICIO_cobertura_Imagenes.xlsx` y consultar Pendientes
de Imágenes. El período de resoluciones confirmado es 03/06/2026 a 02/08/2026.
La primera fila del 2 de agosto muestra «Sin aval» por 100.000 ARS, la segunda
muestra «1 de 2 autorizada» por 100.000 ARS y la del 4 de agosto queda pendiente.
La demo preparada se deja sin decisiones. Para crear otra desde estas fuentes
usar `python -B -m scripts.create_review_journey_demo --cobertura-csv --name NOMBRE-NUEVO`.

Los cambios abarcan app/csv_export.py, app/csv_coverage.py, app/authorization_matching.py,
app/api.py, app/practice_board.py, app/row_decisions.py, app/db.py (esquema 38), web/app.js,
web/index.html, web/workbench.js, web/sheet_actions.js y web/row_decision.js.
La demo se genera en scripts/create_review_journey_demo.py. La selección Python se reproduce
con `python -B scripts/verify_r20_coverage.py`, que incluye tests/test_csv_shortfall.py.
El recorrido Windows se reproduce con `node tests/r20_browser_smoke.cjs` y TFG_BROWSER_PYTHON
apuntando al intérprete del proyecto. Usa su propia demo, navegador y servidor en loopback.

En esta copia pasaron 62 pruebas Python seleccionadas y 158 JavaScript, sin fallos
ni omisiones. En navegador Windows se comprobó el resultado de las tres filas y se
retiró y restableció la declaración del período desde Autorizaciones. La prueba de
dos facturas comprobó que el aval usado en la fila con dos TAC no vuelve a cubrir
otra realización. El ensayo se limitó a datos ficticios y a la selección indicada.
Queda pendiente la validación por un operador con la exportación que corresponda.

## B18-R21 — Cantidad autorizada por práctica de Imágenes HPC

La planilla distingue dos unidades autorizadas de una sola. El movimiento debe
identificar la práctica y aprobarla. El CSV ficticio de esta revisión indica
«AUTORIZAR: 1234567890 - TAC TRIDIMENSIONAL x2». Se conserva el movimiento
original, la fila del CSV y la cantidad interpretada para ese código. También
se reconoce una cantidad expresa en el ítem listado cuando su resolución
individual lo aprueba y no la reduce. Una cantidad contradictoria o condicional
requiere cotejo. Las capturas anteriores que necesitan una nueva interpretación
pueden confirmarse y seleccionarse con el mecanismo existente de Autorizaciones.

El cotejo usa la fecha de prestación y las unidades disponibles de cada aval
en las facturas con el mismo alcance. La fila con dos TAC cubiertas muestra
«2 de 2 autorizadas». Una prestación posterior encuentra el saldo agotado.
Con el CSV completo y vigente, el total de esa tercera prestación se propone
para revisión. Si varias filas del mismo día compiten por unidades insuficientes,
quedan pendientes de cotejo.

Demo manual preparada en `.tmp/demo-dos-tac`. Ingresar como `demo-administrativo`
y abrir `FICTICIO_Tres_TAC.xlsx`. En **Ver factura completa** se ven las dos TAC
del 02/08 (200.000 ARS en una fila). En **Pendientes · Imágenes**, revisar la del
04/08 (100.000 ARS). Para generar otra demo, usar un directorio nuevo con
`python -B -m scripts.create_review_journey_demo --dos-tac --name NOMBRE-NUEVO`.

Los cambios de interpretación y saldo están en app/csv_item_quantity.py,
app/hpc_csv_adapter.py, app/hpc_csv_resolutions.py, app/authorization_matching.py
y app/csv_coverage.py. El cálculo parcial, los filtros y la presentación se
actualizaron en app/row_decisions.py, app/csv_export.py, app/practice_board.py,
web/row_decision.js, web/workbench.js y web/sheet_actions.js. Las verificaciones
se reproducen con scripts/verify_r21_units.py y tests/r21_browser_smoke.cjs.

En Windows aprobaron 97 pruebas de la selección Python y 158 pruebas JavaScript.
La selección específica de cantidades, que se superpone con la general, aprobó
19 pruebas. El navegador comprobó las dos unidades cubiertas en Ver factura
completa y los 100.000 ARS propuestos para la tercera TAC en Pendientes.
Las pruebas incluyeron filas separadas, empate de fechas, declaraciones dudosas
y reinterpretación explícita de una captura anterior sin sobrescribirla.
En la demo preparada se verificaron dos filas, cero decisiones y cero cierres.
Las pruebas usaron datos ficticios. La aceptación con el operador y su exportación
queda pendiente.
