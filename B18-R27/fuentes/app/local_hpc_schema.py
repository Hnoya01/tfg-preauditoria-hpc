"""Native local practice identities and immutable documented versions."""
def migration_statements():
    result=['''CREATE TABLE local_hpc_practices (
        id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL REFERENCES datasets(id),source_id TEXT NOT NULL REFERENCES source_registry(id),
        code TEXT NOT NULL,description TEXT NOT NULL,family TEXT NOT NULL CHECK(family IN ('images','other','unclassified')),
        actor_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,UNIQUE(dataset_id,source_id,code))''',
        '''CREATE TABLE local_hpc_versions (
        id TEXT PRIMARY KEY,practice_id TEXT NOT NULL REFERENCES local_hpc_practices(id),ordinal INTEGER NOT NULL CHECK(ordinal>=1),
        previous_id TEXT REFERENCES local_hpc_versions(id),amount_ars TEXT NOT NULL,unit_label TEXT NOT NULL,
        active INTEGER NOT NULL CHECK(active IN (0,1)),effective_from TEXT NOT NULL,
        document_id TEXT NOT NULL REFERENCES evidence_documents(id),document_sha256 TEXT NOT NULL,page_number INTEGER NOT NULL CHECK(page_number>=1),
        excerpt TEXT NOT NULL,reason TEXT NOT NULL,actor_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,
        UNIQUE(practice_id,ordinal))''']
    for table in ('local_hpc_practices','local_hpc_versions'):
        for verb in ('UPDATE','DELETE'):
            result.append(f"CREATE TRIGGER {table}_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'Local HPC history is append-only'); END")
    return tuple(result)
