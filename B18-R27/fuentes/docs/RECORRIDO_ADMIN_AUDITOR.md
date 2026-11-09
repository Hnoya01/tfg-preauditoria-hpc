# Recorrido administrativo y auditor — incremento local del 01/11/2026

## Decisión y trazabilidad

Autorizado por el usuario después de evaluar las maquetas: el administrativo puede
resolver diferencias de suma, de convenio y autorizaciones sin localizar, con
fundamento y respaldo. Consulta cuando duda o excede su competencia. El auditor
resuelve lo consultado sin segunda aprobación administrativa; otras observaciones
siguen pendientes. Pedir información y registrar una respuesta externa no resuelven.
La autorización permite implementar en rama aislada, documentar y probar ficción;
no permite publicación remota, PR, merge, despliegue ni operar datos reales.

Base comprobada: `a7ad15756cb187d2130ddf13e963adec4eb630a8`, rama remota
`feat/consultas-respuestas-externas`, PR #7. `main` permanecía en
`dcaa39174259e8df05cff4f0b2baa81b92beae55`. Rama local nueva:
`feat/recorrido-admin-auditor`. No se descartó trabajo previo.

REQUISITOS_TP.md conserva su extracto literal. Esta decisión funcional posterior
amplía el recorrido interno; **no modifica el documento académico original**.
RN26/MD09 describen al médico consultado y su acceso acotado: su correspondencia
externa sigue sin resolver alertas. El Auditor de este incremento es una función
de revisión interna con capacidad reviewer existente, no una cuenta médica con
acceso automático a toda la facturación. La sincronización del TP original y el
acceso médico por fragmentos siguen pendientes; no se leyó un nuevo Word/PDF.
RN04/CP03 mantienen revisión individual sin obligación de confirmar toda fila.
RN28/MD12 rigen vigencia y concurrencia; RN29/MD11 siguen regulando el cierre global,
que es distinto de resolver una observación.

## Capacidades reales

Se reutiliza **reviewer por conjunto**, comprobado en servidor en cada lectura,
escritura y replay; admin conserva su capacidad existente. Una cuenta sin acceso
o con viewer no puede utilizar el circuito. No se asignan permisos ni cuentas
reales al migrar. La demo crea dos cuentas individuales ficticias con reviewer
sobre un único conjunto ficticio: administrativo y auditor.

El selector «Función de trabajo» organiza acciones y bandeja; **no es una frontera
de seguridad entre esas dos funciones**. Ambas son revisores internos con la misma
capacidad existente. No se introduce un rol médico, ni una separación obligatoria
entre «auditor resolutor» y «médico consultado». Los endpoints validan función,
transición, acceso al conjunto, estado de revisión y evidencia. Las operaciones
anteriores del reviewer siguen disponibles con sus permisos anteriores. Si se
requiere restringir formalmente qué revisor puede ejercer cada función, eso exige
un diseño de capacidades adicional; esta versión no afirma esa separación.

«Consultar todos los casos» consulta las observaciones del conjunto seleccionado
que la cuenta puede revisar, entre sus facturas. El selector de conjuntos permite
pasar a los otros conjuntos permitidos. La bandeja identifica prestador declarado
(o «Prestador por comprobar»), archivo/factura, afiliado, fecha, práctica e importe.
No se infiere prestador desde el nombre del archivo ni aprobación desde un aviso.

## Modelo y transiciones

La identidad es revisión + fila + control. Los resultados automáticos no se
reescriben. `observation_events` añade una historia inmutable de gestión, asociada
al análisis y a la cuenta que actuó. No copia la prestación a otra bandeja.

| Trabajo actual | Acción explícita | Resultado |
| --- | --- | --- |
| Pendiente | Administrativo resuelve con fundamento y respaldo | Observación resuelta |
| Pendiente | Administrativo consulta con pregunta y comprobaciones | Consulta al auditor |
| Consulta al auditor | Auditor pide información | Esperando información / Completar información solicitada |
| Esperando información | Administrativo aporta respuesta y respaldo | Consulta al auditor; todavía sin resolver |
| Consulta al auditor | Auditor guarda resolución | Sólo esa observación resuelta |
| Evidencia por actualizar | Reanálisis explícito y revisión posterior | Se conserva historia; se recalcula vigencia |

Una resolución de un indicio inserta la decisión humana ya existente y el evento
interno **en una única transacción**. Las resoluciones sobre información insuficiente
registran la conclusión humana en el circuito, sin convertir el control automático
en ejecutado/aprobado ni eliminar limitaciones del cierre. La pantalla distingue
ambas categorías. Confirmar una observación significa confirmar el problema con
respaldo; no autorizar una práctica ni generar un débito.

Los controles no ejecutados siguen no ejecutados. Una orden no equivale a una
autorización. Al resolver autorización sin localizar, se exige explicitar requisito,
respaldo o motivo de no exigibilidad. A1 no contiene importes autorizados; no se
agregó comparación monetaria ficticia con la plataforma. La suma 10 + 20 frente
39 señala una diferencia, sin inferir que corresponde debitar 9. Para RN14, cuando
hay referencia aplicable, el panel muestra tarifa, cantidad, comparable, facturado,
diferencia, vigencia, equivalencia, fragmento y enlace privado al convenio.

Cada escritura verifica dataset/revisión/análisis y evidencia vigente dentro de
BEGIN IMMEDIATE. Una clave de operación por cuenta conserva cuerpo exacto,
incluidas versiones; un reenvío idéntico devuelve el mismo ID sin repetir decisiones,
eventos o incrementos. Otro cuerpo con esa clave se rechaza. Se vuelven a comprobar
permisos incluso si la operación ya había sido guardada. El replay histórico puede
confirmar el registro después del cierre; una nueva escritura allí se rechaza.

Si cambia evidencia relevante, se muestra «Evidencia por actualizar». Tras análisis
explícito, la gestión previa se conserva sólo cuando resultado y dependencias son
equivalentes, indicando su reutilización; de lo contrario queda en historia y se
avisa que hace falta revisión nueva. No se borra historia ni se modifica un cierre.
Una revisión sucesora no hereda silenciosamente eventos internos; la anterior
conserva su exportación e historia. El ZIP añade `observation_events.jsonl` para
revisiones nuevas del esquema 27; los ZIP históricos no se reconstruyen.

El navegador conserva operaciones inciertas sólo en memoria de la sesión,
con cuerpo/clave originales, incluso al cerrar/reabrir el panel. Advierte antes de
abandonar el documento. Cambiar cuenta/logout las retira. Tras respuesta confirmada,
un fallo de refresco no se presenta como «no guardado». No hay reintento automático.
Una recarga completa pierde la memoria local: comprobar historia antes de registrar
otra operación. No se guardan textos privados en almacenamiento persistente web.

## Recorrido de prueba para Hernán

Usar la rama local entregada y el venv del proyecto. Para una demostración nueva:

```powershell
.\.venv\Scripts\python.exe -m scripts.create_review_journey_demo
$env:TFG_DATA_DIR = Join-Path (Get-Location) '.tmp/recorrido-ficticio'
$env:TFG_PUBLIC_ORIGIN = 'http://127.0.0.1:8000'
$env:TFG_LOCAL_HTTP = '1'
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Linux: `.venv/bin/python -m scripts.create_review_journey_demo`, exportar esas mismas
variables (TFG_DATA_DIR="$PWD/.tmp/recorrido-ficticio") y ejecutar
`.venv/bin/python -m uvicorn app.api:app --host 127.0.0.1 --port 8000`.
El generador rechaza un directorio existente; para repetir usar `--name otro-ensayo`.
Las credenciales aleatorias quedan sólo en `credenciales-demo.txt` dentro del
directorio ficticio; no se incluyen en Git ni en capturas. No usar la demo con datos
reales. No expone un puerto público ni envía comunicaciones.

1. Abrir http://127.0.0.1:8000, entrar como `demo-administrativo`, elegir conjunto
   DEMO y factura A. En Prácticas elegir **Todas las prácticas**: no hay catálogo
   real en esta demo. La grilla permite agrupar por afiliado y conserva filas sin
   indicios para contexto. Los grupos pueden continuar en otra página.
2. En Carla Ficticia, pulsar **Revisar** y elegir posible repetición. Consultar al
   auditor con una pregunta concreta y lo comprobado; el motivo de suma permanece.
3. Salir y entrar como `demo-auditor`, elegir el mismo conjunto y factura y la
   función **Auditor**. Abrir derivaciones y **Revisar e historia**.
4. Pedir información. El auditor ve **Esperando información**. El administrativo
   ve **Completar información solicitada**. Completar conserva el pendiente.
5. Como auditor, revisar las dos constancias ficticias descritas en el respaldo,
   descartar sólo la duplicación y **Guardar resolución** con confirmación humana.
   La diferencia de suma sigue pendiente. Horarios diferentes, por sí solos, no
   establecen autorización ni derecho a facturar; el ejemplo no crea esa regla.
6. Como administrativo, resolver la suma con explicación y respaldo. El importe
   original sigue siendo 39; no hay débito. Abrir historia y comprobar autor/fecha.
   Las limitaciones de autorizaciones y convenio siguen explícitas en esta demo.
7. **Siguiente sin decidir** avanza a la siguiente fila de la página sin decidir.
   Cerrar el panel vuelve a la misma grilla. La última fila no ofrece un avance falso.

## Migración, verificación y límites

Esquema 26→27 aditivo: una tabla, índice y triggers de inmutabilidad/alcance.
Detener el servidor y ejecutar el procedimiento existente `backup-and-upgrade`
antes de abrir una base anterior. El arranque normal rechaza migración implícita.
Para volver atrás, usar código anterior y respaldo 26 juntos en otro directorio;
no borrar tablas ni abrir esquema 27 con código 26. No se migraron datos reales.
Se conserva SOURCE_HASHES.json como huellas históricas; INVENTARIO.json describe
la entrega actual. La prueba histórica 25→26 mantiene explícitamente ese destino;
la recuperación del esquema actual comprueba 27.

Pruebas y fallos de esta entrega se registran en ESTADO.md. Implementación y pruebas
sintéticas no equivalen a aceptación de Hernán ni validación Windows. Las maquetas
Library 08_roles_administrativo_v2.png y 09_roles_auditor_v2.png se resolvieron por ID,
pero ambas transferencias y el único reintento fallaron; no pudieron inspeccionarse
sus píxeles. Se inspeccionaron las capturas de la interfaz implementada.

Limitaciones: la bandeja recorre el conjunto seleccionado sin paginación propia;
se comparte el cálculo de vigencia por lote, pero no hay benchmark de múltiples
facturas grandes. El caso de más de mil filas sigue en la suite de grilla. Adjuntos
nuevos a derivaciones no se agregan: se registra respaldo textual/localizador y se
usan los originales existentes. Acceso médico por fragmentos, envío externo,
separación formal de funciones internas y validación académica original no se
presentan como implementados. No hay aprobación clínica ni económica automática.

## Ajuste de interfaz tras revisión del coordinador

El commit 61af5ff queda como antecedente. El coordinador inspeccionó las maquetas y
las capturas e identificó exceso de panel lateral y pérdida de contexto. La revisión
actual usa panel inferior, encabezado estable con afiliado/práctica/fecha/importe y
formulario a su lado. Los filtros vuelven al cerrar; su selección no cambia. El resumen
de pendientes se despliega a demanda y no se ofrece resolución al pedir información.
El Auditor ve primero la pregunta y lo comprobado. La resolución confirmada informa
su autor y pendientes; no cierra otras observaciones.

La demo ahora genera 12 prestaciones agrupadas en Carla, Bruno y Diana, cuatro por
persona, y una segunda factura ficticia. Las filas sin indicios conservan información
insuficiente donde faltan fuentes. Prestador por comprobar es literal: no se inventa
un convenio para la demo. Los ensayos a 1440×900 y 1366×768 mantienen varias filas,
encabezado y acción visibles. El detalle largo del respaldo/historia puede desplazarse
sin mover el encabezado ni las acciones. No se declara aceptación humana ni Windows.

`node tests/browser_observation_workflow.cjs` crea una demo aislada nueva, usa ambas
cuentas, guarda capturas en las dos resoluciones y elimina su directorio al finalizar.
Usa el Python del venv según plataforma (o TFG_BROWSER_PYTHON), sin imprimir claves.
