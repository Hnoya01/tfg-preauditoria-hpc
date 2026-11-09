# Exclusiones y revisión
Se copiaron exclusivamente los nombres de COPY_ALLOWLIST.txt; la documentación nueva se preparó por separado.
No se recorrieron los directorios denegados.
Excluidos: fuentes originales, bases y objetos operativos, documentos Word/PDF/Excel originales,
exports, respaldos, .tmp, .venv, cachés, capturas, logs, credenciales y todo archivo no permitido.
README.txt, informes de estado originales, guías operativas, tareas históricas y scripts de verificación real
no se trasladaron porque mezclan contexto o resultados reales. SOURCE_HASHES.json permite verificar
los archivos de origen permitidos sin revelar su contenido. Los hashes de fuentes documentales presentes
en el código son referencias de integridad funcionales; no se copiaron sus documentos ni catálogos.

Verificado: cinco JSON sintéticos con origen declarado y valores artificiales; tests que crean sus
propios Excel, SQLite, usuarios y PDF mínimos. Las contraseñas de pruebas son literales ficticios,
no se deben usar para cuentas operativas. common_passwords.txt es una lista de rechazo necesaria.
No se certifica material excluido o inaccesible. No se copiaron datos anonimizados de procedencia incierta.
El código de recuperación y cotejo acepta rutas explícitas; no ejecutarlo con fuentes reales en nube.
El auxiliar verify_v9_preservation se conserva como dependencia de recuperación (lectura/hash),
no se ejecutó su CLI de migración real.

Las reglas .gitignore son defensa adicional, no detector de secretos ni limpieza de historial.
No se creó Git ni se configuraron remotos o accesos.
