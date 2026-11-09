"""Private row attachments and explicit manual reading history, schema 28."""
def migration_statements():
    statements = [
        """CREATE TABLE row_documents (
        id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
        import_id TEXT NOT NULL REFERENCES invoice_imports(id), source_row INTEGER NOT NULL,
        revision_id TEXT NOT NULL REFERENCES revisions(id), category TEXT NOT NULL CHECK(category IN ('informe','autorizacion')),
        sha256 TEXT NOT NULL REFERENCES stored_files(sha256), original_name TEXT NOT NULL,
        provenance TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        request_id TEXT NOT NULL, request_sha256 TEXT NOT NULL,
        UNIQUE(actor_id,request_id), UNIQUE(import_id,source_row,category,sha256))""",
        """CREATE TABLE row_document_reviews (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES row_documents(id),
        revision_id TEXT NOT NULL REFERENCES revisions(id), note TEXT NOT NULL,
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        request_id TEXT NOT NULL, request_sha256 TEXT NOT NULL, UNIQUE(actor_id,request_id))""",
        'CREATE INDEX row_documents_lookup ON row_documents(import_id,source_row)',
    ]
    for table in ('row_documents','row_document_reviews'):
        for operation in ('UPDATE','DELETE'):
            statements.append(f"CREATE TRIGGER {table}_immutable_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable documentary history'); END")
    return tuple(statements)
