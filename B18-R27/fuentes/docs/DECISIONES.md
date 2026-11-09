# Decisiones vigentes y límites

Extracto revisado de las decisiones confirmadas; se excluyeron observaciones y resultados operativos. Las referencias a incrementos son antecedentes, no acreditan validación actual.



| Asunto | Estado y respaldo |
| --- | --- |
| Plazo de facturación HPC, 09/11/2026 | Decisión expresa del usuario para R26. Se comparan la fecha de realización y el último día del mes confirmado. De 0 a 45 días corridos inclusive cumple. A partir del día 46 se presenta el total de la fila de Imágenes para revisión. Las filas A/C anteriores siguen disponibles para decidir. Internación sigue excluida. Una fecha ilegible no acredita demora. La regla amplía RN19 y ALC02 del [TP escrito](REQUISITOS_TP.md), que excluían los meses anteriores. Se conserva la versión escrita como antecedente. RN10 y la vigencia del aval se evalúan por separado. |
| Primer recorrido | Excel + autorizaciones JSON + valores; PDF/OCR después. Encargo P00 y T1 §Alcance. |
| Demo B mínima, 24/10/2026 | Usuario confirmó mantener autorizaciones JSON en el recorrido y autorizó el primer incremento local B01: contrato/importación con vista previa, historia y datos ficticios explícitos. No autorizó contratación ni publicación por Internet; se hará en tarea posterior con entorno/presupuesto. Dos semanas es objetivo sujeto a los resultados, sin reducir silenciosamente el alcance. |
| Arquitectura de T1 | Python/FastAPI/Uvicorn, HTML/CSS/JavaScript y SQLite con archivos persistentes en servidor; T1 §Diseño y despliegue. La organización interna aún es propuesta. |
| Identidad, código y cantidad | RN05–RN11, MD01–MD05. DNI en este circuito; código completo para autorización; prefijo HPC de seis dígitos solo para equivalencia de valores documentada; ambigüedad no asigna cobertura. |
| RN10 | Autorización antes de incorporar la práctica al consolidado, aunque después de realizarla. Fecha de factura/archivo/carga no sustituye esa evidencia. Sin precisión suficiente, no concluyente. T1 RN10 y CA10. |
| Dinero | O/P/Q de X1 son importes de fila; RN12–RN16. Propuestas requieren hallazgos confirmados, referencia vigente y componentes sin solapamiento; RN27 y MD10. |
| Revisión compartida | Versiones, permisos al confirmar, rechazo del guardado obsoleto y acciones conjuntas indivisibles; MD12, RN25, RN28. |
| Corte de V1 | **BASE_2026-10-09**. Es una referencia versionada; no acredita la base externa actual. |
| Prestador de X1 agosto de 2026 | **HPC únicamente**, aclaración explícita del usuario. Los aranceles de otros prestadores de V1 no son candidatos para esta factura. Esta decisión de alcance no valida por sí sola unidad, condiciones ni vigencia de cada arancel HPC. |
| Gestión de valores, 25/10/2026 | El usuario pidió valores precargados en BD y un apartado para aumentos/modificaciones; aclaró que sean valores respaldados por convenio y sólo HPC. La implementación local registra versiones exactas asociadas a PDF, sin alterar V1 ni afirmar aplicabilidad a filas. Un porcentaje masivo y su regla de redondeo no fueron definidos; requieren una tarea posterior si se desean. |
| Interfaz operativa, 25/10/2026 | El usuario confirmó que Facturación, Autorizaciones, Convenios/valores y Alertas/Revisión deben estar delimitados y ser interpretables. La pantalla larga actual es temporal. Pidió una vista tipo Excel del lote completo, con posibles discrepancias marcadas, motivos al lado, filtros y decisiones; revisar cientos de casos uno por uno resulta impráctico. La automatización cubre detección/motivo con evidencia; decisiones y aplicabilidad monetaria conservan las condiciones del TP. Se documenta como B-UI, pendiente de implementación. |
| Elegibilidad por ámbito | RF03/ALC02/MD02 del TP excluyen internación (`F=I`); `F=C` significa alta complejidad y permanece elegible si cumple período. El arreglo `X1-ALC02-v1` corrige el comportamiento anterior, que miraba solo la fecha. |
| Devolución de interfaz e imágenes, 25/10/2026 | El usuario indicó que el diseño B-UI1 no le resulta cómodo: mensajes/paneles ambiguos, demasiado espacio y poca información a la vista. Pidió trabajar primero con imágenes, identificables por nomenclatura/código, y una planilla semejante a Excel para buscar. No aprobó el diseño anterior ni un rango concreto de códigos. Ajuste compacto aplicado; aceptación del usuario pendiente. Se prioriza antes de ampliar B-UI2, conservando alcance completo posterior del TP. |
| Continuidad B-UI2a, 25/10/2026 | El usuario indicó que la planilla está algo mejor y pidió avanzar. Se continúa con vínculos y decisiones en la grilla, sin interpretar esa continuidad como diseño finalmente validado ni resolución de cantidades/RN10 o aplicabilidad económica. Se mantienen historia, exclusiones y objetivo completo posterior. |
| Continuidad B-PROG, 25/10/2026 | El usuario pidió continuar con el siguiente incremento después de confirmar la actualización documental. Se instrumentó el análisis de controles con estado/progreso e interrupciones/reintentos. No autoriza servicios externos, publicación, relajar permisos o presentar finalización técnica como aprobación económica. |

**Elección técnica reversible de B-PROG:** trabajador local con hilos estándar y registro/confirmaciones en SQLite, un intento activo por lote y ninguna cola externa. Recepción repetida usa la misma clave/cuerpo; reintento conserva padre y entradas, y cambios requieren análisis nuevo. La captura y el éxito técnico se confirman en la misma transacción. Aplicado al análisis de controles; importaciones/vistas previas conservan su funcionamiento síncrono. Es implementación técnica, no una regla nueva de autorización o vigencia monetaria. Operación.



**Aclaración del usuario posterior al cotejo documental (24/10/2026):** avanzar con las prestaciones que el convenio cubre claramente, sin volver a pedir información ya presente. Esto autoriza usar la referencia general respaldada; no confirma cada diferencia como irregularidad, no acredita urgencia ni aprueba importes por sí solo. Una fecha final no declarada no demuestra caducidad ni habilita extrapolar cambios posteriores al corte **BASE_2026-10-09**. No se exige probar la inexistencia de acuerdos particulares: uno específico aceptado y aplicable prevalece cuando se identifica. Las normas especiales, identidad ambigua y diferencias documentales se mantienen como cuestiones concretas por resolver.


Pendientes: validación del intercambio A1 y cobertura; evidencia temporal I1; identidad entre extracciones MD04 y contradicciones; aplicabilidad económica; cierre y revisiones posteriores; validación de interfaz; Linux y recuperación independiente. No se autorizó alojamiento, publicación, servicios ni accesos.

## Q1/Q2 confirmados, 31/10/2026

El usuario confirmó bloquear consultas nuevas de internación (tipo F=I según
clasificación vigente), conservando historia. Esto no extiende el bloqueo a otras
causas de exclusión ni altera las reglas de respuestas existentes, cierre o reapertura.
Los reintentos exactos de operaciones guardadas conservan su identidad y efectos.
Permite registrar recepción externa anterior al alta de la consulta. Se conservan
responded_at y created_at separados: fecha informada de recepción para nuevos
registros y fecha de registro generada por el servidor. No se reinterpretan fechas
históricas existentes, no se agregan columnas ni fechas ficticias. Se mantiene
zona horaria, precisión actual y prohibición de futuro. Migración 25→26 cambia
sólo el trigger de inserción; conserva revisión abierta e inmutabilidad.

## Recorrido administrativo y auditor aprobado, 01/11/2026

El usuario autorizó implementar en rama separada, conservando la versión actual.
El administrativo resuelve suma, convenio y autorización sin localizar con respaldo,
sin visado obligatorio. Deriva dudas concretas. El Auditor resuelve sólo lo
consultado sin segunda aprobación; otras observaciones continúan pendientes.
Pedir/completar información o registrar respuesta externa no resuelve por sí solo.
[Diseño, capacidades reales, relación con RN26/MD09 y prueba](RECORRIDO_ADMIN_AUDITOR.md).
El extracto académico original permanece literal; su sincronización está pendiente.
No autoriza publicación, PR, merge, despliegue, usuarios reales ni datos reales.
