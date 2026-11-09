# Instrucciones de trabajo del TFG

## Objetivo y alcance

Construir por entregas verificables un prototipo de preauditoría administrativa de facturación. El primer recorrido es Excel, autorizaciones JSON y valores, seguido de alertas con evidencia y revisión compartida. Los PDF y el OCR pertenecen a una etapa posterior. No convertir el prototipo en auditoría clínica ni en un sistema que aplica débitos automáticamente.

Este archivo es una propuesta para adoptar en el repositorio del proyecto. Las instrucciones explícitas del usuario y los permisos efectivos del entorno prevalecen. Este archivo no concede permisos ni garantiza ejecución desatendida continua.

## Antes de trabajar

1. Leer la tarea activa, estas instrucciones y los documentos pertinentes. Verificar el directorio y el estado de Git. Conservar cambios ajenos.
2. Consultar el TP vigente, las decisiones confirmadas y el contrato de fuentes. Cuando se incorporen al repositorio, sus rutas se registrarán en README.md. No inventar documentos ausentes.
3. Separar requisito del TP, decisión del usuario, observación de una fuente, propuesta técnica y supuesto pendiente. No presentar una propuesta como decisión aprobada.
4. Si dos fuentes se contradicen, registrar el caso con localizador. No corregir silenciosamente el TP ni elegir por intuición una regla de negocio.

## Forma de avanzar

- Completar la tarea activa y las subtareas necesarias dentro de su alcance. Resolver decisiones técnicas reversibles, coherentes con la arquitectura acordada, sin consultar por cada archivo.
- Dividir cambios grandes por comportamiento verificable. Mantener una sola tarea de implementación activa; otras tareas pueden quedar documentadas.
- Ante una duda funcional, comprobar primero documentos, código y muestras autorizadas. Continuar el trabajo independiente. Consultar únicamente lo que modifica el comportamiento y no tiene respaldo suficiente.
- No inferir autorización para contratar servicios, cambiar el sincronizador remoto, acceder a sistemas hospitalarios, publicar fuentes reales ni enviar mensajes. Preparar el resultado concreto antes de pedir una autorización que efectivamente falte.
- No iniciar trabajos paralelos con otros agentes salvo que la tarea lo autorice. No añadir servicios, bibliotecas o skills sin una necesidad verificable.
- Si una herramienta o permiso bloquea una operación, registrar el bloqueo real; no modificar controles para eludirlo.

## Invariantes funcionales

- Conservar originales inmutables, hash y localizadores. Un mismo Excel no genera otro lote en el mismo conjunto de datos por cambiar su nombre. Una nueva revisión no es otra facturación.
- Separar estado técnico, resultado de control, decisión humana y vigencia. Un control no implementado o sin evidencia no cuenta como aprobado ni como no aplicable.
- RN10 compara autorización e incorporación al consolidado. No exigir autorización anterior a la realización. Si falta evidencia temporal suficiente, no concluir incumplimiento.
- Preservar códigos completos y originales; aplicar únicamente normalizaciones documentadas. No vincular por nombre solamente ni asignar unidades cuando la identidad o el alcance sean ambiguos.
- No usar débitos históricos, motivos, colores o importes ya corregidos para generar detecciones. La referencia de evaluación debe estar separada.
- Usar importes decimales con moneda, unidad y vigencia explícitas. Honorarios, derechos y total del Excel son importes de fila. No multiplicarlos otra vez por cantidad.
- La propuesta monetaria requiere decisiones confirmadas y vigentes, con componentes sin solapamiento. No equiparar importe desconocido con cero.
- Cambios en datos, vínculos o fuentes invalidan automáticamente lo afectado. Reanalizar requiere una acción explícita. Conservar historia y resultados no afectados según las dependencias.
- Comprobar permisos y versión al confirmar cada escritura. Rechazar el guardado desactualizado sin pisar cambios. Mantener lotes de acciones indivisibles.
- Aplicar RN, CP y MD del TP también cuando no estén repetidos aquí. Estos puntos no reemplazan su especificación.

## Datos y seguridad

- Mantener fuentes reales, bases, exportaciones, contraseñas y tokens fuera del repositorio. Un repositorio privado no reemplaza esta separación.
- Usar fixtures ficticios o anonimizados verificados. No imprimir datos clínicos o identificadores en logs, capturas, incidencias ni informes de pruebas.
- Cuentas individuales y permisos comprobados en el servidor. Servir archivos privados mediante rutas autorizadas.
- Antes de una migración, restauración o reemplazo de datos, preparar respaldo coherente y procedimiento de recuperación. No borrar trabajo previo para hacer pasar pruebas.

## Criterio de finalización

Ejecutar las pruebas pertinentes al cambio y al riesgo concreto. No afirmar que se probó algo no ejecutado. No ampliar pruebas sin propósito ni cambiar resultados esperados para acomodarlos a la implementación.

Al cerrar la tarea, dejar cambios revisables, instrucciones reproducibles y un registro con: requisito atendido, archivos modificados, pruebas ejecutadas y resultado, pruebas no ejecutadas, limitaciones, decisiones pendientes y siguiente tarea. Distinguir especificado, implementado, probado y validado por el usuario. Actualizar docs/ESTADO.md cuando exista; no crear otra fuente de estado contradictoria. No declarar el sistema completo por tener una pantalla funcional.
