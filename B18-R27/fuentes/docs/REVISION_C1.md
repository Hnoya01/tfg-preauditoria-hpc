# Paquete de revisión C1 — pendiente de revisión independiente

Implementación autorizada por el usuario, excluyendo explícitamente revisión Astra durante
el bloque. No se invocaron revisores independientes. Este paquete queda preparado para que
el usuario realice esa revisión. No constituye una aprobación del TP completo.

## Referencias y alcance

Base: 0d244d28cb56529da53dbf39b3969b291201e94b (PR #2).
Rama separada: feat/revision-close. La PR C1 apunta a fix/recovery-review-history.
Código/tests a revisar: dbd8e15fdc67e836751efa9d375b92b7a170788b, con commits por comportamiento:
3425c09 (backend/migración), 395a0a4 (interfaz) y dbd8e15 (regresión de fuente posterior).
El informe final indica el SHA completo del paquete con documentación/inventario. Comparar
contra la base anterior; main, MIME y la rama de PR #2 permanecen intactas.

C1 atiende RF11/RF12, RN29/RN31 y MD08/MD11/MD12: vista previa, limitaciones justificadas,
confirmación explícita, cierre atómico e inmutable y descarga de captura conservada.
C2/RF16/RN30 (nueva revisión) queda fuera. No hay despliegue, fusión ni datos reales.

## Archivos y decisiones técnicas para revisar

- app/closure.py: catálogo de evaluaciones, causas/alcances, fundamentos versionados,
  confirmación, preparación de archivo y revalidación al confirmar. Una causa compartida
  vincula todos los controles afectados, incluidos los que no tienen ResultadoControl.
- app/db.py: migración aditiva 20, limitaciones/asociaciones/cierres, FK y triggers de
  inmutabilidad. Los registros cerrados no se reabren; C2 deberá crear otra revisión.
- app/provisional.py: captura interna reutilizable desde un snapshot del llamador, sin
  auditoría de exportación provisional al preparar un cierre. El modo sin ejecución sólo
  se usa internamente para C1, y declara not_executed sin fabricar resultados.
- app/storage.py: publicación de capturas generadas; se conserva el límite 16 MiB de las
  fuentes recibidas. El archivo se prepara antes del commit de cierre; un rollback puede
  dejar huérfanos privados visibles, sin registro de cierre ni estado falsamente completado.
- app/api.py: rutas de preview/fundamento/confirmación/descarga con rol de revisión;
  POST usa el control de origen/CSRF ya existente. Descarga revalida acceso después de leer.
- web/closure.js y conexión en index/app: versiones/alcances congelados en cada acción,
  selección expresa, rechazo sin reintentos automáticos, descarte de respuestas de otro
  contexto y preservación de borradores de fundamentos de otros alcances sin cambios.

Se incluyen RN20/RN21/RN22 como controles documentales sin implementar y de aplicabilidad
sin verificar. Requieren fundamento compartido y confirmación; no se convierten en no
aplicables ni en aprobados. Los controles afectados exigen reevaluación o limitación expresa;
las alertas pendientes siguen bloqueando el cierre. No se cambian reglas económicas.

El alcance de una limitación liga filas/reglas, resultados/evidencia y entradas pertinentes.
Si cambia, el fundamento anterior queda histórico y no satisface automáticamente el alcance
nuevo. Los fundamentos vigentes se reutilizan y se confirman, sin pedir reescribirlos.

La captura congelada conserva fuentes, resultados, decisiones, versiones de propuestas,
exclusiones y cobertura del exportador existente, más closure_controls.jsonl y
closure_limitations.jsonl. El manifiesto identifica cierre, actor/fecha, referencias y
limitaciones. La descarga devuelve los mismos bytes y verifica hash; no consulta evaluadores.

## Evidencia a contrastar

En .test-results/ (local, excluido de Git):
- c1-before.log: reproducción inicial (rutas C1 ausentes, 404).
- c1-targeted-final.log, c1-source-change.log: casos de cierre y cambio de fuente posterior.
- c1-python.log y c1-python-summary.json: ejecución completa final del runner aislado.
- c1-node.log y c1-web.log: pruebas JavaScript existentes y seis nuevas de confirmación.
- c1-browser.json, c1-preview.png y c1-closed.png: Chromium real en loopback, siete fundamentos
  y siete confirmaciones expresas en el caso ficticio, cierre y dos descargas idénticas.
- c1-inventory-check.json: paquete y hashes verificados.

Pruebas principales: pendientes/no justificados bloquean; controles sin ningún análisis
pueden cerrarse sólo con limitaciones explícitas; conflicto tras preparar no deja cierre
parcial; rollback de auditoría conserva revisión abierta; rol/CSRF/sesión revocada rechazan;
cambio de alcance invalida el fundamento; procesamiento activo bloquea; fuentes posteriores
no alteran el archivo; no se recalcula al descargar; migración v19 respaldada y rollback.
La fixture histórica de migración v18 selecciona ahora su versión explícita y comprueba el
último esquema, conservando las aserciones anteriores; no se omiten tests para la migración 20.

## Límites y revisión pendiente

Windows sigue pendiente: usar el SHA del informe final y VERIFICACION_WINDOWS.md en una copia
nueva. Dos omisiones Linux no validan cifrado/ACL equivalentes. Las migraciones y pruebas de
recuperación de este bloque fueron únicamente sintéticas; no se migró ninguna base operativa.
No se midió carga máxima de cierre: el preview y congelado construyen alcance/ZIP en memoria
y la confirmación revalida dentro de una transacción. No se afirma rendimiento con 100.000 filas,
recuperación externa, prueba de caída física durante escritura ni aceptación de usabilidad.

La revisión del usuario debe comprobar especialmente atomicidad, cobertura de controles sin
resultado, vigencia de fundamentos, permisos, ausencia de aprobación económica y separación
entre captura cerrada y fuentes posteriores. Registrar hallazgos antes de cualquier integración.
