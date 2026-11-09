# Incorporación local de paquetes Sync · candidata a validación

## Alcance implementado

El panel Autorizaciones admite A1 existente y paquetes JSON locales emitidos por
`prepareImageDay` del sincronizador histórico 0.5.1, con extractor declarado
`historico-0.4`. No se conecta al hospital, Worker, sincronizador ni URLs de adjuntos.
No admite un resumen de búsqueda, respuesta arbitraria de Worker ni PDF.
No se inspeccionó un paquete real actual: el contrato operativo actual sigue sin validar.

El operador guarda el original, revisa la vista previa y confirma la incorporación
con procedencia. Son dos operaciones explícitas. Guardar un original inválido no lo
incorpora como captura. Cualquier análisis y asociación continúa siendo explícito.

## Conservación y controles

- Bytes originales sin modificar en almacén privado direccionado por SHA-256,
  descarga autorizada y auditoría existentes. Cambiar nombre no duplica la fuente.
- Permisos reviewer/admin, versión optimista y protección CSRF existentes tanto
  en carga como en confirmación. No hay endpoint público nuevo.
- JSON estricto: duplicados, Unicode inválido, profundidad >60, más de 250.000 nodos,
  tamaño >16 MiB, payload de orden >80.000 bytes y más de 200 filas/ítems del paquete rechazados. El contrato A1
  aplica adicionalmente sus límites por campo y de registros.
- Se verifican los hashes de cada payload y sus identidades; se rechazan códigos
  bloqueantes del productor. No se interpretan cadenas como código ejecutable.
- Tras confirmar, A1 normalizado se conserva como objeto privado registrado.
  Su hash y el del original están en el manifiesto; la metadata registra adaptador
  y el hash derivado. Correspondencias verifica original, interpretación, manifiesto
  y objeto A1 antes de usar la captura.
- Registro de captura, fuente, manifiesto y derivado en una transacción SQLite;
  fallos no dejan una captura parcial. Publicación de objetos puede dejar objetos
  huérfanos sin referencia tras rollback, como en el almacenamiento previo. No se
  borra un objeto que pudiera estar en uso ni se elimina el original recibido.
- Cada fecha consultada forma un flujo distinto; otra captura del mismo día es una
  versión, no una suma automática. No se mezclan días por sustitución inadvertida.
  La selección existente admite hasta ocho flujos distintos; no se implementó
  agregación mensual ni mezcla automática de días o versiones.

## Lo que no acredita

La conversión siempre marca origen `real_unvalidated`, cobertura parcial y no
verificada. En las pruebas API se usan identidades ficticias, pero se conserva esa
misma regla de producción; la opción synthetic del adaptador solo es auxiliar de
pruebas, no una elección HTTP.

Se conservan códigos completos, textos de movimientos y fechas originales. No se
infieren cantidades, moneda, unidad, importes, equivalencias ni autorización por
práctica. Movimientos tienen alcance `unknown` e ítems vacíos. El texto de un
movimiento «Autorizada» no autoriza los ítems. Filas sin payload por fallo de
extracción permanecen en el original y se cuentan como no representadas. Adjuntos
solo permanecen referenciados en el original, nunca se descargan.

La pantalla muestra versión/contrato, cobertura parcial, intercambio actual no
validado, número de filas no representadas, hashes y limitaciones. Los controles
posteriores conservan sus bloqueos; no hay decisiones humanas ni débitos nuevos.

## Pruebas reproducibles

Desde esta copia aislada, con dependencias del lock:

```
.venv/bin/python -m unittest tests.test_sync_intake tests.test_hpc_sync_adapter tests.test_authorization_imports tests.test_authorization_matching tests.test_authorization_assessment tests.test_authorization_controls -q
node --test tests/web_*.test.cjs
```

El productor JS copiado del histórico produce una entrada sintética que atraviesa
API real (TestClient sin puerto), almacenamiento, manifest y A1, y el renderizador
real de vista previa en DOM simulado. Se bloquean conexiones socket durante la
incorporación. No equivale a aceptación visual en navegador ni a prueba del
exportador desplegado actual. Incluye rollback, hash alterado, duplicado renombrado,
versión/hash de preview obsoleto, permisos, límites y ausencia de inferencias.

No se migró ninguna base real. B11 y los originales permanecen sin modificar.
