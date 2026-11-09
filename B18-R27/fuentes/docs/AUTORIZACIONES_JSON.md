# Contrato canónico de autorizaciones A1-canonical-v1

**Continuación B04a:** integración en controles/revisión/salida disponible sólo mediante análisis explícito, con resultados de demostración identificados y fuentes reales sin validar no concluyentes. No cambia el esquema canónico ni hace que importar una captura apruebe autorización. Un lote que se declaró ficticio no pasa a real cambiando su selección ni admite propuestas monetarias reales.

Este contrato es una decisión técnica local del incremento B01 autorizado. No describe un sincronizador real validado. El código ejecutable está en `app/authorization_json.py`; ejemplos íntegramente ficticios en `fixtures/autorizaciones/`. La fuente real A1 y su cobertura continúan pendientes de validación. No se modifica el sincronizador remoto.

**Actualización B03:** el contrato A1-canonical-v1 no cambia. La vista previa de cantidades y fechas interpreta declaraciones completas y registra datos complementarios por separado. Una general expresa autorizada que identifica ítems, sin cantidad agregada, comprende las cantidades solicitadas identificadas según RN09; una cantidad general agregada no se copia a cada ítem. La importación continúa sin ejecutar análisis ni aprobar autorización. Históricos de B01/B02 que dicen «pendiente B03» describen su cierre; la integración persistente B04 y la validación real siguen pendientes.

## Estructura

JSON UTF-8 (se admite BOM), objeto único. Se rechazan claves repetidas, campos extra, números no JSON como NaN/Infinity y tipos incorrectos. No se convierte un código numérico a texto porque ya podría haber perdido ceros. Cantidades decimales son cadenas de texto o `null`; no se asignan unidades ni cantidades desconocidas como cero. Los textos originales se conservan.

| Objeto/campo | Contrato |
| --- | --- |
| `schema_version` | Obligatorio, literal `A1-canonical-v1`. |
| `data_origin` | Obligatorio: `synthetic` (ficticio) o `real_unvalidated` (origen declarado real, intercambio sin validar). No existe un valor que acredite validación desde el JSON. |
| `source` | Obligatorio. `system` y `stream_id` obligatorios, 1–80 caracteres ASCII alfanuméricos o `_ . : -`. `capture_id` opcional, ID externa; `captured_at` opcional, texto original de fecha/hora. |
| `coverage` | Obligatorio. `declared`: `unknown`, `partial` o `complete`; `description`: texto obligatorio que describe población y alcance. `period` opcional `AAAA-MM`; `limitations`: lista de textos, por defecto vacía. `complete` sigue siendo una declaración sin verificar. |
| `orders` | Lista obligatoria, puede estar vacía. Vacía no prueba ausencia de autorizaciones. |
| Cada orden | Campos opcionales `order_id`, `affiliate_id`, `provider`, `ordered_at`, `global_status`; listas `items` y `resolutions` por defecto vacías. Un estado global no aprueba todos sus ítems. |
| Cada práctica en `items` | `item_id`, `full_code`, `description`, `requested_quantity`, `unit`, `service_date`: textos opcionales o `null`. `position`: entero no negativo opcional, posición declarada, sin convertirla en ID. Códigos completos y ceros se conservan. |
| Cada resolución | Textos opcionales `resolution_id`, `scope`, `status`, `authorized_quantity`, `unit`, `decided_at`, `supersedes_resolution_id`, `reason`; `item_ids`: lista de IDs de ítems de esa orden, por defecto vacía. Los identificadores de reemplazo se conservan sin elegir automáticamente una resolución vigente. |

Alcances reconocidos para observar la estructura: `item` y `explicit_general`, con ítems expresamente identificados. Estados reconocidos: `authorized`, `rejected`, `referred`, `pending`, `unknown`. Otros textos se conservan como información no interpretada y generan una observación; no se traducen por intuición. Resolución parcial y contradictoria se conservan completas. El contrato no contiene precios, débitos, decisiones humanas ni booleanos de aprobación económica.

Fechas: se conserva el texto y se informa precisión de día/minuto/segundo cuando es interpretable. Fecha sola no recibe hora de medianoche. Hora sin zona no recibe zona inferida. Texto temporal desconocido queda observado sin impedir conservar la captura. B01 no ejecuta RN10 ni compara autorización contra realización o incorporación.

Límites operativos: 16 MiB por original y manifiesto; hasta 5.000 órdenes, 10.000 ítems o resoluciones por orden, 25.000 ítems y 25.000 resoluciones en total; profundidad JSON 60 y 250.000 nodos. Textos: IDs de orden/afiliado/prestador/resolución/ítem 200; código 80; fecha 80; cantidad 64; unidad/estado/alcance 100; descripción/cobertura 4.000; motivo 8.000; hasta 100 limitaciones. El exceso de un límite es error de formato/capacidad, no un rechazo de autorización.

## Recepción, interpretación e incorporación

1. Guardar el original privado por SHA-256 y registrar nombre de recepción, responsable y fecha. No incorpora todavía una captura utilizable. Un JSON inválido también puede conservarse para corregir el intercambio sin perder evidencia.
2. Consultar vista previa: formato, conteos, procedencia declarada, cobertura declarada, prácticas/resoluciones, observaciones y huella de interpretación `A1-intake-v1`. No escribe análisis ni decisiones.
3. Incorporar con procedencia contextual obligatoria (10–2.000 caracteres), huella de vista previa y versión actual del conjunto. Se registran original y manifiesto por hash, instantánea canónica, observaciones, responsable, fecha y versión interna. Permiso y versión se revalidan dentro de la transacción.

Mismos bytes en el mismo conjunto, aun con otro nombre: mismo original y misma captura, sin aumentar versión ni reactivar una antigua. Bytes diferentes del mismo `system/stream_id`: nueva versión interna de recepción, encadenada mediante `previous_id`; no se sobrescriben las anteriores. El ordinal corresponde al orden de incorporación, no a cronología clínica ni precedencia de resoluciones. Reutilizar una ID externa se señala; el hash distingue los originales. JSON con otro espaciado tiene otro hash y constituye otra recepción: no se afirma equivalencia semántica. Un flujo no mezcla `synthetic` y `real_unvalidated`; usar flujo/conjunto separado. Para probar, usar siempre un conjunto DEMO separado del real.

La consulta de historia distingue `is_latest_import` de versión histórica. **Última recibida no significa autorización vigente, fuente exhaustiva ni resolución aplicable.** En este incremento no se selecciona una captura para conciliación. El futuro B02 debe definir sus dependencias y separar cabezas de flujos de capturas históricas; no sumar versiones anteriores ni mezclar ficción en controles reales.

## Errores y observaciones

- **Formato/capacidad:** JSON ilegible, esquema/tipo/campo no permitido o límite excedido. Vista previa `technical_state=format_error`, `can_import=false`, localizadores/códigos sin volcar valores privados. Original conservado. Confirmación rechazada.
- **Conflicto de contexto:** formato interpretable, pero un mismo flujo cambia de origen ficticio a real o viceversa. Se muestra aparte y se impide incorporarlo a ese flujo.
- **Información funcional:** faltan identidades/códigos/fechas/cantidades/unidades; referencias no unívocas; estado/alcance no interpretado; prácticas de mismo código; resoluciones aparentemente opuestas. Observaciones con localizador JSON, importables como información incierta. No se corrigen automáticamente ni se elige vínculo, resolución o cantidad aplicable.

No coincidir en una fuente de cobertura desconocida nunca se convierte aquí en rechazo ni ausencia de autorización. No se usa nombre como llave ni se identifica `NroOrden` del Excel con un ID de plataforma. La importación solo añade dependencias a las reglas de autorizaciones mediante la infraestructura existente: RN09/RN10/RN11/RN18 de capturas previas requieren actualización; RN13/RN17 y decisiones independientes conservan su vigencia. No inicia ese reanálisis. Los controles de autorizaciones siguen no concluyentes/no evaluados hasta B02/B03.

El ZIP provisional incluye `authorization_captures.jsonl` con todas las versiones, origen explícito, procedencia, observaciones y estados sin verificar. No incluye por eso un control aprobado ni un importe. Los originales se descargan mediante una ruta autorizada por conjunto y se comprueba su SHA-256 al leer. Las propuestas monetarias y la exclusión común de internación no se modifican. Valores: conservar expresamente **BASE_2026-10-09** donde corresponda.
