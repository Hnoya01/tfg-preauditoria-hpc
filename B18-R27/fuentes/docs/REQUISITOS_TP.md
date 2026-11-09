# Requisitos vigentes del TP

Extracto literal revisado de T1, entrega 3: RF, RNF, RN, ALC, CP y MD. Son requisitos, no una afirmación de implementación. No contiene el documento original, anexos operativos ni resultados reales. No reemplaza los casos de uso ni criterios completos de aceptación del TP; antes de ampliar alcance deben consultarse en el original privado autorizado. No se corrige silenciosamente la numeración del original.

RF01. El sistema deberá permitir incorporar lotes de facturación, resoluciones de autorización, referencias de valores e informes de respaldo disponibles.

RF02. El sistema deberá validar la integridad y la correcta interpretación de las fuentes incorporadas.

RF03. El sistema deberá identificar las prestaciones comprendidas en la revisión y los controles aplicables a cada una.

RF04. El sistema deberá relacionar las prestaciones facturadas con sus autorizaciones, referencias de valores e informes disponibles.

RF05. El sistema deberá aplicar controles automáticos para detectar posibles inconsistencias administrativas y documentales en las prestaciones comprendidas en la revisión.

RF06. El sistema deberá priorizar las prestaciones que requieran revisión.

RF07. El sistema deberá permitir consultar y filtrar las prestaciones, sus alertas y la evidencia asociada.

RF08. El sistema deberá permitir registrar las decisiones, observaciones, consultas y aclaraciones resultantes de la revisión.

RF09. El sistema deberá registrar automáticamente y permitir consultar el historial de las acciones realizadas durante la revisión.

RF10. El sistema deberá permitir retomar una revisión conservando el avance registrado.

RF11. El sistema deberá permitir cerrar la revisión de un lote.

RF12. El sistema deberá permitir exportar los resultados y las propuestas de débito con su respaldo.

RF13. El sistema deberá permitir consultar el avance, la cobertura y los resultados de los controles aplicados al lote.

RF14. El sistema deberá calcular diferencias económicas y permitir elaborar las propuestas de débito resultantes de la revisión.

RF15. El sistema deberá permitir corregir los datos de trabajo y las vinculaciones utilizados durante la revisión.

RF16. El sistema deberá permitir iniciar una nueva revisión de un lote previamente cerrado.

RF17. El sistema deberá autenticar a los usuarios que accedan a la aplicación.

RNF01 Seguridad de acceso. El sistema deberá restringir el acceso a la información y a las operaciones según la identidad y los permisos del usuario.

RNF02 Confidencialidad. El sistema deberá proteger los datos personales y asistenciales frente a accesos o divulgaciones no autorizados durante su almacenamiento, procesamiento y exportación.

RNF03 Integridad. El sistema deberá preservar la información original y distinguirla de las correcciones y transformaciones utilizadas durante la revisión.

RNF04 Trazabilidad. El sistema deberá mantener la trazabilidad de los resultados y decisiones hasta las fuentes, reglas y acciones que los originaron.

RNF05 Recuperabilidad. El sistema deberá permitir recuperar el avance conservado sin inconsistencias entre datos, evidencias y decisiones después de una interrupción o restauración.

RNF06 Usabilidad. El sistema deberá presentar la información y las acciones de revisión con terminología del circuito y criterios de interacción consistentes para sus usuarios.

RNF07 Operación web centralizada. El sistema deberá permitir el trabajo simultáneo de usuarios desde distintas computadoras mediante una aplicación web centralizada.

RNF08 Respuesta durante el procesamiento. El sistema deberá mantener disponible la consulta del estado y del avance durante el procesamiento de los lotes.

RNF09 Reproducibilidad de controles. El sistema deberá producir los mismos resultados de control al utilizar los mismos datos de trabajo, fuentes, reglas y configuración de procesamiento.

RN04 Unidad de revisión. Los controles se aplican sobre las filas de facturación, conservando el detalle de cada prestación y su relación con la orden y el ítem correspondiente. La agrupación por orden no reemplaza la revisión individual. Una orden puede contener varias prácticas y su número repetirse en las filas correspondientes; esa repetición no constituye por sí sola doble facturación.

RN05 Identidad del afiliado. En este circuito, el número de afiliado representa el DNI. Para el formato con barra y ceros iniciales de relleno, la normalización concatena los dígitos de ambos lados y elimina los ceros iniciales, conservando el dato original. Su aplicación general debe comprobarse con otros registros. Un formato no reconocido, identificador ausente, inválido o contradictorio impide confirmar las vinculaciones que dependan de él, pero no invalida los controles independientes. El DNI inicia la búsqueda de candidatos; práctica y fechas compatibles completan la vinculación. No se exige la ID de plataforma en el Excel. El nombre por sí solo no permite confirmar la identidad.

RN06 Columna de significado desconocido. La columna J sin encabezado se conserva como dato de origen. No se utiliza para identificar ítems, vincular registros ni deducir omisiones o duplicaciones.

RN08 Cobertura de autorizaciones. El archivo estructurado debe conservar las resoluciones de las prestaciones del lote que requieren autorización, incluidos rechazos y derivaciones. La cobertura prevista se distingue de la comprobada en cada carga; se identificarán el universo cubierto, el corte y las limitaciones de la extracción. Una práctica sin coincidencia se presenta como «sin autorización localizada en la fuente». Esa ausencia exige revisar identidad, vínculo y cobertura; por sí sola no demuestra rechazo ni genera un débito.

RN09 Resolución aplicable. Se utiliza la resolución aplicable a cada práctica. Una autorización general expresa comprende las prácticas y cantidades solicitadas que identifica; el estado global AUTORIZADO no acredita por sí solo la aprobación de todos los ítems. Si hay decisiones individuales, se conservan autorizaciones, rechazos y derivaciones sin extenderlos a las demás prácticas. Un motivo truncado o ambiguo no permite completar decisiones por suposición. Cod.Auto y la URL no acreditan autorización. La vinculación utiliza DNI, código completo, descripción y fechas compatibles, sin exigir la ID de plataforma en el Excel. El prefijo de seis dígitos no acredita autorización. Sin código completo, no se confirma el vínculo automáticamente. La ID de la orden vinculada se conserva; no se equiparan Nro.Orden y op ni se utiliza la columna J como ítem. Solo una correspondencia inequívoca permite vinculación automática; conflictos reales entre resoluciones, prácticas repetidas indistinguibles o varios candidatos requieren revisión. Una misma orden no permite autorizar prácticas a distintos prestadores.

RN10 Fecha de autorización. La autorización puede ser anterior o posterior a la realización, pero debe preceder la incorporación de la práctica al Excel consolidado. Se conservarán fecha, hora y zona cuando la fuente las informe, junto con su precisión y procedencia. Si ambos eventos ocurren el mismo día, solo se establecerá su orden con evidencia temporal suficiente. Una fecha sin hora no se convertirá a medianoche. Una autorización acreditadamente posterior a la inclusión genera observación para revisión; una secuencia que no puede determinarse queda no concluyente. La emisión de la factura comercial, la fecha del archivo, el período facturado y la carga al prototipo no sustituyen esa evidencia. Las refacturaciones quedan fuera del alcance.

RN11 Cantidades y cobertura. La cantidad facturada se contrasta con la comprendida en la resolución aplicable, general o por práctica. Cuando varias filas se vinculan con el mismo ítem y ocasión de realización, se considera su alcance conjunto para evitar asignar más de una vez las mismas unidades autorizadas. Una asociación ambigua no asigna ni consume automáticamente cobertura. Una cantidad mayor que uno en una orden corresponde a la misma ocasión; realizaciones en fechas distintas requieren órdenes diferentes, según el criterio operativo acordado.

RN12 Importes de la fila. Hono., Dere y Total representan importes de toda la fila, ya correspondientes a Cant. No deben multiplicarse nuevamente por la cantidad.

RN13 Coherencia monetaria interna. La suma de honorarios y derechos se contrasta con el total de la fila, con una tolerancia de $0,01. La consistencia de esa suma no demuestra que el arancel o la cantidad sean correctos.

RN14 Referencia económica aplicable. Prevalece el importe específico aceptado o renegociado aplicable a la prestación. Para el arancel general, la vigencia corresponde a la fecha de realización. La comparación requiere compatibilidad de unidad y cantidad cubierta, utiliza los primeros seis dígitos del código HPC para la equivalencia de valores y conserva fuente y versión. Se aplica una tolerancia de $0,01.

RN15 Referencia arancelaria insuficiente. Cuando falta una referencia suficiente o su aplicación es ambigua, el control arancelario queda como no concluyente. Esto no impide otros controles monetarios independientes. Una diferencia respecto de otra fila o período no demuestra por sí sola un error de valor.

RN16 Importes cero. Los códigos 660001 y 661001 admiten importe cero por su condición de no valorizados. Los demás importes cero se interpretan según la prestación y su referencia aplicable; no se consideran universalmente inválidos.

RN17 Posibles duplicados. Las coincidencias entre prestaciones incluidas, dentro del lote y con otros lotes incorporados del mismo período, constituyen candidatos a revisión y no confirman automáticamente doble facturación. Se conserva su procedencia y se distinguen la reincorporación de una fuente y las unidades legítimas. Las revisiones de un mismo lote no se cuentan como presentaciones independientes. Una coincidencia no autoriza a eliminar la fila original.

RN18 Repeticiones válidas. La repetición de una práctica en distintas fechas, con órdenes válidamente autorizadas, no genera por sí sola una alerta de frecuencia. Los controles de duplicación, cantidad, valor y respaldo permanecen independientes.

RN19 Período incluido. El prototipo analiza prestaciones cuya fecha de realización pertenece al mes y año facturados, confirmados al incorporar el lote. Las prestaciones de otros períodos permanecen identificadas como excluidas del alcance actual, sin generar por esa causa una irregularidad o propuesta de débito. La refacturación de períodos anteriores y el tratamiento de hojas de débito quedan fuera de esta versión. Una fecha ausente o ilegible se informa como indeterminada; no se excluye por suposición. El período no se determina por el mes en que se usa el sistema ni por la fecha de autorización.

RN20 Disponibilidad documental. Los informes se utilizan cuando están disponibles. Su falta permite continuar los controles administrativos y no demuestra que la prestación no se realizó. En el prototipo, la conciliación documental se evaluará sobre una muestra acotada de informes descargados. En las prestaciones sin informe disponible, el control correspondiente figurará como no evaluado por falta de ejecución. Debe distinguirse esa limitación de haber efectuado una búsqueda suficiente sin encontrar respaldo compatible. La cobertura documental y los resultados de la muestra se informarán sin extrapolarlos al lote completo.

RN21 Correspondencia documental. Se comprueban por separado identidad, correspondencia temporal, estudio, región y cantidad. Cada resultado conserva la evidencia y su localización. Solo se confirman vínculos inequívocos; varios candidatos requieren revisión. Un informe puede respaldar varias prácticas identificadas sin duplicar el archivo ni extender a todas la evidencia de una sola. La compatibilidad de fecha o código por sí sola no confirma el vínculo.

RN22 Contraste. Cada fila de contraste facturado debe vincularse a una práctica compatible del mismo afiliado y fecha de realización. El informe vinculado debe mencionar expresamente su uso, con la correspondencia temporal de RN21. La mención respalda utilización, no cantidad ni importe. La ausencia de mención en un informe legible o una indicación expresa de estudio sin contraste generan observación para revisión; la omisión no prueba que no se administró. Lectura insuficiente o vínculo dudoso: no concluyente. Sin informe: no evaluado. Cantidad y valor se controlan por separado, sin equiparar unidades de contraste con estudios.

RN23 Independencia de controles. El resultado favorable de un control no resuelve los demás. Una prestación no puede presentarse como completamente verificada cuando alguno de sus controles aplicables no pudo concluirse.

RN24 Priorización. Se ordena primero por tipo de problema y después por el importe observado calculable, de mayor a menor. En cada nivel, los importes desconocidos se identifican como «por determinar» y se ubican después de los cuantificados. Si persiste el empate, se utiliza el orden de las filas del Excel. Las consecuencias de una misma causa y los componentes económicos superpuestos se cuentan una sola vez. Los controles pendientes por fallo técnico o actualización permanecen visibles como trabajo pendiente; no se convierten en avisos de baja prioridad.

RN25 Decisiones sobre alertas. Cada alerta conserva su decisión individual: pendiente, confirmada, descartada o no concluyente. Las decisiones registradas identifican al responsable y su fundamento. Se admite aplicar una decisión y justificación común a alertas seleccionadas expresamente por el revisor cuando comparten fundamento; cada una conserva su registro, responsable y fecha. Los casos con tratamiento diferente se separan. La acción conjunta no suma importes ni confirma un débito definitivo.

RN26 Intervención médica. El revisor puede registrar una consulta y dejar el caso disponible para los médicos habilitados para esa revisión. Cualquiera de ellos puede consultar su evidencia pertinente y registrar una respuesta. También puede responder fuera de la aplicación para que el revisor incorpore la aclaración, distinguiendo autor y registrador. Ese acceso se limita a los casos consultados y no habilita modificaciones de facturación, propuestas de débito ni cierre. La respuesta no resuelve automáticamente la alerta ni modifica la autorización original. La validación definitiva del débito continúa fuera del prototipo.

RN27 Propuesta de débito. Cuando regla y datos lo permiten, el sistema prepara un importe por fila con desglose de motivos y componentes económicos. Cada componente que aporte importe exige hallazgo confirmado y respaldo suficiente y vigente. El sistema consolida unidades o rubros sin superposición y permite sumar diferencias independientes respaldadas. El revisor confirma el cálculo disponible o lo ajusta con cálculo y fundamento, sin transcribir lo ya obtenido. Las estimaciones de alertas pendientes y los importes afectados por cambios se separan del total vigente. Sin respaldo suficiente se conserva la observación sin cuantificar, nunca como cero por defecto. La validación definitiva del débito permanece fuera del prototipo.

RN28 Cambios durante la revisión. El Excel presentado permanece inmutable. Las correcciones internas de interpretación o asociación conservan original, cambio, responsable, fecha y motivo. El sistema identifica automáticamente controles, decisiones y propuestas afectados; sus importes quedan fuera del total vigente hasta reevaluarse. El trabajo independiente conserva validez. El revisor puede acumular cambios y solicitar Actualizar análisis. Una nueva fuente también marca los controles de la limitación compartida afectada, sin ejecutarlos automáticamente. Si existe un cierre, la nueva evidencia requiere otra revisión del mismo lote según RN30.

RN29 Condiciones de cierre. El cierre exige que no queden alertas pendientes de revisión. Se permite cerrar con casos no concluyentes y controles no ejecutados identificados y justificados. Una limitación compartida se registra una sola vez por causa y alcance; el sistema vincula los controles afectados y conserva la trazabilidad por prestación. Al cerrar se reutiliza ese fundamento y el revisor confirma únicamente las limitaciones que continúan pendientes, completando las que carezcan de justificación. Estas permanecen visibles en el cierre y la exportación; no transforman controles en realizados ni resuelven alertas automáticamente. Todo control o decisión afectado por cambios debe reevaluarse o quedar comprendido en una limitación expresa. Una decisión histórica no valida datos nuevos. El cierre no certifica toda la factura.

RN30 Evidencia posterior al cierre. La incorporación de nueva evidencia después del cierre requiere iniciar expresamente una nueva revisión del mismo lote. Se conserva el cierre anterior y se identifican los controles y decisiones afectados.

RN31 Resultados exportados. Toda salida identifica lote y revisión, conserva resultados, decisiones y respaldo, y mantiene visibles exclusiones, casos no concluyentes y limitaciones de cobertura. Durante una revisión abierta se identifica como provisional e incluye alertas pendientes. Después del cierre reproduce el estado conservado. Los importes se presentan como propuestas sujetas a validación externa; las estimaciones y los pendientes de reevaluación quedan separados del total vigente.

ALC01 Finalidad y exclusiones. La preauditoría identifica posibles inconsistencias y aporta información para revisión humana. Quedan fuera del prototipo la determinación de pertinencia clínica, la interpretación de imágenes diagnósticas, la autorización de prestaciones y la aplicación de débitos definitivos.

ALC02 Alcance por prestación y control. Se incluyen prestaciones realizadas en el mes y año facturados. Internación y prestaciones de otros períodos quedan excluidas y permanecen identificadas; la refacturación de períodos anteriores no se gestiona en esta versión. Los controles administrativos se aplican a las prestaciones elegibles según sus datos. La conciliación documental inicial se concentra en estudios por imágenes. Los medicamentos no se excluyen automáticamente de controles administrativos y alta complejidad no equivale por sí sola a internación.

ALC03 Limitación de identificación de urgencias. Las fuentes disponibles no permiten identificar las urgencias de manera confiable. Se aplicarán los controles comunes que la información permita, sin inferir esa categoría ni interpretar la falta de identificación como ausencia de urgencias. Esta limitación impedirá presentar resultados diferenciados para ellas.

CP01 Integridad De Incorporación

La carga se confirma cuando las filas y los importes se concilian con la fuente. Los registros no interpretables conservan su identificación y motivo. Una pérdida o alteración introducida durante la interpretación impide confirmar la carga.

Una fuente idéntica se reconoce por su contenido, aunque cambie el nombre, y no genera una segunda facturación. Las inconsistencias presentes en el archivo original se conservan para su análisis.

Esta comprobación acredita la fidelidad de la incorporación; los controles de prestación, autorización, cantidad y valor corresponden al análisis posterior.

CP02 Resultados Y Estados

Los resultados de los controles, las decisiones humanas y los estados de procesamiento deben registrarse por separado.

Resultado del control. No evaluado, no aplicable, sin observaciones, con indicios de inconsistencia o no concluyente. Cada resultado corresponde a un control concreto de una prestación.

Decisión sobre una alerta. Se registra por separado del resultado automático, con los estados, responsable y fundamento definidos en RN25.

Situación de la prestación. Se obtiene de sus controles y alertas. Puede contener simultáneamente hallazgos confirmados y controles no concluyentes, sin reducirse a una clasificación única de correcta o incorrecta.

Estado de la revisión. En preparación, en revisión o cerrada. El cierre pertenece a una revisión identificada; un lote puede conservar una revisión cerrada anterior y otra posterior en curso.

Estado técnico del procesamiento. Pendiente, en ejecución, completado, interrumpido o fallido, identificado por tarea o unidad procesada. Una falla técnica no constituye por sí misma una inconsistencia de facturación.

No aplicable. El control no corresponde por alcance o regla.

No evaluado. No se obtuvo una evaluación del control; debe conservarse el motivo.

No concluyente. La evaluación o revisión no permite sostener una conclusión suficiente.

Sin autorización localizada en la fuente. Se interpreta conforme a RN08. En otros controles, una falta de coincidencia tampoco demuestra ausencia de prestación.

Los controles no ejecutados conservan esa condición al cerrar. Si una reevaluación se interrumpe, la decisión anterior permanece como antecedente; su vigencia y la posibilidad de cierre se rigen por RN28–RN29.

CP03 Automatización Y Apoyo A La Revisión

El revisor solicita Analizar después de preparar las fuentes disponibles o Actualizar análisis tras incorporar cambios. El sistema ejecuta automáticamente los controles aplicables, sin exigir que se lance cada control por separado. Las limitaciones que impidan ejecutar o concluir un control quedan identificadas. La incorporación de fuentes no inicia por sí sola otra ejecución.

La intervención del revisor se concentrará en alertas, asociaciones dudosas y situaciones que requieran una decisión humana. No se exigirá la confirmación manual individual de todas las prestaciones procesadas. La ausencia de alertas se presentará junto con la cobertura de los controles efectivamente realizados.

Para resolver una alerta, el revisor deberá poder consultar conjuntamente la prestación facturada, el motivo y la regla que originaron la alerta, los datos utilizados en la comparación, la evidencia vinculada y su referencia de origen, y las decisiones y aclaraciones registradas.

El sistema registra automáticamente la trazabilidad de fuentes, controles y acciones; el revisor aporta las decisiones y sus fundamentos.

Las exclusiones se muestran agrupadas por causa, sin confirmación por fila. Una causa técnica común no se presenta como múltiples irregularidades ni exige repetir su fundamento. Los cambios y los cálculos siguen RN28 y RN27, respectivamente.

MD01 Identidad Y Origen

Los identificadores locales son claves técnicas. DNI, número de orden, código y posición de fila no constituyen claves universales. Se conservan los valores externos literales y su procedencia. Las equivalencias se versionan con su fuente según RN06, sin crear un catálogo maestro ni un padrón ajenos al alcance.

MD02 Facturación Inmutable Y Período

Lote referencia un único Excel inmutable y su período confirmado; sus revisiones comparten las filas originales. No se trasladan decisiones entre Excel corregidos. DatoTrabajo distingue prestaciones incluidas, excluidas e indeterminadas conforme a RN19 y ALC02.

MD03 Correcciones Internas

Una corrección agrega una versión de DatoTrabajo con motivo y responsable y recalcula su alcance. Vinculo conserva antecedentes y una sola versión efectiva por cadena. La identificación de dependencias y la reevaluación cumplen RN28.

MD04 Identidad De Cobertura

ItemAutorizacion representa lo que una fuente expresa. IdentidadItemAutorizado reconoce una misma cobertura entre extracciones verificadas. Si la fuente no distingue prácticas iguales o no permite confirmar equivalencia, los candidatos quedan separados y no se asignan unidades automáticamente. El agrupamiento por identidad no decide cuál de dos resoluciones contradictorias es aplicable.

MD05 Asignación De Cantidades

Se compara una sola representación de cada fila incluida del período y cada cobertura identificada, aunque figure en varias extracciones. Para cada lote pertinente se usa su revisión abierta o, si no existe, la última revisión; se fija ese conjunto y sus dependencias en la captura. Solo cuentan vínculos confirmados, no reemplazados y compatibles con el dato actual. La suma conjunta por identidad y ocasión respeta la cantidad autorizada. Una fecha distinta no reinicia la cobertura: se cumple RN11. Información ambigua o pendiente no libera ni acredita unidades; se informa la limitación sin asignar por orden de llegada. Cambios en un lote marcan los controles dependientes de otras revisiones abiertas; los cierres conservan su contenido. Historial, contraste y coincidencias no suman cobertura.

MD06 Resultados Y Decisiones

ControlEvaluacion identifica el control de una fila; ResultadoControl, su evaluación; Alerta, el indicio; y DecisionRevision, la intervención sobre un resultado específico. Su vigencia sigue RN28. En otra revisión del mismo archivo, reutilizar trabajo exige la misma fila, dependencias equivalentes y procedencia explícita; esa reutilización no cuenta como una nueva decisión humana. Confirmar requiere evidencia vigente y una limitación no resuelve alertas.

MD07 Capturas Reproducibles

Antes de analizar se guarda una captura inmutable con lote, archivo, período, datos, vínculos, reglas y conjunto comparado, incluidas dependencias entre lotes. Los registros inmutables se identifican por ID y versión; de las relaciones mutables se conserva el valor utilizado, como fuentes activas, equivalencias de códigos y sus fuentes, identidad de cobertura y controles de cada limitación. Se valida la captura al construirla; las FK operativas permanecen en tablas. Antes de publicar se comprueba que las dependencias siguen siendo las analizadas. Si cambiaron, el resultado queda histórico. Reutilizar un resultado exige equivalencia de dependencias y procedencia explícita.

MD08 Limitaciones Comunes

LimitacionCompartida se vincula con cada ControlEvaluacion afectado mediante limitacion_control. Esto incluye controles sin resultado. Al incorporarse la fuente faltante se marcan para actualización; no se consideran ejecutados. El cierre conserva el fundamento y la lista exacta de controles que seguían afectados.

MD09 Alcance Médico

La combinación de rol médico, acceso_revision y consulta_prestacion delimita el acceso. consulta_evidencia restringe páginas o fragmentos pertinentes; conocer el ID o la ruta de un archivo no concede acceso. No se comparte el PDF completo cuando contiene información ajena a la consulta. Una respuesta externa identifica al emisor sin exigirle cuenta.

MD10 Importe Por Fila

Se conserva una propuesta vigente por fila y revisión. Cada componente identifica base, unidades o rubros, decisiones y referencias; los componentes que aportan importe deben cumplir RN27. Se versionan las modificaciones y se preservan cálculo automático, ajuste manual y motivo. La consolidación admite diferencias independientes y evita superposiciones, sin agregar un tope contractual universal.

MD11 Cierre Y Exportación

El cierre conserva un manifiesto con IDs de decisiones, propuestas, fuentes y cobertura, y cambia el estado en una transacción (RN29 y MD12). Se bloquean sus modificaciones de contenido. La exportación utiliza esa captura o una captura provisional consistente, según RN31.

MD12 Consistencia Al Guardar

Las operaciones verifican el número de cambio leído y los permisos antes de confirmar. Si la base cambió desde que se abrió el caso, se solicita actualizar la vista. Control, dato y resultado deben corresponder a la misma revisión y fila; la ejecución pertenece a esa revisión; la versión de regla debe coincidir con el código del control. La decisión solo puede referir a un resultado de su alerta. Los vínculos exigen fuentes habilitadas y compatibilidad de moneda, unidad y alcance. Las FK, unicidades y condiciones simples se implementarán en la base; las sumas de cobertura, vigencia y compatibilidad entre varias entidades se validarán dentro de la misma operación transaccional. La resolución conjunta valida toda la selección antes de guardar y confirma el grupo completo en una transacción; si cambió un caso, solicita actualizar sin decisiones parciales inesperadas.

Las operaciones que afectan varias tablas se confirman juntas. Primero se prepara el archivo inmutable y se verifica su huella; luego se registra su referencia junto con el cambio de estado. Un fallo no debe dejar una carga, cierre o exportación presentada como completa. El apartado de despliegue detalla el tratamiento de archivos huérfanos y la restauración conjunta.
