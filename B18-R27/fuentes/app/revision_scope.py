"""Select one revision per immutable invoice, without copying billed rows.

The schema-21 views expose only that revision's working inputs. Physical
append-only evidence tables retain every predecessor. Older schemas are used
only by offline migration fixtures; normal startup requires the latest schema.
"""

SCOPED = ('invoice_imports', 'authorization_match_scopes',
          'authorization_link_versions', 'authorization_input_versions',
          'batch_provider_scope_history')


def revision_table(conn, name):
    if name not in SCOPED:
        raise ValueError('Unknown revision input table')
    return 'current_' + name if conn.execute('PRAGMA user_version').fetchone()[0] >= 21 else name


def next_ordinal(conn, table, where, parameters):
    """Keep physical sequence numbers unique across all revisions of a row."""
    if table not in SCOPED[1:]:
        raise ValueError('Unknown revision history table')
    return conn.execute(f'SELECT COALESCE(MAX(ordinal),0)+1 FROM {table} WHERE {where}', parameters).fetchone()[0]


def migration_statements():
    statements = [
        '''CREATE VIEW current_invoice_imports AS SELECT
        i.id,i.batch_id,r.id AS revision_id,i.period,i.sheet_name,i.row_count,
        i.included_count,i.excluded_count,i.indeterminate_count,i.honorarios_ars,
        i.derechos_ars,i.total_ars,i.created_by,i.created_at,i.eligibility_version
        FROM invoice_imports i JOIN revisions r ON r.batch_id=i.batch_id
        WHERE r.ordinal=(SELECT MAX(x.ordinal) FROM revisions x WHERE x.batch_id=i.batch_id)''',
        '''CREATE TABLE revision_openings (
        revision_id TEXT PRIMARY KEY REFERENCES revisions(id),
        previous_revision_id TEXT NOT NULL UNIQUE REFERENCES revision_closures(revision_id),
        actor_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,
        reason TEXT NOT NULL CHECK(length(reason)>=10),basis_json TEXT NOT NULL)''',
        '''CREATE TABLE revision_input_owners (
        kind TEXT NOT NULL,record_id TEXT NOT NULL,revision_id TEXT NOT NULL REFERENCES revisions(id),
        PRIMARY KEY(kind,record_id))''',
        '''CREATE TABLE revision_work_fields (
        revision_id TEXT NOT NULL REFERENCES revisions(id),import_id TEXT NOT NULL,
        source_row INTEGER NOT NULL,field TEXT NOT NULL CHECK(field IN ('B','C','E','G','K')),
        value_json TEXT NOT NULL,latest_change_id TEXT NOT NULL REFERENCES work_changes(id),
        PRIMARY KEY(revision_id,import_id,source_row,field),
        FOREIGN KEY(import_id,source_row) REFERENCES invoice_rows(import_id,source_row))''',
        '''INSERT INTO revision_work_fields SELECT c.revision_id,w.* FROM work_fields w
        JOIN work_changes c ON c.id=w.latest_change_id''',
        'DROP TABLE work_fields',
        '''CREATE VIEW work_fields AS SELECT w.import_id,w.source_row,w.field,w.value_json,w.latest_change_id
        FROM revision_work_fields w JOIN current_invoice_imports i
        ON i.id=w.import_id AND i.revision_id=w.revision_id''',
    ]
    for table in SCOPED[1:]:
        statements += [
            f"INSERT INTO revision_input_owners SELECT '{table}',h.id,i.revision_id FROM {table} h JOIN invoice_imports i ON i.batch_id=h.batch_id",
            f'''CREATE TRIGGER {table}_revision_owner AFTER INSERT ON {table} BEGIN
            INSERT INTO revision_input_owners VALUES('{table}',NEW.id,
            (SELECT i.revision_id FROM current_invoice_imports i JOIN revisions r ON r.id=i.revision_id
            WHERE i.batch_id=NEW.batch_id AND r.state!='cerrada')); END''',
            f'''CREATE VIEW current_{table} AS SELECT h.* FROM {table} h
            JOIN revision_input_owners o ON o.kind='{table}' AND o.record_id=h.id
            JOIN current_invoice_imports i ON i.batch_id=h.batch_id AND i.revision_id=o.revision_id''',
        ]
    for table in ('revision_openings', 'revision_input_owners'):
        for action in ('UPDATE', 'DELETE'):
            statements.append(f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable revision provenance'); END")
    for table in SCOPED[1:]:
        for action in ('UPDATE', 'DELETE'):
            statements.append(f"CREATE TRIGGER {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Immutable revision input history'); END")
    for action in ('INSERT', 'UPDATE'):
        statements.append(f'''CREATE TRIGGER revision_work_fields_valid_{action.lower()} BEFORE {action} ON revision_work_fields
        WHEN NOT EXISTS(SELECT 1 FROM revisions r JOIN invoice_imports i ON i.batch_id=r.batch_id
        WHERE r.id=NEW.revision_id AND i.id=NEW.import_id AND r.state!='cerrada')
        BEGIN SELECT RAISE(ABORT,'Working input requires its open revision'); END''')
    for action in ('UPDATE', 'DELETE'):
        statements.append(f'''CREATE TRIGGER closed_work_fields_{action.lower()} BEFORE {action} ON revision_work_fields
        WHEN (SELECT state FROM revisions WHERE id=OLD.revision_id)='cerrada'
        BEGIN SELECT RAISE(ABORT,'Immutable closed working input'); END''')
    return tuple(statements)
