# B10: clasificación documental revisada, sin efecto económico

Se incorporan tres códigos completos de una revisión documental del nomenclador: 420101 y 420103 como Consultas (familia «otras» en esta versión), y 180109 como modalidad Imágenes conservando la especialidad Oftalmología.

El módulo `verified_display_nomenclature` contiene extractos revisados y su identidad documental, no un catálogo nuevo ni una verificación automática del archivo original durante cada consulta. Los textos breves son etiquetas de presentación, no transcripciones completas de normas. El registro `REVIEWED_DISPLAY_NOMENCLATURE.json` conserva fila y descripción extraída. El Excel original no se incluye en el código.

La excepción 180109 sólo resuelve el solapamiento documentado Imágenes/Oftalmología. Si aparece evidencia de otra área, vuelve a quedar en conflicto. Las clasificaciones se hacen por código completo: no se rellenan ceros ni se utilizan prefijos. Una fuente registrada corrupta bloquea también estos resultados y sugerencias.

Cinco códigos de una lista de revisión pueden mostrar «Posible imagen: verificar código y documentación; no clasificada». Permanecen sin clasificar y no ingresan al filtro de imágenes por esa sugerencia. No es una equivalencia ni una decisión clínica.

La trazabilidad de cada fila distingue el extracto revisado externo (archivo, hoja, fila y hash) del catálogo registrado. No se modifican aranceles, condiciones económicas, autorizaciones, decisiones ni propuestas de débito. Esquema 30 sin nueva migración.
