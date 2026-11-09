"""SQLite connections and versioned schema."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4
from .hpc_value_status_schema import migration_statements as hpc_value_status_migrations
from .row_document_schema import migration_statements as row_document_migrations
from .agreement_declaration_schema import migration_statements as agreement_declaration_migrations
from .category_history_schema import migration as category_history_migration
from .local_hpc_schema import migration_statements as local_hpc_migrations
from .observation_schema import migration_statements as observation_migrations
from .revision_scope import migration_statements
from .medical_schema import migration_statements as consultation_migrations, historical_response_migrations


MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        """CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'reviewer', 'viewer')),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            csrf_token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_active_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )""",
        "CREATE INDEX sessions_user_idx ON sessions(user_id)",
        """CREATE TABLE login_failures (
            id TEXT PRIMARY KEY,
            username_key TEXT NOT NULL,
            origin_key TEXT NOT NULL,
            failed_at TEXT NOT NULL
        )""",
        "CREATE INDEX login_failures_user_idx ON login_failures(username_key, failed_at)",
        "CREATE INDEX login_failures_origin_idx ON login_failures(origin_key, failed_at)",
        """CREATE TABLE datasets (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE dataset_access (
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            user_id TEXT NOT NULL REFERENCES users(id),
            role TEXT NOT NULL CHECK (role IN ('admin', 'reviewer', 'viewer')),
            PRIMARY KEY (dataset_id, user_id)
        )""",
        """CREATE TABLE stored_files (
            sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
            byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
            relative_path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE batches (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_sha256 TEXT NOT NULL REFERENCES stored_files(sha256),
            original_name TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'staged' CHECK (state = 'staged'),
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (dataset_id, source_sha256)
        )""",
        "CREATE INDEX batches_dataset_idx ON batches(dataset_id)",
        """CREATE TABLE revisions (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(id),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            state TEXT NOT NULL CHECK (state IN ('preparacion', 'revision', 'cerrada')),
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            created_at TEXT NOT NULL,
            UNIQUE (batch_id, ordinal)
        )""",
        "CREATE UNIQUE INDEX one_open_revision_per_batch ON revisions(batch_id) WHERE state != 'cerrada'",
        """CREATE TABLE audit_events (
            id TEXT PRIMARY KEY,
            actor_id TEXT REFERENCES users(id),
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        )""",
    )),
    (2, (
        """CREATE TABLE invoice_imports (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL UNIQUE REFERENCES batches(id),
            revision_id TEXT NOT NULL UNIQUE REFERENCES revisions(id),
            period TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            included_count INTEGER NOT NULL,
            excluded_count INTEGER NOT NULL,
            indeterminate_count INTEGER NOT NULL,
            honorarios_ars TEXT NOT NULL,
            derechos_ars TEXT NOT NULL,
            total_ars TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE invoice_rows (
            import_id TEXT NOT NULL REFERENCES invoice_imports(id),
            source_row INTEGER NOT NULL,
            disposition TEXT NOT NULL CHECK (disposition IN ('included', 'excluded', 'indeterminate')),
            disposition_reason TEXT,
            practice_date TEXT,
            permitted_json TEXT NOT NULL,
            honorarios_ars TEXT NOT NULL,
            derechos_ars TEXT NOT NULL,
            total_ars TEXT NOT NULL,
            amount_check TEXT NOT NULL CHECK (amount_check IN ('consistent', 'difference_within_tolerance')),
            PRIMARY KEY (import_id, source_row)
        )""",
        "CREATE INDEX invoice_rows_disposition_idx ON invoice_rows(import_id, disposition)",
    )),
    (3, (
        """CREATE TABLE source_registry (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            kind TEXT NOT NULL CHECK (kind IN ('authorizations', 'values')),
            status TEXT NOT NULL CHECK (status IN ('pending', 'registered')),
            source_sha256 TEXT REFERENCES stored_files(sha256),
            manifest_sha256 TEXT REFERENCES stored_files(sha256),
            format_label TEXT,
            cut_label TEXT,
            source_version TEXT,
            captured_at TEXT,
            coverage_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            CHECK ((status = 'pending' AND source_sha256 IS NULL AND manifest_sha256 IS NULL) OR
                   (status = 'registered' AND source_sha256 IS NOT NULL AND manifest_sha256 IS NOT NULL)),
            UNIQUE (dataset_id, kind, source_sha256)
        )""",
        "CREATE UNIQUE INDEX source_one_pending_kind ON source_registry(dataset_id, kind) WHERE status = 'pending'",
        "CREATE INDEX source_dataset_idx ON source_registry(dataset_id, kind, created_at)",
    )),
    (4, (
        """CREATE TABLE control_runs (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            import_id TEXT NOT NULL REFERENCES invoice_imports(id),
            snapshot_sha256 TEXT NOT NULL CHECK (length(snapshot_sha256) = 64),
            snapshot_json TEXT NOT NULL,
            technical_state TEXT NOT NULL CHECK (technical_state = 'completed'),
            freshness TEXT NOT NULL CHECK (freshness IN ('current', 'requires_update')),
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (revision_id, snapshot_sha256)
        )""",
        "CREATE INDEX control_runs_revision_idx ON control_runs(revision_id, created_at)",
        """CREATE TABLE control_results (
            run_id TEXT NOT NULL REFERENCES control_runs(id),
            import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            rule_code TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            result TEXT NOT NULL CHECK (result IN ('no_evaluado', 'no_aplicable',
                'sin_observaciones', 'con_indicios', 'no_concluyente')),
            reason_code TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            difference_ars TEXT,
            currency TEXT,
            PRIMARY KEY (run_id, source_row, rule_code),
            FOREIGN KEY (import_id, source_row) REFERENCES invoice_rows(import_id, source_row),
            CHECK ((difference_ars IS NULL AND currency IS NULL) OR
                   (difference_ars IS NOT NULL AND currency = 'ARS'))
        )""",
        "CREATE INDEX control_results_rule_idx ON control_results(run_id, rule_code, result)",
    )),
    (5, (
        """CREATE TABLE work_changes (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            field TEXT NOT NULL CHECK (field IN ('B', 'C', 'E', 'G', 'K')),
            previous_json TEXT NOT NULL,
            new_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            FOREIGN KEY (import_id, source_row) REFERENCES invoice_rows(import_id, source_row)
        )""",
        "CREATE INDEX work_changes_row_idx ON work_changes(import_id, source_row, created_at)",
        """CREATE TABLE work_fields (
            import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            field TEXT NOT NULL CHECK (field IN ('B', 'C', 'E', 'G', 'K')),
            value_json TEXT NOT NULL,
            latest_change_id TEXT NOT NULL REFERENCES work_changes(id),
            PRIMARY KEY (import_id, source_row, field),
            FOREIGN KEY (import_id, source_row) REFERENCES invoice_rows(import_id, source_row)
        )""",
        """CREATE TABLE alerts (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            rule_code TEXT NOT NULL,
            first_run_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            created_at TEXT NOT NULL,
            UNIQUE (revision_id, source_row, rule_code),
            FOREIGN KEY (first_run_id, source_row, rule_code)
                REFERENCES control_results(run_id, source_row, rule_code),
            FOREIGN KEY (import_id, source_row) REFERENCES invoice_rows(import_id, source_row)
        )""",
        "CREATE INDEX alerts_revision_idx ON alerts(revision_id, source_row, rule_code)",
        """CREATE TABLE review_decisions (
            id TEXT PRIMARY KEY,
            alert_id TEXT NOT NULL REFERENCES alerts(id),
            run_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            rule_code TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('confirmada', 'descartada', 'no_concluyente')),
            foundation TEXT NOT NULL,
            evidence_note TEXT,
            previous_id TEXT REFERENCES review_decisions(id),
            group_id TEXT,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id, source_row, rule_code)
                REFERENCES control_results(run_id, source_row, rule_code)
        )""",
        "CREATE INDEX review_decisions_alert_idx ON review_decisions(alert_id, created_at, id)",
        """CREATE TABLE decision_reuses (
            id TEXT PRIMARY KEY,
            alert_id TEXT NOT NULL REFERENCES alerts(id),
            decision_id TEXT NOT NULL REFERENCES review_decisions(id),
            run_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            rule_code TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (alert_id, run_id),
            FOREIGN KEY (run_id, source_row, rule_code)
                REFERENCES control_results(run_id, source_row, rule_code)
        )""",
    )),
    (6, (
        """CREATE TABLE batch_provider_scopes (
            batch_id TEXT PRIMARY KEY REFERENCES batches(id),
            provider TEXT NOT NULL,
            billing_unit TEXT NOT NULL,
            confirmation_note TEXT NOT NULL,
            confirmed_by TEXT NOT NULL REFERENCES users(id),
            confirmed_at TEXT NOT NULL
        )""",
        """CREATE TABLE economic_verifications (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            source_sha256 TEXT NOT NULL REFERENCES stored_files(sha256),
            evidence_sha256 TEXT NOT NULL REFERENCES stored_files(sha256),
            evidence_locator TEXT NOT NULL,
            tariff_locator TEXT NOT NULL,
            provider TEXT NOT NULL,
            code_complete TEXT NOT NULL,
            currency TEXT NOT NULL,
            economic_unit TEXT NOT NULL,
            rate_ars TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            verified_through TEXT NOT NULL,
            applicability_note TEXT NOT NULL,
            verified_by TEXT NOT NULL REFERENCES users(id),
            verified_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
        )""",
        "CREATE INDEX economic_verifications_source_idx ON economic_verifications(dataset_id, source_id, code_complete)",
        """CREATE TABLE proposal_versions (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            previous_id TEXT REFERENCES proposal_versions(id),
            run_id TEXT NOT NULL REFERENCES control_runs(id),
            provider_scope_at_save TEXT NOT NULL,
            work_basis_json TEXT NOT NULL,
            amount_ars TEXT NOT NULL,
            currency TEXT NOT NULL CHECK (currency = 'ARS'),
            payload_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            FOREIGN KEY (import_id, source_row) REFERENCES invoice_rows(import_id, source_row),
            UNIQUE (import_id, source_row, ordinal)
        )""",
        "CREATE INDEX proposal_versions_row_idx ON proposal_versions(import_id, source_row, ordinal)",
    )),
    (7, (
        """CREATE TABLE evidence_documents (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            sha256 TEXT NOT NULL REFERENCES stored_files(sha256),
            original_name TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('agreement', 'nomenclator')),
            source_match TEXT NOT NULL CHECK (source_match IN ('catalog_hash_match', 'no_catalog_hash')),
            provenance_note TEXT NOT NULL,
            registered_by TEXT NOT NULL REFERENCES users(id),
            registered_at TEXT NOT NULL,
            UNIQUE (dataset_id, sha256)
        )""",
        "CREATE INDEX evidence_documents_source_idx ON evidence_documents(dataset_id, source_id)",
        """CREATE TABLE batch_provider_scope_history (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(id),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            previous_id TEXT REFERENCES batch_provider_scope_history(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            provider TEXT NOT NULL,
            billing_unit TEXT NOT NULL,
            confirmation_note TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (batch_id, ordinal)
        )""",
        "CREATE INDEX batch_provider_scope_history_batch_idx ON batch_provider_scope_history(batch_id, ordinal)",
    )),
    (8, (
        "ALTER TABLE invoice_imports ADD COLUMN eligibility_version TEXT NOT NULL DEFAULT 'period-only-v0'",
    )),
    (9, (
        """CREATE TABLE invoice_rows_rebuilt (
            import_id TEXT NOT NULL REFERENCES invoice_imports(id),
            source_row INTEGER NOT NULL,
            disposition TEXT NOT NULL CHECK (disposition IN ('included', 'excluded', 'indeterminate')),
            disposition_reason TEXT,
            practice_date TEXT,
            permitted_json TEXT NOT NULL,
            honorarios_ars TEXT NOT NULL,
            derechos_ars TEXT NOT NULL,
            total_ars TEXT NOT NULL,
            amount_check TEXT NOT NULL CHECK (amount_check IN ('consistent', 'difference_within_tolerance',
                                                              'difference_exceeds_tolerance')),
            PRIMARY KEY (import_id, source_row)
        )""",
        "INSERT INTO invoice_rows_rebuilt SELECT * FROM invoice_rows",
        "DROP TABLE invoice_rows",
        "ALTER TABLE invoice_rows_rebuilt RENAME TO invoice_rows",
        "CREATE INDEX invoice_rows_disposition_idx ON invoice_rows(import_id, disposition)",
    )),
    (10, (
        """CREATE TABLE economic_verification_withdrawals (
            id TEXT PRIMARY KEY,
            verification_id TEXT NOT NULL UNIQUE REFERENCES economic_verifications(id),
            reason TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        )""",
    )),
    (11, (
        """CREATE TABLE documentary_assessments (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            provider TEXT NOT NULL,
            code_complete TEXT NOT NULL,
            tariff_seq INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            previous_id TEXT REFERENCES documentary_assessments(id),
            document_id TEXT NOT NULL REFERENCES evidence_documents(id),
            edition TEXT NOT NULL,
            page_number INTEGER NOT NULL CHECK (page_number >= 1),
            fragment TEXT NOT NULL,
            observed_factor TEXT,
            factor_unit TEXT NOT NULL CHECK (factor_unit = 'UB'),
            conclusion TEXT NOT NULL CHECK (conclusion IN ('matches', 'differs', 'inconclusive')),
            note TEXT NOT NULL,
            basis_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (source_id, provider, code_complete, tariff_seq, ordinal)
        )""",
    )),
    (12, (
        """CREATE TABLE agreement_document_reviews (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            ordinal INTEGER NOT NULL,
            report_sha256 TEXT NOT NULL REFERENCES stored_files(sha256),
            basis_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (source_id, ordinal)
        )""",
    )),
    (13, (
        """CREATE TABLE authorization_uploads (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_sha256 TEXT NOT NULL REFERENCES stored_files(sha256),
            original_name TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (dataset_id, source_sha256)
        )""",
        """CREATE TABLE authorization_captures (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            upload_id TEXT NOT NULL UNIQUE REFERENCES authorization_uploads(id),
            source_registry_id TEXT NOT NULL UNIQUE REFERENCES source_registry(id),
            source_system TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            previous_id TEXT REFERENCES authorization_captures(id),
            data_origin TEXT NOT NULL CHECK (data_origin IN ('synthetic', 'real_unvalidated')),
            canonical_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            observations_json TEXT NOT NULL,
            preview_sha256 TEXT NOT NULL,
            provenance_note TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (dataset_id, source_system, stream_id, ordinal)
        )""",
        "CREATE INDEX authorization_capture_stream ON authorization_captures(dataset_id, source_system, stream_id, ordinal)",
    )),
    (14, (
        """CREATE TABLE hpc_value_versions (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            tariff_seq INTEGER NOT NULL,
            code TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            previous_id TEXT REFERENCES hpc_value_versions(id),
            amount_ars TEXT NOT NULL,
            unit_label TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            document_id TEXT NOT NULL REFERENCES evidence_documents(id),
            document_sha256 TEXT NOT NULL,
            page_number INTEGER NOT NULL CHECK (page_number >= 1),
            excerpt TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (dataset_id, source_id, tariff_seq, ordinal)
        )""",
        "CREATE INDEX hpc_value_versions_lookup ON hpc_value_versions(dataset_id, source_id, tariff_seq, effective_from, ordinal)",
    )),
    (15, (
        """CREATE TABLE authorization_match_scopes (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            batch_id TEXT NOT NULL REFERENCES batches(id), ordinal INTEGER NOT NULL,
            previous_id TEXT REFERENCES authorization_match_scopes(id),
            capture_ids_json TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('synthetic_demo','real_unvalidated')),
            note TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            UNIQUE(batch_id, ordinal)
        )""",
        """CREATE TABLE authorization_link_versions (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            batch_id TEXT NOT NULL REFERENCES batches(id), import_id TEXT NOT NULL REFERENCES invoice_imports(id),
            source_row INTEGER NOT NULL, ordinal INTEGER NOT NULL,
            previous_id TEXT REFERENCES authorization_link_versions(id),
            state TEXT NOT NULL CHECK(state IN ('selected','unresolved')),
            candidate_key TEXT, basis_sha256 TEXT NOT NULL, evidence_json TEXT NOT NULL,
            note TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            UNIQUE(import_id, source_row, ordinal)
        )""",
        'CREATE INDEX authorization_links_lookup ON authorization_link_versions(import_id, source_row, ordinal)',
    )),
    (16, (
        'CREATE INDEX practice_board_controls ON control_results(run_id, source_row, rule_code, result, reason_code)',
    )),
    (17, (
        """CREATE TABLE processing_attempts (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            batch_id TEXT NOT NULL REFERENCES batches(id), actor_id TEXT NOT NULL REFERENCES users(id),
            session_hash TEXT NOT NULL, request_key TEXT NOT NULL,
            previous_id TEXT UNIQUE REFERENCES processing_attempts(id),
            expected_dataset_version INTEGER NOT NULL, expected_revision_version INTEGER NOT NULL,
            input_sha256 TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','interrupted','blocked')),
            stage TEXT NOT NULL, processed_rows INTEGER NOT NULL DEFAULT 0 CHECK(processed_rows>=0),
            total_rows INTEGER CHECK(total_rows>=0),
            created_at TEXT NOT NULL, started_at TEXT, heartbeat_at TEXT, finished_at TEXT,
            owner_id TEXT, lease_until REAL, version INTEGER NOT NULL DEFAULT 1,
            result_run_id TEXT REFERENCES control_runs(id), result_created INTEGER CHECK(result_created IN (0,1)),
            error_code TEXT, error_type TEXT, UNIQUE(dataset_id, request_key)
        )""",
        "CREATE UNIQUE INDEX processing_one_active ON processing_attempts(batch_id) WHERE state IN ('queued','running')",
        'CREATE INDEX processing_batch_history ON processing_attempts(batch_id, created_at)',
    )),
    (18, (
        """CREATE TABLE authorization_input_versions (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            batch_id TEXT NOT NULL REFERENCES batches(id), import_id TEXT NOT NULL REFERENCES invoice_imports(id),
            source_row INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('incorporation','quantity_unit')),
            ordinal INTEGER NOT NULL, previous_id TEXT REFERENCES authorization_input_versions(id),
            state TEXT NOT NULL CHECK(state IN ('declared','withdrawn')),
            value TEXT, provenance TEXT NOT NULL, locator TEXT NOT NULL,
            data_origin TEXT NOT NULL CHECK(data_origin IN ('synthetic','real_unvalidated')),
            record_sha256 TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            UNIQUE(import_id, source_row, kind, ordinal)
        )""",
        'CREATE INDEX authorization_inputs_lookup ON authorization_input_versions(import_id, source_row, kind, ordinal)',
    )),
    (19, (
        """CREATE TABLE analysis_history (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            import_id TEXT NOT NULL REFERENCES invoice_imports(id),
            snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256)=64), snapshot_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('captured','prepared','published','historical')),
            reason_code TEXT, published_run_id TEXT REFERENCES control_runs(id)
        )""",
        """CREATE TABLE analysis_history_results (
            run_id TEXT NOT NULL REFERENCES analysis_history(id), import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL, rule_code TEXT NOT NULL, rule_version TEXT NOT NULL,
            result TEXT NOT NULL, reason_code TEXT NOT NULL, evidence_json TEXT NOT NULL,
            difference_ars TEXT, currency TEXT, PRIMARY KEY(run_id,source_row,rule_code)
        )""",
        'CREATE INDEX analysis_history_revision ON analysis_history(dataset_id,revision_id,created_at)',
    )),
    (20, (
        """CREATE TABLE review_limitations (
            id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions(id),
            group_key TEXT NOT NULL, scope_sha256 TEXT NOT NULL, rule_codes_json TEXT NOT NULL,
            reason_code TEXT NOT NULL, foundation TEXT NOT NULL CHECK(length(foundation)>=10),
            ordinal INTEGER NOT NULL, previous_id TEXT REFERENCES review_limitations(id),
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            UNIQUE(revision_id,group_key,ordinal)
        )""",
        """CREATE TABLE limitation_controls (
            limitation_id TEXT NOT NULL REFERENCES review_limitations(id),
            import_id TEXT NOT NULL, source_row INTEGER NOT NULL, rule_code TEXT NOT NULL,
            evaluation_json TEXT NOT NULL, PRIMARY KEY(limitation_id,source_row,rule_code),
            FOREIGN KEY(import_id,source_row) REFERENCES invoice_rows(import_id,source_row)
        )""",
        """CREATE TABLE revision_closures (
            id TEXT PRIMARY KEY, revision_id TEXT NOT NULL UNIQUE REFERENCES revisions(id),
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            archive_sha256 TEXT NOT NULL REFERENCES stored_files(sha256), manifest_sha256 TEXT NOT NULL,
            manifest_json TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
        )""",
        "CREATE TRIGGER closure_immutable_update BEFORE UPDATE ON revision_closures BEGIN SELECT RAISE(ABORT,'Immutable closure'); END",
        "CREATE TRIGGER closure_immutable_delete BEFORE DELETE ON revision_closures BEGIN SELECT RAISE(ABORT,'Immutable closure'); END",
        "CREATE TRIGGER limitation_immutable_update BEFORE UPDATE ON review_limitations BEGIN SELECT RAISE(ABORT,'Immutable limitation history'); END",
        "CREATE TRIGGER limitation_immutable_delete BEFORE DELETE ON review_limitations BEGIN SELECT RAISE(ABORT,'Immutable limitation history'); END",
        "CREATE TRIGGER limitation_scope_immutable_update BEFORE UPDATE ON limitation_controls BEGIN SELECT RAISE(ABORT,'Immutable limitation scope'); END",
        "CREATE TRIGGER limitation_scope_immutable_delete BEFORE DELETE ON limitation_controls BEGIN SELECT RAISE(ABORT,'Immutable limitation scope'); END",
        "CREATE TRIGGER closed_revision_no_reopen BEFORE UPDATE OF state ON revisions WHEN OLD.state='cerrada' AND NEW.state!='cerrada' BEGIN SELECT RAISE(ABORT,'Closed revision cannot be reopened'); END",
    )),

    (21, migration_statements()),
    (22, (
        """CREATE TABLE closure_input_captures (
            sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64),payload_json TEXT NOT NULL)""",
        """CREATE TABLE limitation_formats (
            limitation_id TEXT PRIMARY KEY REFERENCES review_limitations(id),
            format_version TEXT NOT NULL,input_capture_sha256 TEXT NOT NULL REFERENCES closure_input_captures(sha256))""",
        "CREATE TRIGGER capture_immutable_update BEFORE UPDATE ON closure_input_captures BEGIN SELECT RAISE(ABORT,'Immutable closure inputs'); END",
        "CREATE TRIGGER capture_immutable_delete BEFORE DELETE ON closure_input_captures BEGIN SELECT RAISE(ABORT,'Immutable closure inputs'); END",
        "CREATE TRIGGER limitation_format_immutable_update BEFORE UPDATE ON limitation_formats BEGIN SELECT RAISE(ABORT,'Immutable limitation format'); END",
        "CREATE TRIGGER limitation_format_immutable_delete BEFORE DELETE ON limitation_formats BEGIN SELECT RAISE(ABORT,'Immutable limitation format'); END",
    )),
    (23, (
        """CREATE TABLE row_economic_references (
            id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            revision_id TEXT NOT NULL REFERENCES revisions(id), import_id TEXT NOT NULL,
            source_row INTEGER NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>0),
            previous_id TEXT REFERENCES row_economic_references(id),
            state TEXT NOT NULL CHECK(state IN ('confirmed','withdrawn','unresolved')),
            source_id TEXT NOT NULL REFERENCES source_registry(id),
            confirmation_json TEXT NOT NULL, basis_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            UNIQUE(revision_id,source_row,ordinal),
            FOREIGN KEY(import_id,source_row) REFERENCES invoice_rows(import_id,source_row))""",
        """CREATE TRIGGER row_economic_reference_open BEFORE INSERT ON row_economic_references
            WHEN NOT EXISTS(SELECT 1 FROM revisions r JOIN invoice_imports i ON i.batch_id=r.batch_id
            JOIN batches b ON b.id=r.batch_id JOIN source_registry s ON s.dataset_id=b.dataset_id
            WHERE r.id=NEW.revision_id AND r.state!='cerrada' AND i.id=NEW.import_id
            AND b.dataset_id=NEW.dataset_id AND s.id=NEW.source_id)
            BEGIN SELECT RAISE(ABORT,'Reference requires its own open revision and source'); END""",
        "CREATE TRIGGER row_economic_reference_immutable_update BEFORE UPDATE ON row_economic_references BEGIN SELECT RAISE(ABORT,'Immutable applicability history'); END",
        "CREATE TRIGGER row_economic_reference_immutable_delete BEFORE DELETE ON row_economic_references BEGIN SELECT RAISE(ABORT,'Immutable applicability history'); END",
    )),
    (24, (
        """CREATE TABLE rn14_simulation_versions (
            id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions(id),
            import_id TEXT NOT NULL, source_row INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal>0),
            previous_id TEXT REFERENCES rn14_simulation_versions(id),
            run_id TEXT NOT NULL REFERENCES control_runs(id), provider_scope_at_save TEXT NOT NULL,
            work_basis_json TEXT NOT NULL, amount_ars TEXT NOT NULL,
            currency TEXT NOT NULL CHECK(currency='ARS'),
            payload_json TEXT NOT NULL CHECK(json_valid(payload_json) AND json_type(payload_json,'$.simulation_only')='true'),
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            FOREIGN KEY(import_id,source_row) REFERENCES invoice_rows(import_id,source_row),
            UNIQUE(import_id,source_row,ordinal))""",
        """CREATE TABLE rn14_proposal_references (
            id TEXT PRIMARY KEY,
            proposal_id TEXT UNIQUE REFERENCES proposal_versions(id),
            simulation_id TEXT UNIQUE REFERENCES rn14_simulation_versions(id),
            decision_id TEXT NOT NULL REFERENCES review_decisions(id),
            applicability_id TEXT NOT NULL REFERENCES row_economic_references(id),
            CHECK((proposal_id IS NULL)!=(simulation_id IS NULL)),
            CHECK(id=coalesce(proposal_id,simulation_id)))""",
        "CREATE TRIGGER rn14_reference_immutable_update BEFORE UPDATE ON rn14_proposal_references BEGIN SELECT RAISE(ABORT,'Immutable amount provenance'); END",
        "CREATE TRIGGER rn14_reference_immutable_delete BEFORE DELETE ON rn14_proposal_references BEGIN SELECT RAISE(ABORT,'Immutable amount provenance'); END",
        """CREATE TRIGGER rn14_simulation_open BEFORE INSERT ON rn14_simulation_versions
            WHEN NOT EXISTS(SELECT 1 FROM revisions r JOIN invoice_imports i ON i.batch_id=r.batch_id
            WHERE r.id=NEW.revision_id AND i.id=NEW.import_id AND r.state!='cerrada'
            AND EXISTS(SELECT 1 FROM authorization_match_scopes s WHERE s.batch_id=r.batch_id AND s.mode='synthetic_demo'))
            BEGIN SELECT RAISE(ABORT,'Simulation requires its open, declared fictional revision'); END""",
        "CREATE TRIGGER rn14_simulation_immutable_update BEFORE UPDATE ON rn14_simulation_versions BEGIN SELECT RAISE(ABORT,'Immutable simulation history'); END",
        "CREATE TRIGGER rn14_simulation_immutable_delete BEFORE DELETE ON rn14_simulation_versions BEGIN SELECT RAISE(ABORT,'Immutable simulation history'); END",
        """CREATE TRIGGER proposal_not_simulation BEFORE INSERT ON proposal_versions
            WHEN CASE WHEN json_valid(NEW.payload_json) THEN json_extract(NEW.payload_json,'$.simulation_only')=1 ELSE 0 END
            BEGIN SELECT RAISE(ABORT,'Simulation cannot be stored as a real proposal'); END""",
        """CREATE TRIGGER rn14_real_proposal_open BEFORE INSERT ON proposal_versions
            WHEN CASE WHEN json_valid(NEW.payload_json) THEN json_extract(NEW.payload_json,'$.format_version')=3 ELSE 0 END
            AND NOT EXISTS(SELECT 1 FROM revisions r JOIN invoice_imports i ON i.batch_id=r.batch_id
            WHERE r.id=NEW.revision_id AND i.id=NEW.import_id AND r.state!='cerrada'
            AND NOT EXISTS(SELECT 1 FROM authorization_match_scopes s WHERE s.batch_id=r.batch_id AND s.mode='synthetic_demo'))
            BEGIN SELECT RAISE(ABORT,'RN14 real proposal requires its open, non-fictional revision'); END""",
        """CREATE TRIGGER rn14_proposal_immutable_update BEFORE UPDATE ON proposal_versions
            WHEN CASE WHEN json_valid(OLD.payload_json) THEN json_extract(OLD.payload_json,'$.format_version')=3 ELSE 0 END
            BEGIN SELECT RAISE(ABORT,'Immutable RN14 proposal history'); END""",
        """CREATE TRIGGER rn14_proposal_immutable_delete BEFORE DELETE ON proposal_versions
            WHEN CASE WHEN json_valid(OLD.payload_json) THEN json_extract(OLD.payload_json,'$.format_version')=3 ELSE 0 END
            BEGIN SELECT RAISE(ABORT,'Immutable RN14 proposal history'); END""",
    )),
    (25, consultation_migrations()),
    (26, historical_response_migrations()),
    (27, observation_migrations()),
    (28, row_document_migrations() + hpc_value_status_migrations()),
    (29, local_hpc_migrations()),
    (30, agreement_declaration_migrations()),
    (31, (
        """CREATE TABLE source_registry_new (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            kind TEXT NOT NULL CHECK (kind IN ('authorizations', 'values')),
            status TEXT NOT NULL CHECK (status IN ('pending', 'registered')),
            source_sha256 TEXT REFERENCES stored_files(sha256),
            manifest_sha256 TEXT REFERENCES stored_files(sha256),
            format_label TEXT,
            cut_label TEXT,
            source_version TEXT,
            captured_at TEXT,
            coverage_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            CHECK ((status = 'pending' AND source_sha256 IS NULL AND manifest_sha256 IS NULL) OR
                   (status = 'registered' AND source_sha256 IS NOT NULL AND manifest_sha256 IS NOT NULL)),
            UNIQUE (dataset_id, kind, source_sha256, manifest_sha256)
        )""",
        "INSERT INTO source_registry_new SELECT * FROM source_registry",
        "DROP TABLE source_registry",
        "ALTER TABLE source_registry_new RENAME TO source_registry",
        "CREATE UNIQUE INDEX source_one_pending_kind ON source_registry(dataset_id, kind) WHERE status = 'pending'",
        "CREATE UNIQUE INDEX source_values_identity ON source_registry(dataset_id, kind, source_sha256) WHERE kind = 'values'",
        "CREATE INDEX source_dataset_idx ON source_registry(dataset_id, kind, created_at)",
        """CREATE TABLE authorization_captures_new (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES datasets(id),
            upload_id TEXT NOT NULL REFERENCES authorization_uploads(id),
            source_registry_id TEXT NOT NULL UNIQUE REFERENCES source_registry(id),
            source_system TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
            previous_id TEXT REFERENCES authorization_captures(id),
            data_origin TEXT NOT NULL CHECK (data_origin IN ('synthetic', 'real_unvalidated')),
            canonical_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            observations_json TEXT NOT NULL,
            preview_sha256 TEXT NOT NULL,
            provenance_note TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (dataset_id, source_system, stream_id, ordinal)
        )""",
        "INSERT INTO authorization_captures_new SELECT * FROM authorization_captures",
        "DROP TABLE authorization_captures",
        "ALTER TABLE authorization_captures_new RENAME TO authorization_captures",
        "CREATE INDEX authorization_capture_stream ON authorization_captures(dataset_id, source_system, stream_id, ordinal)",
        "CREATE UNIQUE INDEX authorization_capture_interpretation ON authorization_captures(upload_id, preview_sha256)",
    )),
    (32, (
        """CREATE TABLE hpc_display_categories (
            dataset_id TEXT NOT NULL REFERENCES datasets(id), code TEXT NOT NULL,
            family TEXT NOT NULL CHECK(family IN ('images','other')),
            description TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(id),
            revision_id TEXT NOT NULL REFERENCES revisions(id), invoice_row INTEGER NOT NULL,
            source_sha256 TEXT NOT NULL REFERENCES stored_files(sha256), source_file TEXT NOT NULL,
            sheet TEXT NOT NULL, source_row INTEGER NOT NULL, source_column INTEGER NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, dataset_version INTEGER NOT NULL,
            PRIMARY KEY(dataset_id,code))""",
        "CREATE TRIGGER hpc_category_no_update BEFORE UPDATE ON hpc_display_categories BEGIN SELECT RAISE(ABORT,'Immutable category'); END",
        "CREATE TRIGGER hpc_category_no_delete BEFORE DELETE ON hpc_display_categories BEGIN SELECT RAISE(ABORT,'Immutable category'); END",
    )),
    (33, category_history_migration()),
    (34, (
        """CREATE TABLE csv_coverage_reviews (
            id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions(id),
            source_row INTEGER NOT NULL, evidence_sha256 TEXT NOT NULL,
            evidence_json TEXT NOT NULL, note TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL, request_id TEXT NOT NULL,
            UNIQUE(revision_id,source_row,evidence_sha256), UNIQUE(actor_id,request_id))""",
        "CREATE TRIGGER csv_review_no_update BEFORE UPDATE ON csv_coverage_reviews BEGIN SELECT RAISE(ABORT,'Immutable CSV review'); END",
        "CREATE TRIGGER csv_review_no_delete BEFORE DELETE ON csv_coverage_reviews BEGIN SELECT RAISE(ABORT,'Immutable CSV review'); END",
    )),
    (35, (
        """CREATE TABLE invoice_review_duties (
            dataset_id TEXT NOT NULL, user_id TEXT NOT NULL, duty TEXT NOT NULL CHECK(duty IN ('administrative','auditor')),
            PRIMARY KEY(dataset_id,user_id), FOREIGN KEY(dataset_id,user_id) REFERENCES dataset_access(dataset_id,user_id))""",
        """CREATE TABLE invoice_row_decisions (
            revision_id TEXT NOT NULL REFERENCES revisions(id), source_row INTEGER NOT NULL,
            ordinal INTEGER NOT NULL, action TEXT NOT NULL CHECK(action IN ('accept','partial','total','none')),
            amount_ars TEXT NOT NULL, reason TEXT NOT NULL, correction_note TEXT,
            reference TEXT, evidence_hash TEXT NOT NULL, basis_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
            request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
            PRIMARY KEY(revision_id,source_row,ordinal), UNIQUE(actor_id,request_id))""",
        "CREATE TRIGGER row_decision_no_update BEFORE UPDATE ON invoice_row_decisions BEGIN SELECT RAISE(ABORT,'Immutable decision'); END",
        "CREATE TRIGGER row_decision_no_delete BEFORE DELETE ON invoice_row_decisions BEGIN SELECT RAISE(ABORT,'Immutable decision'); END",
    )),
    (36, (
        """CREATE TABLE invoice_handoffs (
            revision_id TEXT PRIMARY KEY REFERENCES revisions(id),actor_id TEXT NOT NULL REFERENCES users(id),
            sent_at TEXT NOT NULL,request_id TEXT NOT NULL,receipt_count INTEGER NOT NULL,
            debit_total_ars TEXT NOT NULL, UNIQUE(actor_id,request_id))""",
        """CREATE TABLE invoice_handoff_rows (
            revision_id TEXT NOT NULL REFERENCES invoice_handoffs(revision_id),source_row INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,practice_date TEXT,order_number TEXT,code TEXT,description TEXT,billed_ars TEXT,
            PRIMARY KEY(revision_id,source_row),
            FOREIGN KEY(revision_id,source_row,ordinal) REFERENCES invoice_row_decisions(revision_id,source_row,ordinal))""",
        "CREATE TRIGGER handoff_immutable BEFORE UPDATE ON invoice_handoffs BEGIN SELECT RAISE(ABORT,'Immutable handoff'); END",
        "CREATE TRIGGER handoff_no_delete BEFORE DELETE ON invoice_handoffs BEGIN SELECT RAISE(ABORT,'Immutable handoff'); END",
        "CREATE TRIGGER handoff_rows_immutable BEFORE UPDATE ON invoice_handoff_rows BEGIN SELECT RAISE(ABORT,'Immutable handoff'); END",
        "CREATE TRIGGER handoff_rows_no_delete BEFORE DELETE ON invoice_handoff_rows BEGIN SELECT RAISE(ABORT,'Immutable handoff'); END",
        """CREATE TRIGGER handoff_revision_lock BEFORE UPDATE ON revisions
           WHEN EXISTS (SELECT 1 FROM invoice_handoffs WHERE revision_id=OLD.id)
           BEGIN SELECT RAISE(ABORT,'invoice_already_handed_off'); END""",
    ) + tuple(
        f"CREATE TRIGGER handoff_lock_{table} BEFORE INSERT ON {table} "
        "WHEN EXISTS (SELECT 1 FROM invoice_handoffs h WHERE h.revision_id=NEW.revision_id) "
        "BEGIN SELECT RAISE(ABORT,'invoice_already_handed_off'); END"
        for table in ('invoice_row_decisions','observation_events','hpc_display_categories','hpc_category_corrections')
    ) + tuple(
        f"CREATE TRIGGER handoff_lock_{table} BEFORE INSERT ON {table} "
        "WHEN EXISTS (SELECT 1 FROM revisions r JOIN invoice_handoffs h ON h.revision_id=r.id "
        "WHERE r.batch_id=NEW.batch_id AND r.ordinal=(SELECT max(ordinal) FROM revisions WHERE batch_id=NEW.batch_id)) "
        "BEGIN SELECT RAISE(ABORT,'invoice_already_handed_off'); END"
        for table in ('authorization_match_scopes','processing_attempts','practice_requests')
    )),
    (37, (
        """CREATE TABLE audit_invoice_scope (
            revision_id TEXT PRIMARY KEY REFERENCES invoice_handoffs(revision_id),
            invoice_ars TEXT NOT NULL, images_ars TEXT NOT NULL, image_count INTEGER NOT NULL,
            scope_hash TEXT NOT NULL)""",
        """CREATE TABLE audit_adjustments (
            revision_id TEXT NOT NULL, source_row INTEGER NOT NULL, seq INTEGER NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), adjusted_at TEXT NOT NULL,
            amount_ars TEXT NOT NULL, reason TEXT NOT NULL,
            PRIMARY KEY(revision_id,source_row,seq),
            FOREIGN KEY(revision_id,source_row) REFERENCES invoice_handoff_rows(revision_id,source_row))""",
        """CREATE TABLE audit_invoice_closures (
            revision_id TEXT PRIMARY KEY REFERENCES invoice_handoffs(revision_id),
            actor_id TEXT NOT NULL REFERENCES users(id), closed_at TEXT NOT NULL, request_id TEXT NOT NULL,
            debit_ars TEXT NOT NULL, net_ars TEXT NOT NULL, debited_count INTEGER NOT NULL,
            workbook BLOB NOT NULL, sha256 TEXT NOT NULL, UNIQUE(actor_id,request_id))""",
        "DROP TRIGGER handoff_revision_lock",
        """CREATE TRIGGER handoff_revision_lock BEFORE UPDATE ON revisions
           WHEN EXISTS (SELECT 1 FROM invoice_handoffs WHERE revision_id=OLD.id)
            AND NOT (OLD.state!='cerrada' AND NEW.state='cerrada' AND NEW.version=OLD.version+1
                AND NEW.id=OLD.id AND NEW.batch_id=OLD.batch_id AND NEW.ordinal=OLD.ordinal
                AND NEW.created_at=OLD.created_at
                AND EXISTS (SELECT 1 FROM audit_invoice_closures WHERE revision_id=OLD.id))
           BEGIN SELECT RAISE(ABORT,'invoice_already_handed_off'); END""",
        """CREATE TRIGGER finalize_audit_state AFTER INSERT ON audit_invoice_closures
           BEGIN UPDATE revisions SET state='cerrada',version=version+1 WHERE id=NEW.revision_id; END""",
        """CREATE TRIGGER audit_adjustment_closed BEFORE INSERT ON audit_adjustments
           WHEN EXISTS(SELECT 1 FROM audit_invoice_closures WHERE revision_id=NEW.revision_id)
           BEGIN SELECT RAISE(ABORT,'Finalized invoice'); END""",
    ) + tuple(f"CREATE TRIGGER immutable_{table}_{op} BEFORE {op} ON {table} "
              "BEGIN SELECT RAISE(ABORT,'Immutable audit record'); END"
              for table in ('audit_invoice_scope','audit_adjustments','audit_invoice_closures')
              for op in ('UPDATE','DELETE'))),
    (38, (
        """CREATE TABLE csv_export_ranges (
               scope_id TEXT PRIMARY KEY REFERENCES authorization_match_scopes(id),
               complete_from TEXT NOT NULL, complete_until TEXT NOT NULL CHECK(complete_from<=complete_until))""",
        "CREATE TRIGGER csv_range_immutable BEFORE UPDATE ON csv_export_ranges BEGIN SELECT RAISE(ABORT,'Immutable export range'); END",
        "CREATE TRIGGER csv_range_keep BEFORE DELETE ON csv_export_ranges BEGIN SELECT RAISE(ABORT,'Immutable export range'); END",
    )),
    (39, (
        """CREATE TABLE image_budget_links (
            id INTEGER PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES revisions(id), source_row INTEGER NOT NULL,
            dataset_id TEXT NOT NULL REFERENCES datasets(id), capture_sha TEXT NOT NULL, order_id TEXT NOT NULL,
            practice_code TEXT NOT NULL, item_locator TEXT NOT NULL, performed_on TEXT NOT NULL,
            units INTEGER NOT NULL CHECK(units>0), amount_ars TEXT NOT NULL, locator TEXT NOT NULL, reason TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)""",
        'CREATE INDEX image_budget_order ON image_budget_links(dataset_id,capture_sha,order_id,id)',
        "CREATE TRIGGER image_budget_keep BEFORE DELETE ON image_budget_links BEGIN SELECT RAISE(ABORT,'Immutable budget history'); END",
        "CREATE TRIGGER image_budget_history BEFORE UPDATE ON image_budget_links BEGIN SELECT RAISE(ABORT,'Immutable budget history'); END",
    )),
    (40, (
        """CREATE TABLE hpc_code_correspondences (
            id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
            source_id TEXT NOT NULL REFERENCES source_registry(id), source_sha256 TEXT NOT NULL,
            invoice_code TEXT NOT NULL, authorization_code TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
            basis_json TEXT NOT NULL, reason TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)""",
        "CREATE INDEX hpc_code_scope ON hpc_code_correspondences(dataset_id,source_id,id)",
        "CREATE TRIGGER hpc_code_keep BEFORE DELETE ON hpc_code_correspondences BEGIN SELECT RAISE(ABORT,'Immutable correspondence history'); END",
        "CREATE TRIGGER hpc_code_history BEFORE UPDATE ON hpc_code_correspondences BEGIN SELECT RAISE(ABORT,'Immutable correspondence history'); END",
    )),
    (41, (
        "ALTER TABLE hpc_code_correspondences ADD COLUMN relation_kind TEXT NOT NULL DEFAULT 'legacy'",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN factor TEXT NOT NULL DEFAULT '1'",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN billing_unit TEXT NOT NULL DEFAULT 'practice'",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN parent_code TEXT",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN related_code TEXT",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN qualifier_kind TEXT",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN qualifier_value TEXT",
        "ALTER TABLE hpc_code_correspondences ADD COLUMN locator TEXT NOT NULL DEFAULT ''",
    )),
    (42, (
        """CREATE TABLE csv_verified_assignments (
            id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id), revision_id TEXT NOT NULL REFERENCES revisions(id),
            scope_id TEXT NOT NULL, source_row INTEGER NOT NULL, source_sha256 TEXT NOT NULL, locator TEXT NOT NULL,
            row_basis TEXT NOT NULL, reason TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)""",
        'CREATE INDEX csv_assign_scope ON csv_verified_assignments(revision_id,scope_id,id)',
        "CREATE TRIGGER csv_assign_history BEFORE UPDATE ON csv_verified_assignments BEGIN SELECT RAISE(ABORT,'Immutable assignment'); END",
        "CREATE TRIGGER csv_assign_keep BEFORE DELETE ON csv_verified_assignments BEGIN SELECT RAISE(ABORT,'Immutable assignment'); END",
    )),
)


def database_path(data_root: Path) -> Path:
    return data_root / "app.sqlite3"


def backup_before_upgrade(conn: sqlite3.Connection, data_root: Path) -> Path:
    """Copy a coherent SQLite snapshot and immutable objects before a schema upgrade."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    latest = MIGRATIONS[-1][0]
    if not 0 < current < latest:
        raise RuntimeError("Backup upgrade expects an existing older schema")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = data_root / "backups" / f"pre-v{current}-to-v{latest}-{stamp}-{uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=False)
    backup_db = sqlite3.connect(target / "app.sqlite3")
    try:
        conn.backup(backup_db)
        if backup_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
        if backup_db.execute("PRAGMA user_version").fetchone()[0] != current:
            raise RuntimeError("SQLite backup version mismatch")
    finally:
        backup_db.close()
    hashes = {}
    source = data_root / "objects"
    if source.exists():
        for item in sorted(source.glob("*/*")):
            if not item.is_file():
                continue
            relative = item.relative_to(data_root)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest != item.name:
                raise RuntimeError(f"Object backup integrity failed: {relative.as_posix()}")
            hashes[relative.as_posix()] = digest
    expected = {row[0] for row in conn.execute("SELECT sha256 FROM stored_files")}
    if expected - set(hashes.values()):
        raise RuntimeError("Registered source missing from backup")
    (target / "manifest.json").write_text(json.dumps({"schema": current, "objects": hashes},
                                               indent=2), encoding="utf-8")
    return target


def connect(data_root: Path, *, timeout: float = 10) -> sqlite3.Connection:
    from .recovery_guard import recovery_status
    recovery_status(data_root)
    path = database_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may run a sync dependency and its endpoint in different worker threads.
    conn = sqlite3.connect(path, timeout=timeout, isolation_level=None, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    except BaseException:
        # The caller cannot close a connection it never received.
        conn.close()
        raise


def migrate(conn: sqlite3.Connection, migrations=MIGRATIONS, *, allow_existing_upgrade: bool = False) -> int:
    if conn.in_transaction:
        raise RuntimeError("Schema migration requires an idle connection")
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    latest = migrations[-1][0] if migrations else 0
    if current > latest:
        raise RuntimeError(f"Database schema {current} is newer than application schema {latest}")
    if 0 < current < latest and not allow_existing_upgrade:
        raise RuntimeError("Existing database requires an offline backup-and-upgrade before schema migration")
    for version, statements in migrations:
        if version <= current:
            continue
        if version != current + 1:
            raise RuntimeError("Migration versions must be consecutive")
        # SQLite's documented parent-table rebuild procedure requires foreign
        # keys off outside the transaction, then a full check before commit.
        rebuild_parent = version in (9, 31)
        if rebuild_parent:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA legacy_alter_table = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in statements:
                conn.execute(statement)
            if rebuild_parent and conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("Foreign key integrity failed during parent-table rebuild")
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            if rebuild_parent:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA legacy_alter_table = OFF")
        current = version
    return current


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except sqlite3.IntegrityError as error:
        conn.rollback()
        if str(error)=='invoice_already_handed_off':
            from .service import Problem
            from .invoice_handoff import LOCK_MESSAGE
            raise Problem(409,LOCK_MESSAGE) from error
        raise
    except Exception:
        conn.rollback()
        raise
