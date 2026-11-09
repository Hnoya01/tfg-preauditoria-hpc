"""Additive internal workflow schema; originals and historical closures are untouched."""

def migration_statements():
    sql = ['''CREATE TABLE observation_events (
        id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions(id),
        run_id TEXT NOT NULL REFERENCES control_runs(id), source_row INTEGER NOT NULL,
        rule_code TEXT NOT NULL, action TEXT NOT NULL CHECK(action IN
        ('refer','request_info','provide_info','resolve')),
        duty TEXT NOT NULL CHECK(duty IN ('administrative','auditor')),
        foundation TEXT NOT NULL CHECK(length(trim(foundation)) BETWEEN 10 AND 4000),
        evidence_note TEXT NOT NULL CHECK(length(trim(evidence_note)) BETWEEN 10 AND 4000),
        decision TEXT CHECK(decision IN ('confirmada','descartada')),
        decision_id TEXT REFERENCES review_decisions(id),
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
        request_id TEXT NOT NULL CHECK(length(request_id) BETWEEN 16 AND 100),
        request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
        CHECK((action='resolve' AND decision IS NOT NULL) OR (action!='resolve' AND decision IS NULL AND decision_id IS NULL)),
        UNIQUE(actor_id,request_id),
        FOREIGN KEY(run_id,source_row,rule_code) REFERENCES control_results(run_id,source_row,rule_code))''',
        '''CREATE INDEX observation_scope ON observation_events(revision_id,source_row,rule_code)''',
        '''CREATE TRIGGER observation_open BEFORE INSERT ON observation_events
        WHEN NOT EXISTS(SELECT 1 FROM revisions r JOIN control_runs c ON c.revision_id=r.id
        JOIN current_invoice_imports i ON i.revision_id=r.id
        WHERE r.id=NEW.revision_id AND c.id=NEW.run_id AND r.state!='cerrada')
        BEGIN SELECT RAISE(ABORT,'Observation requires current open revision'); END''']
    for action in ('UPDATE','DELETE'):
        sql.append(f"CREATE TRIGGER observation_immutable_{action.lower()} BEFORE {action} ON observation_events BEGIN SELECT RAISE(ABORT,'Immutable observation history'); END")
    return tuple(sql)

