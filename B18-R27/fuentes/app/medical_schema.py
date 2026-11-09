"""Additive RN26 schema; existing records and closures remain untouched."""
def migration_statements():
    statements = [
        '''CREATE TABLE medical_consultations (
        id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions(id),
        import_id TEXT NOT NULL, source_row INTEGER NOT NULL,
        question TEXT NOT NULL CHECK(length(trim(question)) BETWEEN 10 AND 4000),
        context_json TEXT NOT NULL CHECK(json_valid(context_json)),
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        request_id TEXT NOT NULL, request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
        UNIQUE(actor_id,request_id),
        FOREIGN KEY(import_id,source_row) REFERENCES invoice_rows(import_id,source_row))''',
        '''CREATE TABLE medical_responses (
        id TEXT PRIMARY KEY, consultation_id TEXT NOT NULL REFERENCES medical_consultations(id),
        author_name TEXT NOT NULL CHECK(length(trim(author_name)) BETWEEN 2 AND 200),
        responded_at TEXT NOT NULL,
        channel TEXT NOT NULL CHECK(channel IN ('email','phone','document','other')),
        provenance TEXT NOT NULL CHECK(length(trim(provenance)) BETWEEN 10 AND 2000),
        response TEXT NOT NULL CHECK(length(trim(response)) BETWEEN 10 AND 4000),
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        request_id TEXT NOT NULL, request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
        UNIQUE(actor_id,request_id))''',
        '''CREATE TRIGGER medical_consultation_open BEFORE INSERT ON medical_consultations
        WHEN NOT EXISTS(SELECT 1 FROM revisions r JOIN current_invoice_imports i ON i.revision_id=r.id
        WHERE r.id=NEW.revision_id AND i.id=NEW.import_id AND r.state!='cerrada')
        BEGIN SELECT RAISE(ABORT,'Consultation requires its current open revision'); END''',
        '''CREATE TRIGGER medical_response_open BEFORE INSERT ON medical_responses
        WHEN NOT EXISTS(SELECT 1 FROM medical_consultations c JOIN revisions r ON r.id=c.revision_id
        JOIN current_invoice_imports i ON i.revision_id=r.id
        WHERE c.id=NEW.consultation_id AND r.state!='cerrada' AND NEW.responded_at>=c.created_at
        AND NEW.responded_at<=NEW.created_at)
        BEGIN SELECT RAISE(ABORT,'Response requires its open consultation and consistent dates'); END''',
    ]
    for table in ('medical_consultations', 'medical_responses'):
        for action in ('UPDATE', 'DELETE'):
            statements.append(f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable correspondence'); END")
    return tuple(statements)



def historical_response_migrations():
    """v26: retain stored dates; allow reception before consultation registration."""
    return (
        'DROP TRIGGER medical_response_open',
        """CREATE TRIGGER medical_response_open BEFORE INSERT ON medical_responses
        WHEN NOT EXISTS(SELECT 1 FROM medical_consultations c JOIN revisions r ON r.id=c.revision_id
        JOIN current_invoice_imports i ON i.revision_id=r.id
        WHERE c.id=NEW.consultation_id AND r.state!='cerrada'
        AND NEW.responded_at<=NEW.created_at)
        BEGIN SELECT RAISE(ABORT,'Response requires its open consultation and consistent dates'); END""",
    )
