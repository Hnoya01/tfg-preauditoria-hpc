# Preparación de la copia — 26/10/2026

## Alcance y trazabilidad

Preparación autorizada para futura publicación privada y desarrollo en nube. No se inicializó Git,
configuraron accesos, crearon commits, publicaron archivos ni modificó el proyecto operativo.
Se leyó únicamente la lista explícita COPY_ALLOWLIST.txt para copiar código: 92 archivos.
Los extractos normativos se obtuvieron del TP privado autorizado sin copiar el documento original.
Las decisiones y contratos se revisaron por separado para quitar resultados operativos y rutas personales.
Los directorios denegados no se consultaron. No se trasladaron carpetas completas para limpiarlas después.

INVENTARIO.json enumera exactamente los archivos preparados para revisión/publicación, con hashes
salvo su propio contenido. SOURCE_HASHES.json conserva las huellas anteriores a los cambios de la copia.
No incluye entornos ni resultados de ejecución. Todo nombre ausente queda fuera de la entrega fuente.

## Cambios y razón

- .gitignore cubre datos, fuentes, bases/journals, secretos, documentos, respaldos y generados a cualquier profundidad.
- README distingue Windows/Linux, dependencia documental opcional, instalación, pruebas y demo local.
- requirements.txt, requirements-dev.txt y requirements-lock.txt permanecen sin cambios.
- requirements-documentary.txt declara pypdf 6.10.0, inspeccionado en el runtime disponible.
- tests/temp_support.py crea el directorio temporal padre; los tests que importaban TemporaryDirectory
  utilizan ese helper. No cambian aserciones, resultados esperados ni decoradores de omisión.
- tests/__init__.py y scripts/__init__.py hacen inequívocos los paquetes locales.
- scripts/run_synthetic_tests.py configura la ejecución aislada y conserva resultados por estado.
- El auxiliar documental sólo cambia su explicación de instalación.
- Código app/, web/ y fixtures/ idéntico al original. Se conserva common_passwords.txt.
- REQUISITOS_TP conserva 71 bloques normativos (RF, RNF, RN, ALC, CP, MD), sin inventar numeración.
  La especificación conserva prioridad; no se afirma que todos sus requisitos estén implementados.

## Entorno de comprobación

Venv nuevo, Python 3.12.14 Windows, sin system-site-packages; Node 24.13.0.
La creación inicial de venv no completó ensurepip por su ubicación temporal; se resolvió utilizando
un temporal privado en la copia. pip no pudo resolver el índice por error DNS.
Se preparó el venv offline copiando sólo los archivos enumerados por los metadatos de las 21
versiones exactas del lock instalado, más pypdf 6.10.0 del runtime auxiliar. Se omitieron bytecodes
y entradas fuera de site-packages. No se instaló ni modificó nada en el entorno original.
Esto permite probar la copia, pero no demuestra instalación limpia desde el índice ni portabilidad Linux.
pip check dio errores transitorios durante la preparación incompleta; repetido tras terminarla aprobó.
Dos intentos iniciales de suite fueron interrumpidos sin resultado por el socket interno asyncio
bloqueado en el entorno restringido. El diagnóstico identificó socketpair/TestClient, no una aserción
funcional fallida. Se solicitó ejecución con sockets locales habilitados, conservando el aislamiento
de archivos y todas las protecciones de la aplicación. No se lanzó un servidor público.

## Pendientes de nube

1. Instalación desde índice en venv limpio; verificar versiones, disponibilidad y pip check.
2. Ejecutar suite y pruebas JavaScript en Linux; generar lock Linux separado sólo si es necesario.
3. Validar cifrado/recuperación con PowerShell 7/.NET o preparar una alternativa equivalente revisada;
   las ACL NTFS requieren diseño POSIX y pruebas de permisos. Dos tests originales se omiten en Linux.
4. Probar almacenamiento persistente privado, SQLite WAL/bloqueos, reinicios, permisos, respaldos,
   recuperación independiente y concurrencia. No asumir seguridad ni durabilidad del volumen.
5. Probar origen HTTPS, cookies, CSRF, acceso privado al puerto y sesiones detrás del proxy elegido.
6. Mantener todas las pruebas de nube sobre datos ficticios. A1 real, I1, MD04/contradicciones,
   aplicabilidad económica, cierre/revisiones y aceptación de interfaz conservan sus pendientes.
7. Elegir proveedor/entorno y autorizar configuración de accesos/publicación en una tarea posterior.

El resumen vigente de pruebas de esta copia está en ESTADO.md; los estados históricos operativos
no se trasladaron ni se utilizan como acreditación de esta entrega.
