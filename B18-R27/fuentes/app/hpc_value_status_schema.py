"""Append-only logical status history for existing HPC references."""
def migration_statements():
    return ('''CREATE TABLE hpc_value_status_versions (
        id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
        source_id TEXT NOT NULL REFERENCES source_registry(id), tariff_seq INTEGER NOT NULL,
        ordinal INTEGER NOT NULL CHECK(ordinal>=1), previous_id TEXT REFERENCES hpc_value_status_versions(id),
        active INTEGER NOT NULL CHECK(active IN (0,1)), effective_from TEXT NOT NULL,
        document_id TEXT NOT NULL REFERENCES evidence_documents(id), document_sha256 TEXT NOT NULL,
        page_number INTEGER NOT NULL CHECK(page_number>=1), excerpt TEXT NOT NULL, reason TEXT NOT NULL,
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        UNIQUE(dataset_id,source_id,tariff_seq,ordinal))''',
        '''CREATE INDEX hpc_status_lookup ON hpc_value_status_versions(dataset_id,source_id,tariff_seq,effective_from,ordinal)''',
        '''CREATE TRIGGER hpc_status_no_update BEFORE UPDATE ON hpc_value_status_versions BEGIN SELECT RAISE(ABORT,'Status history is append-only'); END''',
        '''CREATE TRIGGER hpc_status_no_delete BEFORE DELETE ON hpc_value_status_versions BEGIN SELECT RAISE(ABORT,'Status history is append-only'); END''')

