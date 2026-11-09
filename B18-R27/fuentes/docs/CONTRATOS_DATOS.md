# Contrato técnico de fuentes

Tabla derivada del contrato vigente; se quitaron recuentos y resultados operativos. Describe el adaptador, no certifica nuevas fuentes. Los originales no se incluyen.

| Campo `Hoja1!fila` | Tipo del adaptador | Significado y uso previsto | Nulos, normalización y límite | Respaldo |
| --- | --- | --- | --- | --- |
| A `R.I.` | numérico | Rendición; contexto, no clave universal | Conservar literal | T1 §Exclusiones; MD01 |
| B `Nro. Orden` | numérico | Número de orden del Excel para búsqueda | Texto literal derivado, sin equipararlo a ID de plataforma | RN04, RN09, MD01 |
| C `Nro.Afiliado` | texto o vacío | Identidad; representa DNI en este circuito | Conservar original; solo para patrón con barra y ceros de relleno, concatenar dígitos y quitar ceros iniciales tras comprobación. Otros formatos: identidad pendiente, sin vínculo automático | RN05; normalización pendiente de validación general |
| D `P/M` | texto | Práctica o medicamento | Conservar valor; no excluir automáticamente medicamentos | T1 §Exclusiones, ALC02 |
| E `Práctica` | numérico | Código de prestación facturada | Convertir a texto sin perder código completo. No usar prefijo para autorización; equivalencia de valores usa primeros 6 dígitos HPC cuando proceda | RN06, RN09, RN14 |
| F `Tipo` | texto | A/I/C del circuito | A=ambulatorio, I=internación, C=alta complejidad; C no equivale a internación | T1 §Exclusiones, ALC02 |
| G `Cant.` | numérico | Cantidad facturada | Mantener decimal/original y validar unidad antes de asignar cobertura | RN11 |
| H `Nombre Afiliado` | texto | Apoyo a revisión de identidad | Dato privado; nombre solo no confirma vínculo | RN05 |
| I `Fecha Práct.` | texto `dd/mm/yyyy` | Fecha de realización | Parseo estricto conservando original y precisión de día; fecha ilegible = indeterminada | RN19; observación local |
| J sin encabezado | numérico | Significado desconocido | Conservar como origen; **no** usar como ítem, vínculo o duplicación | RN06 |
| K `Desc. Práctica` | texto | Descripción para compatibilidad de candidatos | No sustituye código completo | RN09 |
| L `Cod.Auto` | texto o numérico | Dato de origen asociado al circuito | No prueba resolución | T1 §Exclusiones, RN09 |
| M `Médico` y N `Matrícula` | texto; N mixto | Datos de origen del profesional | No usarlos como sustituto de identidad de afiliado/ítem; preservar formato original | MD01; columnas observadas |
| O `Hono.`, P `Dere`, Q `Total ` | numérico, formato `0.00` | Pesos argentinos, importes de **fila** | `Decimal`; `O+P` frente a `Q` con tolerancia $0,01; no multiplicar otra vez por G | RN12–RN13; T1 §Dimensionamiento |
| R `Coseguro` | numérico | Importe de origen | Uso en cálculo pendiente de interpretación documentada; no inferir fórmula de Q | Columna observada; pendiente |
| S `Total original`, T `Total Convenido` | mixto texto/número | Campos monetarios declarados en origen | Su significado y relación con Q no están comprobados para detección. Excluir del motor hasta contrato específico | Columnas observadas; pendiente |
| U `URL` | texto o vacío | Referencia original | No acredita autorización; no abrir automáticamente ni registrar enlace privado en entregables | RN09; localizador privado |
| V `Hono. Debit.`, W `Dere. Debit`, X `Total Debit.`, Y `Motivo débito`, Z `Desc. Motivo`, AA `Devuelve Comprob?` | campo histórico | Etiquetas/resultado histórico de revisión | **Separación estricta:** nunca entradas de detección; eventual evaluación independiente tras etiquetado y validación | T1 §Revisión y Anexo D; observación local |


X1 conserva originales por hash. El período requiere confirmación; A/C elegibles e I excluido según ALC02. Sólo normalizaciones documentadas. A1 se rige por AUTORIZACIONES_JSON.md y no acredita intercambio real. V1 conserva corte BASE_2026-10-09; SQLite y JSON equivalentes no se suman. Una versión nueva no sustituye silenciosamente la anterior.

R–T, J y V–AA quedan fuera del motor según contrato vigente; etiquetas históricas, colores y montos corregidos nunca se usan para detectar. Falta de evidencia temporal I1 mantiene RN10 no concluyente. Los PDF/OCR clínicos son etapa posterior; el cotejo de convenio es documental y no equivale a aprobación económica.
