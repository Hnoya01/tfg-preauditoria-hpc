"""Local operator commands. Passwords are entered interactively, never as arguments."""

from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import secrets

from .db import backup_before_upgrade, connect, database_path, migrate
from .controls import run_controls
from .review import prepare_existing_alerts
from .invoice_x1 import parse_x1
from .security import AccountLocked, authenticate, create_user, issue_session, token_digest
from .service import confirm_invoice, create_batch, create_dataset
from .storage import inventory
from .values_v1 import register_values


def main() -> None:
    parser = argparse.ArgumentParser(description="Operación local del prototipo TFG")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("TFG_DATA_DIR", "data")))
    commands = parser.add_subparsers(dest="command", required=True)
    user_cmd = commands.add_parser("add-user", help="Crear una cuenta individual")
    user_cmd.add_argument("--username", required=True)
    user_cmd.add_argument("--role", choices=["admin", "reviewer", "viewer"], required=True)
    commands.add_parser("doctor", help="Comprobar esquema y objetos sin borrar archivos")
    commands.add_parser("backup-and-upgrade", help="Respaldar base y objetos, verificar y migrar al esquema actual sin servidor activo")
    import_cmd = commands.add_parser("bootstrap-import-x1", help="Crear base privada nueva e importar X1 con período confirmado")
    import_cmd.add_argument("--source", type=Path, required=True)
    import_cmd.add_argument("--period", required=True)
    import_cmd.add_argument("--expected-sha256", required=True)
    import_cmd.add_argument("--dataset-label", required=True)
    import_cmd.add_argument("--username", required=True)
    values_cmd = commands.add_parser("register-values-v1", help="Registrar el SQLite V1 y A1 pendiente en un conjunto existente")
    values_cmd.add_argument("--source", type=Path, required=True)
    values_cmd.add_argument("--manifest", type=Path, required=True)
    values_cmd.add_argument("--expected-sha256", required=True)
    values_cmd.add_argument("--dataset-id", required=True)
    values_cmd.add_argument("--username", required=True)
    values_cmd.add_argument("--password-file", type=Path, required=True)
    analyze_cmd = commands.add_parser("analyze-batch", help="Ejecutar explícitamente P04 sobre un lote importado")
    analyze_cmd.add_argument("--dataset-id", required=True)
    analyze_cmd.add_argument("--batch-id", required=True)
    analyze_cmd.add_argument("--username", required=True)
    analyze_cmd.add_argument("--password-file", type=Path, required=True)
    alerts_cmd = commands.add_parser("materialize-alerts", help="Crear alertas del último análisis existente sin decidirlas")
    alerts_cmd.add_argument("--dataset-id", required=True)
    alerts_cmd.add_argument("--batch-id", required=True)
    alerts_cmd.add_argument("--username", required=True)
    alerts_cmd.add_argument("--password-file", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_dir.resolve()
    if args.command == "bootstrap-import-x1":
        project = Path(__file__).resolve().parent.parent
        if root.is_relative_to(project) or database_path(root).exists():
            raise SystemExit("Elegí un directorio privado nuevo fuera del proyecto")
        source = args.source.resolve()
        content = source.read_bytes()
        import hashlib
        digest = hashlib.sha256(content).hexdigest()
        if digest != args.expected_sha256:
            raise SystemExit("El hash del original no coincide con el inventario")
        parsed = parse_x1(content, args.period)
        if not parsed.summary["can_confirm"]:
            raise SystemExit("X1 no se pudo interpretar fielmente; revisar bloqueos antes de incorporar")
        password = secrets.token_urlsafe(36)
        root.mkdir(parents=True, exist_ok=False)
        credential_path = root / "initial_admin_password.txt"
        fd = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"Usuario: {args.username}\nContraseña inicial: {password}\n")
        conn = connect(root)
        try:
            migrate(conn)
            user_id = create_user(conn, args.username, password, "admin")
            session, _ = issue_session(conn, user_id)
            actor_token = token_digest(session)
            dataset = create_dataset(conn, actor_token, args.dataset_label)
            batch, _ = create_batch(conn, root, actor_token, dataset["id"], dataset["version"],
                                    source.name, content)
            result, _ = confirm_invoice(conn, root, actor_token, dataset["id"], batch["id"],
                                        args.period, batch["dataset_version"])
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (actor_token,))
            print("Importación confirmada: {physical_rows} filas; {included} dentro, {excluded} "
                  "fuera, {indeterminate} indeterminadas; O {honorarios_ars}, P {derechos_ars}, "
                  "Q {total_ars} ARS".format(**result))
            print(f"Base privada: {root}; credencial inicial: {credential_path}")
        finally:
            conn.close()
        return
    conn = connect(root)
    try:
        if args.command == "backup-and-upgrade":
            backup = backup_before_upgrade(conn, root)
            version = migrate(conn, allow_existing_upgrade=True)
            print(f"Respaldo verificado: {backup}; esquema: {version}")
            return
        version = conn.execute("PRAGMA user_version").fetchone()[0] if args.command == "doctor" else migrate(conn)
        if args.command == "add-user":
            password = getpass("Contraseña (mínimo 15 caracteres): ")
            repeat = getpass("Repetir contraseña: ")
            if password != repeat:
                raise SystemExit("Las contraseñas no coinciden")
            create_user(conn, args.username, password, args.role)
            print("Cuenta creada")
        elif args.command in {"register-values-v1", "analyze-batch", "materialize-alerts"}:
            lines = args.password_file.read_text(encoding="utf-8").splitlines()
            if len(lines) != 2 or lines[0] != f"Usuario: {args.username}" or not lines[1].startswith("Contraseña inicial: "):
                raise SystemExit("Archivo de credencial inicial incompatible")
            try:
                user = authenticate(conn, args.username, lines[1].removeprefix("Contraseña inicial: "), "local-cli")
            except AccountLocked:
                raise SystemExit("Ingreso local restringido temporalmente") from None
            if user is None or user["role"] != "admin":
                raise SystemExit("Cuenta administradora inválida")
            session, _ = issue_session(conn, user["id"])
            actor_token = token_digest(session)
            try:
                dataset = conn.execute("SELECT version FROM datasets WHERE id = ?", (args.dataset_id,)).fetchone()
                if dataset is None:
                    raise SystemExit("Conjunto inexistente")
                if args.command == "register-values-v1":
                    result, created = register_values(
                        conn, root, actor_token, args.dataset_id, dataset["version"],
                        args.source.read_bytes(), args.manifest.read_bytes(), args.expected_sha256,
                    )
                    print(f"V1: {result['cut_label']}; SHA-256: {result['source_sha256']}; "
                          f"registro: {'nuevo' if created else 'existente'}; versión de conjunto: {result['dataset_version']}")
                    print("A1: pendiente; cobertura desconocida; aplicabilidad de V1: no validada")
                elif args.command == "analyze-batch":
                    result, created = run_controls(conn, actor_token, args.dataset_id,
                                                   args.batch_id, dataset["version"])
                    print(f"Análisis: {'nuevo' if created else 'existente'}; captura SHA-256: "
                          f"{result['snapshot_sha256']}; estado: {result['technical_state']}; "
                          f"vigencia: {result['freshness']}")
                    for item in result["counts"]:
                        print(f"{item['rule_code']} {item['result']}: {item['total']}")
                else:
                    result = prepare_existing_alerts(conn, actor_token, args.dataset_id,
                                                     args.batch_id, dataset["version"])
                    print(f"Alertas nuevas: {result['created']}; análisis: {result['run_id']}; "
                          f"versión de conjunto: {result['dataset_version']}")
            finally:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (actor_token,))
        elif args.command == "doctor":
            registered = {row[0] for row in conn.execute("SELECT sha256 FROM stored_files")}
            report = inventory(root, registered)
            print(f"Esquema: {version}; integridad: {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
            print("Objetos registrados: {registered}; huérfanos: {orphan_objects}; "
                  "faltantes: {missing_objects}; temporales: {temporary_files}".format(**report))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
