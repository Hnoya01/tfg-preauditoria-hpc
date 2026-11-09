# Revisión humana de importe RN14 y simulación DEMO

Base a376491354aa90ecf47a328c05eed29860695079, PR #5. Rama feat/rn14-human-review,
PR prevista en borrador sobre feat/hpc-row-applicability. El informe final comunica
SHA remoto, enlace y estado reales; esta descripción no certifica una publicación.

## Alcance y contrato

RF14/RN27/MD10: una fila elegible, diferencia positiva RN14 y un componente sobre el
total. RN25 conserva pendiente, confirmada, descartada y no concluyente; ajustar es
una acción sobre el cálculo, no un nuevo estado de alerta. El revisor con acceso al
conjunto y el administrador según permisos actuales pueden operar; viewer no decide.
No se añaden roles ni se aplica un débito definitivo. Los componentes independientes
no se suman dos veces ni se reemplazan silenciosamente (RN28/MD12).

La decisión y su evidencia se confirman con el circuito existente. Luego, el preview
presenta el resultado RN14 publicado, responsable/fecha/fundamento/evidencia de esa
decisión, referencia, unidad, cantidad, fuente, versión y documentos. El servidor
construye el alcance completo desde Q y la captura; el cliente no elige precios,
fuentes, rubros ni componentes. Confirmar conserva el importe disponible; ajustar
exige decimal exacto no negativo, cálculo y fundamento. Conserva ambos importes.
El motor no interpreta la fórmula libre ni agrega un tope contractual universal.

Ejemplo ficticio: Q=$32; dos prácticas a $15 → comparable $30 y diferencia $2. Se
puede confirmar $2 o ajustar explícitamente a $1,50 guardando automático $2, cálculo
y motivo. Cero determinado con fundamento es distinto de importe desconocido. La
tolerancia $0,01 viene del control: este bloque sólo admite un indicio positivo
mayor a ella. Las diferencias negativas siguen como observaciones, sin generar por
defecto una propuesta de cero. No ejecuta controles al consultar o guardar.

Fuera del bloque: adicionales, normas especiales, acuerdos específicos pendientes,
operaciones masivas, internación y nuevos criterios de negocio. Un registro con
otros componentes/formato ajeno queda disponible para consulta; no se sobrescribe.
La aprobación final del débito permanece fuera del prototipo.

## Reutilización y procedencia

monetary_gate conserva su aritmética, validaciones y rechazo de solapamientos.
Las propuestas reales usan proposal_versions con payload v3; ProposalEvaluator
deriva al adaptador RN14 sólo en ese formato. V2 conserva sus verificaciones de
catálogo original y su lectura. No se fabrican economic_verifications ni se relajan
sus igualdades para forzar equivalencias o precios posteriores.

El adaptador usa row_economic_references de la captura de análisis vigente. Mantiene
código facturado completo y código de valor original separados; conserva el ID de
la versión posterior de precio y su localizador, sin modificar el catálogo. La
unidad se acredita por fila, no alterando la declaración global del lote. La base
incluye firma del resultado, SHA de captura, referencia/dependencias y decisión
exacta, incluido fundamento y evidencia. Las FK de procedencia vinculan el importe
a decisión/aplicabilidad y a su tabla real o simulada.

Descartar o dejar no concluyente se registra por la decisión existente y excluye el
componente del total. Se presenta como no vigente por decisión, conservando su cifra
histórica. Una nueva confirmación/fundamento no reactiva automáticamente el importe:
requiere revisar el cálculo y guardar otra versión. Cambios pertinentes de fuente,
valor, unidad, cantidad o evidencia excluyen lo afectado; lo independiente permanece.
Un precio que empieza después de la práctica no invalida su importe anterior.
El reanálisis continúa explícito y una sucesora no hereda propuestas vigentes.

## Simulación sin eludir A1

La declaración ficticia A1 es persistente y el servidor decide el modo. No hay campo
de entrada para convertir una simulación a propuesta real ni cambiar el origen. El
guardador antiguo sigue rechazando propuestas reales en lotes declarados ficticios.

Las simulaciones están en rn14_simulation_versions, separadas de proposal_versions;
triggers impiden cruzar ambos almacenamientos. Sus salidas usan simulation_only y
simulated_amount_ars. El importe real es nulo en esa operación. /proposals continúa
consultando sólo propuestas reales. La pantalla muestra SIMULACIÓN DEMO e identifica
sus importes y versiones por separado. No se mezclan con el total real ni con las
propuestas reales de otros componentes/filas.

El ZIP conserva rn14_simulation_versions.jsonl y rn14_proposal_references.jsonl;
cada fila tiene un campo rn14_simulation y el manifiesto un subtotal simulado
rn14_simulations separado de current_proposal_total_ars. El cierre conserva IDs de
simulaciones en una lista distinta de proposal_version_ids y muestra ese subtotal
como DEMO. Las descargas usan los bytes congelados. Una declaración ficticia posterior
no renombra un registro real histórico: lo excluye y conserva su procedencia.

## API, concurrencia y migración

GET/POST /api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/rn14-proposal.
El GET usa una lectura consistente y revalida permisos/versiones al salir. POST exige
sesión, origen/CSRF, ambas versiones y preview_sha256. Sólo acepta confirmar o ajustar,
con sus campos; no admite indicar modo/origen/precio. Revalida todo bajo BEGIN IMMEDIATE.
Dos revisores que parten del mismo preview no pisan cambios: uno guarda y el otro
recibe conflicto sin escritura parcial. Una revisión cerrada rechaza acciones.

Esquema 24 aditivo: tabla de simulaciones y tabla de FK de procedencia, historia
inmutable y restricciones de origen/revisión. Las bases existentes requieren servidor
detenido, respaldo coherente y backup-and-upgrade; no se migraron bases operativas.
La regresión 23→24 inyecta un fallo de SQL, exige rollback completo, verifica después
integridad/FK y conserva el respaldo previo. La prueba histórica 22→23 se mantiene
explícita, sin omitirla ni confundirla con la nueva migración.

## Verificación y límites

Focales: 17 Python nuevas, más 13 JS del archivo de valores (seis nuevas RN14 sobre
las existentes); una regresión adicional de cierre verifica subtotal DEMO separado.
Incluyen $2/$1,50/cero/desconocido, tipo de referencia nuevo y lectura anterior,
código completo/precio versionado, rechazo de negativos y componentes ajenos,
fuentes/fundamentos afectados, dos cuentas concurrentes, viewer/CSRF y revocación.
La simulación no entra al total real y el cierre/sucesora conserva historia y ZIP.

La primera corrida focal tuvo 11 errores de helper al buscar dataset_version en una
respuesta que expone otra forma de versión; se corrigió el helper para usar la versión
del conjunto ya registrada. Las siguientes focales aprobaron. Logs previos conservados
en .test-results/rn14-focused-{1..6}.log; no se modificó el control para lograrlo.
Resultado final en Linux: **282 descubiertas, 280 aprobadas, cero fallos/errores y
dos omisiones Windows** (AES-GCM/.NET y ACL NTFS). Son 265 de la base y 17 nuevas;
las 17 nuevas también se ejecutaron dentro del runner protegido. JavaScript: **56
aprobadas**, cero fallos/omisiones (49 de la base y siete nuevas). `pip check` correcto.
Logs: .test-results/rn14-python-1.log y rn14-python-1-summary.json,
rn14-node-final.log y rn14-pip-check.log. La suite completa terminó en su primera
corrida, sin reintentos ni relajación de las aserciones.

Chromium y API temporal sólo en loopback: decisión RN14 confirmada por el circuito
existente, simulación de $2, ajuste a $1,50 y descarte posterior; dos versiones
simuladas, cero propuestas reales y ningún análisis disparado por guardar. El ZIP
provisional conservó $1,50 simulado y total real nulo. El fundamento con HTML quedó
inerte; cero errores de página y cero peticiones externas. Evidencia local excluida
de Git: .test-results/rn14-browser.json y rn14-browser-adjusted.png. Se retiraron
servidor, base, usuarios y exportación temporales. No es aceptación con personas.

La regresión de cierre conserva $2 sólo en el manifiesto simulado, IDs separados,
ZIP idéntico tras crear sucesora e historial no heredado como vigente. El respaldo y
restauración ficticios conservan las dos tablas nuevas, fingerprint lógico y bytes
del ZIP. La migración 23→24 conserva la cuenta ficticia, respaldo de esquema 23,
integridad/FK y rollback ante fallo SQL inyectado. Las regresiones anteriores
H1–H3/N1–N2 se ejecutaron como parte de la suite; no se reabrieron por asociación.

Inventario: **150 entradas, 149 hashes/tamaños coincidentes** y autoentrada sin
autohash; sin archivos ajenos. Se conservaron SOURCE_HASHES, preparación original y
locks. La verificación del índice antes del commit debe coincidir con estos bytes;
el informe final identifica el SHA remoto para la revisión independiente del usuario.

```sh
.tmp/validation-venv/bin/python -B -m scripts.run_synthetic_tests
node --test tests/web_processing.test.cjs tests/web_sheet_actions.test.cjs tests/web_values.test.cjs tests/web_workbench.test.cjs tests/web_closure.test.cjs tests/web_revisions.test.cjs
.tmp/validation-venv/bin/python -m pip check
```

Venv dedicado reutilizado; sin dependencias nuevas ni cambios de locks. SOURCE_HASHES,
PREPARACION y metadatos de preparación original se conservan. Sólo código, regresiones
ficticias y documentación/inventario se incorporan al paquete; no bases, logs, venv,
capturas ni credenciales. No se invoca Astra: revisión independiente a cargo del usuario.
Windows del SHA nuevo y aceptación humana UI siguen pendientes; Windows anterior y
navegador no equivalen a esas validaciones. Las omisiones Linux AES-GCM/ACL no validan
Windows y un respaldo de misma máquina no certifica recuperación ante desastre.
