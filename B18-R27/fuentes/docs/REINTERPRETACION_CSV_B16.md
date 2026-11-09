# B16: resoluciones individuales y reinterpretación explícita

El adaptador `hpc-platform-csv-v2` conserva el CSV original. Solo interpreta bloques explícitos «Resolución por ítems» con secciones AUTORIZAR/NO AUTORIZAR, código completo único y evento válido. No transforma un estado global de orden en autorización individual. Las derivaciones CORRESPONDEN/NO CORRESPONDE no autorizan prácticas. Conflictos, códigos repetidos, texto ambiguo o incompleto permanecen indeterminados.

## Una captura ya importada

1. Actualizar código con servidor detenido. Esquema31 requiere `backup-and-upgrade` offline para bases anteriores; respaldo coherente de base y objetos obligatorio. `doctor` debe pasar después.
2. En Autorizaciones, seleccionar el original conservado y consultar la vista previa. La pantalla indica si hay otra interpretación.
3. Registrar el contexto y pulsar **Confirmar nueva interpretación (conservar historia)**. Se exige versión del conjunto, hash de vista previa e ID de captura anterior; una vista obsoleta se rechaza.
4. Se conserva la captura anterior, su manifiesto, su A1 derivado y su fuente. Se crea una nueva captura con ordinal y evento propios, enlazada a la previa y al mismo original. Repetir la operación no duplica interpretaciones. No se permite reinterpretar una recepción histórica para desplazar una recepción posterior del mismo flujo.
5. La selección previa NO se sustituye. Señala captura reemplazada, no fuente corrupta. El operador selecciona expresamente la nueva captura en el alcance del lote abierto y luego solicita el reanálisis. No se ejecutan controles, decisiones ni débitos durante la importación. Cierres y revisiones anteriores no se reescriben.

La comprobación de integridad de las capturas adaptadas usa el manifiesto y A1 derivado propios, no el parser actual: instalar un adaptador nuevo no invalida una interpretación histórica íntegra. Cualquier manipulación del original, manifiesto, derivado o canonical registrado sigue bloqueando su uso.

## Migración y recuperación

Esquema31 elimina la unicidad por upload de capturas y la sustituye por `(upload_id, preview_sha256)`. Fuentes de autorización admiten versiones por `(dataset_id, kind, source_sha256, manifest_sha256)`; valores mantienen su unicidad original. La migración reconstruye tablas en transacción, conserva filas e IDs y verifica claves foráneas antes de confirmar. No modifica capturas ni ejecuta interpretación durante migración.

Aplicar el parche sobre fuentes limpias717c81a, nunca sobre otra entrega acumulativa. La aplicación no migra automáticamente una base existente. Restaurar solo código no baja esquema31: para volver atrás se requiere recuperar base y objetos del respaldo verificado, perdiendo cambios posteriores a ese respaldo.

## Alcance de validación

Pruebas sintéticas de idempotencia, autorización, vistas obsoletas, migración, preservación histórica y captura reemplazada. Revisión independiente con parser B15 v1→B16 v2 y base sintética poblada; preservación de56 tablas y claves foráneas.

Ensayo local cloud sobre COPIA separada de la base real B15:3693 ítems, una resolución individual authorized y una rejected. Los demás estados no se inventan. Originales intactos; sin red, selección automática, decisiones ni débitos. El ensayo prueba interpretación e integridad, no certifica correspondencia factura/práctica ni cobertura documental. Windows y aceptación visual real pendientes.
