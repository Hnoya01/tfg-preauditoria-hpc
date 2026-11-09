# Consultas y respuestas externas (RN26)

Incremento acotado desde `7b841af7fd41e6c79be77ecbbacd001b8cc12a01`,
`feat/rn14-human-review` (PR #6). RF08/RF09, RN26, RN28–RN31 y MD09/MD11/MD12.
El usuario autorizó implementación, pruebas ficticias y PR en borrador sobre esa base.
No constituye aceptación humana, validación clínica ni habilitación productiva.

## Recorrido

En Facturación, abrir **Detalle → Consultas y respuestas externas**. Un revisor con
acceso al conjunto (o admin) registra una consulta por prestación en la revisión
abierta. Se conserva texto, autor, fecha de registro y captura de campos originales
e interpretaciones existentes. No se envía el mensaje al médico.

El revisor incorpora una respuesta externa con nombre informado del emisor, fecha
con hora/zona, medio, referencia de procedencia y texto. El servidor registra por
separado la cuenta y fecha de incorporación. El nombre del emisor es declarado,
no una identidad autenticada ni una firma verificada. No requiere cuenta médica.
La fecha se normaliza a UTC; debe estar entre el registro de la consulta y el de
la respuesta. En pantalla se ingresa en hora local del navegador, incluidos segundos.

Consultas y respuestas son acumulativas, sin editar ni borrar. Para corregir una
respuesta se agrega otra aclaración que identifique lo corregido; todas permanecen
visibles en orden de incorporación. “Con respuesta registrada” sólo describe la
correspondencia: no significa caso resuelto, alerta aprobada ni débito validado.
La decisión de alertas y cualquier interpretación de datos siguen por sus acciones
explícitas ya existentes. No se ejecuta análisis, modifica autorización ni altera
propuesta o importe al guardar correspondencia.

## Consistencia y cierres

Elecciones técnicas reversibles: dos tablas aditivas en esquema 25, claves de
operación para reenvío exacto, captura textual por fila e historial por revisión.
Cada escritura revalida sesión, acceso reviewer, conjunto, prestación, revisión
abierta y versiones dentro de una transacción inmediata. Incrementa las versiones
de conjunto/revisión junto con el evento de auditoría. Las FK y triggers impiden
vínculos ajenos, modificaciones históricas y nuevas respuestas sobre cierre.

Una entrega incierta puede repetirse con la misma clave/cuerpo/cuenta: devuelve
el mismo ID sin duplicar evento ni incrementar versiones. Otra operación con esa
clave se rechaza. La repetición comprueba permisos incluso si ya se había guardado;
puede confirmar un registro histórico después del cierre, sin escribir allí.
La UI no reintenta automáticamente: conserva cuerpo y clave frente a un error
incierto, y conserva borradores frente a conflicto hasta actualizar expresamente.
Las lecturas revalidan acceso/versiones después de una captura consistente.

La salida provisional incluye `medical_consultations.jsonl` con respuestas anidadas,
emisor y registrador, contexto y fechas. El manifiesto identifica consultas,
respuestas y cantidad sin respuesta. Cierre y preview muestran ese resumen.
RN29 sigue exigiendo resolver alertas pendientes y justificar limitaciones; una
consulta sin respuesta no añade una regla de cierre no especificada. Se conserva
explícitamente como pendiente de respuesta, sin convertirla en decisión ni control.

Una nueva aclaración después del cierre exige una nueva revisión. La consulta
anterior queda visible como antecedente de sólo lectura. Registrar una consulta
actual identificando el ID antecedente en el texto, y luego incorporar la nueva
respuesta. No se trasladan respuestas automáticamente ni se modifica el cierre.
El export de la sucesora sólo incluye correspondencia propia; la anterior permanece
en su cierre identificable. Los ZIP previos al esquema 25 conservan exactamente
sus bytes y no se reconstruyen para añadir campos.

## Migración y recuperación

Detener el servidor y preparar respaldo coherente con el procedimiento existente
`backup-and-upgrade` antes de actualizar una base existente (ver README y guía de
recuperación). El inicio normal rechaza esquemas antiguos. La migración 24→25 sólo
crea tablas y triggers; no cambia filas, fuentes o cierres. Ante fallo, la transacción
revierte la migración. Para retroceder, usar aplicación y respaldo v24 juntos en un
directorio separado; nunca abrir una base v25 con aplicación v24 ni borrar tablas.
No se migraron datos operativos ni se crearon credenciales persistentes.

## Evidencia y límites

Resultados finales: 298 Python descubiertas, 296 aprobadas, dos omisiones Windows;
63 JavaScript aprobadas, pip check correcto. Chromium loopback: consulta y respuesta
por UI, emisor/registrador visibles, HTML inerte, cero errores/peticiones externas.
El ensayo inicial detectó un encabezado JSON faltante, corregido y vuelto a probar.
[Registro completo y limitaciones](ESTADO.md). Regresiones nuevas en
`tests/test_medical_consultations.py` y `tests/web_medical_consultations.test.cjs`:
identidades, fechas, texto/HTML inerte, permisos/CSRF, alcance, dos escritores,
reenvíos idénticos, rollback ante fallo de auditoría, revocación en lectura,
exportación, cierre pendiente, sucesora, migración con fallo SQL y recuperación.
Se preserva explícitamente la prueba histórica 23→24, sin ampliarla silenciosamente
al último esquema. La aserción del esquema actual del respaldo pasa a 25.

Pendientes: acceso médico limitado por revisión/caso y fragmentos (MD09 completo),
comunicación externa, adjuntos, paginación de historias extensas, aceptación humana,
Windows de este SHA y recuperación en otro equipo. No OCR, interpretación clínica,
reglas monetarias nuevas, acceso médico global, datos reales ni integración externa.
La lectura completa de una historia puede crecer; no se midió carga máxima.
Windows aprobado de f903bad se conserva como antecedente, sin reabrirlo.

## Corrección U2/U1 del 31/10/2026

Las operaciones inciertas de correspondencia se conservan en memoria de la sesión
con cuerpo/clave exactos también al reconstruir o reabrir el panel. Sus campos se
bloquean hasta comprobar el resultado; no se convierten en otra operación al cambiar
versiones. El cambio de cuenta/logout las retira; abandonar el documento avisa si
quedan operaciones pendientes. No hay almacenamiento persistente de textos privados.

Los formularios RN14 y de aplicabilidad no tienen ese contrato idempotente: ante
resultado desconocido ofrecen lectura de historia, sin reenviar ni renovar versiones.
Un guardado confirmado seguido de error de refresco se presenta como guardado con
pantalla pendiente. Estado de pruebas y limitación de acceso a los adjuntos originales
en [ESTADO.md](ESTADO.md). Q1/Q2 no se modificaron.

## Relación con la revisión interna, 01/11/2026

El nuevo [recorrido administrativo/auditor](RECORRIDO_ADMIN_AUDITOR.md) registra
derivaciones internas por observación. No cambia este contrato de correspondencia:
una respuesta externa sigue sin resolver alertas. Ambos registros conservan autores,
fechas e historia por separado; no se envían mensajes ni se crean cuentas médicas.
