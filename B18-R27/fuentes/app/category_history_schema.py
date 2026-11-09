"""Append-only category corrections and internal registration requests."""
def migration():
    statements=[
        """CREATE TABLE hpc_category_corrections (
            dataset_id TEXT NOT NULL,code TEXT NOT NULL,family TEXT NOT NULL CHECK(family IN ('images','other')),
            description TEXT NOT NULL,batch_id TEXT NOT NULL REFERENCES batches(id),
            revision_id TEXT NOT NULL REFERENCES revisions(id),invoice_row INTEGER NOT NULL,
            source_sha256 TEXT NOT NULL REFERENCES stored_files(sha256),source_file TEXT NOT NULL,
            sheet TEXT NOT NULL,source_row INTEGER NOT NULL,source_column INTEGER NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,dataset_version INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal>=2),reason TEXT NOT NULL CHECK(length(trim(reason))>=10),
            PRIMARY KEY(dataset_id,code,ordinal),FOREIGN KEY(dataset_id,code) REFERENCES hpc_display_categories(dataset_id,code))""",
        """CREATE VIEW hpc_category_history AS SELECT h.*,1 AS ordinal,NULL AS reason FROM hpc_display_categories h
           UNION ALL SELECT * FROM hpc_category_corrections""",
        """CREATE TABLE practice_requests (
           id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL REFERENCES datasets(id),batch_id TEXT NOT NULL REFERENCES batches(id),
           source_id TEXT NOT NULL REFERENCES source_registry(id),invoice_row INTEGER NOT NULL,code TEXT NOT NULL,description TEXT NOT NULL,
           kind TEXT NOT NULL CHECK(kind IN ('category','agreement')),reason TEXT NOT NULL,actor_id TEXT NOT NULL REFERENCES users(id),
           created_at TEXT NOT NULL)""",
        """CREATE TABLE practice_request_outcomes (
           request_id TEXT PRIMARY KEY REFERENCES practice_requests(id),state TEXT NOT NULL CHECK(state IN ('registered','declined')),
           target TEXT,reason TEXT NOT NULL,actor_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL)""",
        "CREATE INDEX practice_request_codes ON practice_requests(dataset_id,code,kind,source_id)"
    ]
    for table in ('hpc_category_corrections','practice_requests','practice_request_outcomes'):
        for op in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable history'); END")
    return tuple(statements)
