# B14: CSV y candidatos de correspondencia por catálogo

El CSV conserva código completo, cada orden y posición de práctica, originales por hash y localizadores; no convierte movimientos a aprobación individual. La vista previa informa motivos y localizadores de cuarentena por fila. Véase HPC_CSV_INTAKE.md para el contrato exacto.

La correspondencia exacta existente no cambia. Se añade un resultado separado `catalog_relationships` al detalle de correspondencia y recuentos en planilla. No entra al selector de vínculos exactos, al motor de autorización, ni genera decisiones o débitos.

## Relaciones permitidas
- Código factura y código de autorización declarados como HPC, con identidad de práctica coherente y unívoca (practice_seq/id).
- Código factura declarado como NOMENCLADOR/kind=nomenclador, enlazado explícitamente a prácticas HPC. Puede ser una categoría amplia: se conserva cada práctica y se rotula expresamente como categoría, NO equivalencia.
- Se exige fuente registrada verificada por SHA-256, conjunto correcto y alcance HPC confirmado. No se usan fuentes de otro prestador.
- Ningún corte de prefijo, eliminación o agregado de ceros, nombre parecido o precio establece una relación. Los conflictos entre identidades de códigos HPC bloquean ese enlace.

## Límites
La identidad del afiliado usa la normalización ya documentada, sin coincidencia aproximada. No se eliminan órdenes ni prácticas repetidas. Las fechas de orden no se convierten en fecha de prestación. Fecha o prestador discrepante se muestran incompatibles; ausencia queda incierta. La factura excluida por período o alcance no recibe candidatos. La cobertura de la captura queda sin verificar.

Se muestran hasta 200 candidatos, conservando el total y aviso de límite. Cada candidato conserva hash del catálogo, filas de códigos, identidad de práctica y localizador del ítem original. Las categorías amplias pueden tener varias opciones; ninguna se selecciona automáticamente.

## Prueba autorizada aislada (solo agregados)
CSV: 2470 órdenes y 3693 ítems aceptados; 5 órdenes en cuarentena explícita. Contra la factura, 154 filas tuvieron 281 ocurrencias candidatas por identidad+relación declarada: 34 enlaces entre códigos HPC y 247 enlaces desde categorías del nomenclador. 41 filas tuvieron múltiples opciones. Todos los candidatos carecen de fecha de prestación declarada en el CSV: no se aprobó ninguno. Estas cifras no son el número de autorizaciones válidas ni de pacientes.

Prefijos estudiados aparte:150 de209 códigos completos tienen primer bloque de6 coincidente con la factura, pero22 prefijos reúnen varios códigos completos;126 de150 tienen sufijo no cero. No se incorporó una regla de truncamiento. La presencia de un enlace de catálogo tampoco certifica equivalencia clínica.

Validación:56 pruebas Python focales y 143 JavaScript; revisión independiente 42 Python. Prueba real sin redes/subprocesos, originales intactos, SQLite íntegro, sin nuevas decisiones, vínculos, ejecuciones de controles, referencias económicas ni débitos. Compatible con los filtros múltiples B13. No requiere migración adicional (esquema 30). Falta aceptación manual en Windows; no confundir pruebas de DOM con navegador real.
