"""Immutable source-level documentary declarations for exploration only."""
def migration_statements():
    return (
        '''CREATE TABLE agreement_declarations (
        id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
        source_id TEXT NOT NULL REFERENCES source_registry(id), source_sha256 TEXT NOT NULL,
        document_id TEXT NOT NULL REFERENCES evidence_documents(id), document_sha256 TEXT NOT NULL,
        valid_from TEXT NOT NULL, valid_until TEXT, payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)''',
        '''CREATE TABLE agreement_declaration_withdrawals (
        declaration_id TEXT PRIMARY KEY REFERENCES agreement_declarations(id),
        reason TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)''',
        'CREATE INDEX agreement_declaration_source ON agreement_declarations(dataset_id,source_id)',
    ) + tuple(f"CREATE TRIGGER {t}_immutable_{a.lower()} BEFORE {a} ON {t} BEGIN SELECT RAISE(ABORT,'Immutable agreement declaration'); END" for t in ('agreement_declarations','agreement_declaration_withdrawals') for a in ('UPDATE','DELETE'))
