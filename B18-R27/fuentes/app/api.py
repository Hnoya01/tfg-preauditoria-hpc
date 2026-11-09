"""Private P03 web shell for X1 and versioned source review."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from typing import Annotated

from typing import Literal
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import connect, migrate, transaction
from .controls import list_runs, row_results, run_controls, run_summary
from .review import (alert_detail, change_work_field, decide_alerts, list_alerts,
                     prepare_existing_alerts, work_field_history)
from .provisional import provisional_export
from .proposals import proposal_history
from .economic_evidence import (confirm_provider_scope, evidence_pdf_bytes,
                                list_evidence_documents, provider_scope_history,
                                register_evidence_pdf)
from .hpc_comparison import compare_batch
from urllib.parse import unquote
from . import row_documents
from .hpc_values import save_value_version, value_history
from .hpc_value_status import save_status
from .local_hpc import save as save_local_hpc, listing as list_local_hpc
from .hpc_percentage import preview_percentage, apply_percentage
from .economic_applicability import preview as economic_preview, save_reference as save_economic_reference
from .rn14_proposals import preview as rn14_proposal_preview, save as save_rn14_proposal
from .practice_board import practice_search, practice_detail, decision_preview
from .processing import ProcessingManager, attempts as processing_attempts, enqueue as enqueue_processing, retry as retry_processing
from .reference_readiness import reference_readiness
from .documentary_assessments import documentary_history, save_documentary_assessment
from .authorization_imports import (authorization_inventory, authorization_original, confirm_authorization,
                                    preview_authorization, stage_authorization)
from .authorization_matching import correspondence, save_link, save_scope, scope_history
from .authorization_assessment import preview as authorization_check_preview, save_input as save_authorization_input
from .security import (AccountLocked, authenticate, csrf_valid, current_session,
                       issue_session, now_utc, refresh_activity_if_available, token_digest)
from .service import (Problem, actor, batch_content, batch_metadata, confirm_invoice,
                      create_batch, create_dataset, event, grant_access, invoice_metadata,
                      list_batches, list_datasets, preview_invoice, rename_dataset)
from .storage import MAX_SOURCE_BYTES
from .values_v1 import candidate_values, list_sources


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
UNSAFE = {"POST", "PATCH", "PUT", "DELETE"}


class ObservationBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    revision_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=16, max_length=100)
    rule_code: str = Field(min_length=1, max_length=20)
    action: str = Field(pattern='^(refer|request_info|provide_info|resolve)$')
    duty: str = Field(pattern='^(administrative|auditor)$')
    foundation: str = Field(min_length=10, max_length=4000)
    evidence_note: str = Field(min_length=10, max_length=4000)
    decision: str | None = None


class LoginBody(BaseModel):
    username: str
    password: str


class CodeCorrespondenceBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(ge=1, strict=True)
    pairs: list[list[str]] | None = None
    active: bool = True
    reason: str = Field(min_length=10, max_length=2000)
    relation_kind: str = 'direct'
    factor: str = '1'
    billing_unit: str = 'practice'
    changes: list[dict] | None = None
    locator: str = ''


class AuthorizationImportBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(ge=1, strict=True)
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    provenance_note: str = Field(min_length=10, max_length=2000)
    reinterpret_capture_id: str | None = None


class PracticeRequestBody(BaseModel):
    version: int
    revision: int
    code: str
    kind: str
    reason: str


class CsvReviewBody(BaseModel):
    model_config = {'extra':'forbid'}
    version: int
    revision_id: str
    revision_version: int
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    request_id: str = Field(min_length=16,max_length=100)
    note: str = Field(min_length=10,max_length=2000)


class PracticeAnswerBody(BaseModel):
    version: int
    state: str
    reason: str


class HandoffBody(BaseModel):
    model_config = {'extra':'forbid'}
    revision_id: str
    expected_dataset_version: int = Field(ge=1,strict=True)
    expected_revision_version: int = Field(ge=1,strict=True)
    request_id: str = Field(min_length=16,max_length=100)


class AuditVersionBody(BaseModel):
    model_config = {'extra':'forbid'}
    revision_id: str = Field(min_length=1,max_length=100)
    expected_dataset_version: int = Field(ge=1,strict=True)


class AuditAdjustmentBody(AuditVersionBody):
    amount_ars: str = Field(max_length=25)
    reason: str = Field(min_length=1,max_length=4000)


class AuditCloseBody(AuditVersionBody):
    expected_debit_ars: str = Field(max_length=25)
    request_id: str = Field(min_length=16,max_length=100)


class ImageBudgetBody(BaseModel):
    replace_link: int | None = None
    revision_id: str
    expected_dataset_version: int
    evidence_hash: str
    amount_ars: str = Field(max_length=28)
    locator: str = Field(min_length=3,max_length=500)
    reason: str = Field(min_length=3,max_length=2000)


class RowDecisionBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    revision_id: str
    evidence_hash: str = Field(min_length=64,max_length=64)
    request_id: str = Field(min_length=16,max_length=100)
    action: Literal['accept','partial','total','none']
    reference: Literal['budget','agreement'] | None = None
    partial_ars: str | None = Field(default=None,max_length=30)
    reason: str = Field(default='',max_length=2000)


class PracticeSearchBody(BaseModel):
    model_config = {'extra': 'forbid'}
    scope: str = 'included'
    view: str = 'all'
    state: str | None = None
    rule: str | None = None
    rules: list[str] = Field(default_factory=list, max_length=11)
    rules_match: str = 'any'
    reason: str | None = Field(default=None, max_length=200)
    decision: str | None = None
    code: str | None = Field(default=None, max_length=80)
    text: str | None = Field(default=None, max_length=100)
    search: str | None = Field(default=None, max_length=100)
    family: str = 'all'
    report_document_state: str = 'all'
    authorization_document_state: str = 'all'
    reference_comparison_state: str = 'all'
    csv_review_state: str = 'all'
    exception_reason: str | None = Field(default=None, max_length=100)
    date_from: str | None = None
    date_to: str | None = None
    after_source_row: int | None = Field(default=None, ge=2, strict=True)
    saved_source_row: int | None = Field(default=None, ge=2, strict=True)
    sort: str = 'source_row'
    direction: str = 'asc'
    offset: int = Field(default=0, ge=0, le=100000, strict=True)
    limit: int = Field(default=50, ge=1, le=100, strict=True)


class AuthorizationScopeBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(ge=1, strict=True)
    capture_ids: list[str] = Field(min_length=1, max_length=8)
    mode: str
    note: str = Field(min_length=10, max_length=2000)
    synthetic_invoice_confirmed: bool = Field(default=False, strict=True)
    csv_complete_from: str | None = None
    csv_complete_until: str | None = None


class AuthorizationLinkBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    basis_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    state: str
    candidate_key: str | None = None
    note: str = Field(min_length=10, max_length=2000)


class CsvAssignmentBody(BaseModel):
    model_config={'extra':'forbid'}
    expected_version: int = Field(ge=1,strict=True)
    expected_revision_version: int = Field(ge=1,strict=True)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    locator: str = Field(max_length=300)
    reason: str = Field(min_length=10,max_length=2000)


class IncorporationGroupBody(BaseModel):
    model_config={'extra':'forbid'}
    expected_version: int = Field(ge=1,strict=True)
    expected_revision_version: int = Field(ge=1,strict=True)
    rows: list[Annotated[int, Field(strict=True,ge=1)]] = Field(min_length=1,max_length=2000)
    incorporation: str
    locator: str = Field(min_length=3,max_length=300)


class AuthorizationInputBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    kind: str
    state: str
    value: str | None = None
    provenance: str = Field(min_length=10, max_length=2000)
    locator: str = Field(min_length=3, max_length=300)


class DocumentaryAssessmentBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    provider: str
    code_complete: str
    tariff_seq: int = Field(ge=1, strict=True)
    document_id: str
    edition: str
    page_number: int = Field(ge=1, le=10000, strict=True)
    fragment: str
    observed_factor: str | None = None
    conclusion: str
    note: str


class HpcValueBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    tariff_seq: int = Field(ge=1, strict=True)
    code: str
    amount_ars: str
    unit_label: str
    effective_from: str
    document_id: str
    page_number: int = Field(ge=1, le=10000, strict=True)
    excerpt: str
    reason: str


class RowDocumentReviewBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    revision_id: str
    request_id: str
    note: str


class HpcStatusBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    tariff_seq: int = Field(ge=1, strict=True)
    active: bool = Field(strict=True)
    effective_from: str
    document_id: str
    page_number: int = Field(ge=1, le=10000, strict=True)
    excerpt: str
    reason: str


class HpcPercentageBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    tariff_seqs: list[Annotated[int, Field(strict=True, ge=1)]] = Field(default_factory=list, max_length=1000)
    local_ids: list[str] = Field(default_factory=list, max_length=1000)
    percentage: str
    effective_from: str
    document_id: str
    page_number: int = Field(ge=1, le=10000, strict=True)
    excerpt: str
    reason: str
    base_currency: str | None = None
    base_unit_label: str | None = None
    base_declaration: bool = Field(default=False, strict=True)


class HpcPercentageApplyBody(HpcPercentageBody):
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class LocalHpcBody(BaseModel):
    model_config = {'extra':'forbid'}
    expected_dataset_version: int = Field(ge=1,strict=True)
    practice_id: str | None = None
    code: str
    description: str
    family: str
    amount_ars: str
    currency: str
    unit_label: str
    active: bool = Field(strict=True)
    effective_from: str
    document_id: str
    page_number: int = Field(ge=1,strict=True)
    excerpt: str
    reason: str


class DatasetBody(BaseModel):
    label: str


class RenameBody(BaseModel):
    label: str
    expected_version: int = Field(ge=1)


class AccessBody(BaseModel):
    invoice_duty: str | None = None
    username: str
    role: str
    expected_version: int = Field(ge=1)


class ConfirmInvoiceBody(BaseModel):
    period: str
    expected_version: int = Field(ge=1)
    period_confirmed: bool


class AnalyzeBody(BaseModel):
    expected_version: int = Field(ge=1)


class ProcessingBody(BaseModel):
    model_config = {'extra':'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,80}$')


class RetryProcessingBody(BaseModel):
    model_config = {'extra':'forbid'}
    expected_attempt_version: int = Field(ge=1, strict=True)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,80}$')


class DecisionItem(BaseModel):
    id: str
    expected_version: int = Field(ge=1)


class DecideBody(BaseModel):
    expected_dataset_version: int = Field(ge=1)
    expected_revision_version: int = Field(ge=1)
    items: list[DecisionItem]
    state: str
    foundation: str
    evidence_note: str | None = None
    preview_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class DecisionPreviewBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    items: list[DecisionItem] = Field(min_length=1, max_length=100)


class WorkChangeBody(BaseModel):
    expected_dataset_version: int = Field(ge=1)
    expected_revision_version: int = Field(ge=1)
    field: str
    value: str
    reason: str


class AgreementDeclarationBody(BaseModel):
    expected_dataset_version: int
    tariff_seqs: list[int]
    document_id: str
    currency: str
    unit_label: str
    valid_from: str
    valid_until: str | None = None
    page_number: int
    excerpt: str
    conditions_note: str
    reason: str
    replaces_id: str | None = None


class AgreementDeclarationSaveBody(AgreementDeclarationBody):
    preview_sha256: str


class AgreementWithdrawalBody(BaseModel):
    expected_dataset_version: int
    reason: str


class ProviderScopeBody(BaseModel):
    expected_dataset_version: int = Field(ge=1)
    expected_revision_version: int = Field(ge=1)
    source_id: str
    provider: str
    billing_unit: str = "unverified"
    billing_unit_note: str | None = None
    confirmation_note: str


class EconomicApplicabilityBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    source_id: str
    basis_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    state: str
    reference_kind: str = 'general_hpc_base_no_additions'
    document_id: str | None = None
    page_number: int | None = Field(default=None, ge=1, le=10000, strict=True)
    excerpt: str = Field(default='', max_length=2000)
    covered_quantity: str = Field(default='', max_length=64)
    currency: str = 'ARS'
    billing_unit: str = 'practice'
    coverage_through: str | None = None
    note: str = Field(min_length=10, max_length=2000)


class Rn14ProposalBody(BaseModel):
    model_config = {'extra':'forbid'}
    expected_dataset_version: int = Field(ge=1,strict=True)
    expected_revision_version: int = Field(ge=1,strict=True)
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    action: str
    adjusted_ars: str | None = Field(default=None,max_length=32)
    adjustment_calculation: str | None = Field(default=None,max_length=2000)
    adjustment_reason: str | None = Field(default=None,max_length=2000)


class ConsultationBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    revision_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=16, max_length=100)
    question: str = Field(min_length=10, max_length=4000)


class ExternalResponseBody(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_dataset_version: int = Field(ge=1, strict=True)
    expected_revision_version: int = Field(ge=1, strict=True)
    revision_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=16, max_length=100)
    author_name: str = Field(min_length=2, max_length=200)
    responded_at: str = Field(max_length=80)
    channel: str = Field(max_length=30)
    provenance: str = Field(min_length=10, max_length=2000)
    response: str = Field(min_length=10, max_length=4000)


class ClosureLimitationBody(BaseModel):
    expected_dataset_version: int
    expected_revision_version: int
    group_key: str = Field(min_length=64,max_length=64)
    scope_sha256: str = Field(min_length=64,max_length=64)
    foundation: str = Field(min_length=10,max_length=4000)


class ClosureBody(BaseModel):
    expected_dataset_version: int
    expected_revision_version: int
    preview_sha256: str = Field(min_length=64,max_length=64)
    confirmed_limitation_ids: list[str] = Field(max_length=1000)


class NewRevisionBody(BaseModel):
    previous_revision_id: str
    expected_dataset_version: int = Field(ge=1)
    expected_revision_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)


def create_app(data_root: Path | None = None, *, public_origin: str | None = None,
               local_http: bool | None = None, processing_enabled: bool = True) -> FastAPI:
    root = Path(data_root or os.environ.get("TFG_DATA_DIR", "data")).resolve()
    source_dir = WEB_DIR.parent / "trabajo_final_auditoria_fuentes"
    if root.is_relative_to(WEB_DIR) or root.is_relative_to(source_dir):
        raise ValueError("Data directory cannot be public assets or original sources")
    origin = public_origin or os.environ.get("TFG_PUBLIC_ORIGIN")
    insecure_local = local_http if local_http is not None else os.environ.get("TFG_LOCAL_HTTP") == "1"
    if insecure_local and (not origin or not origin.startswith(("http://localhost:", "http://127.0.0.1:"))):
        raise ValueError("Local HTTP is permitted only for localhost")

    from .board_projection import BoardProjection
    board_projection=BoardProjection(root)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from .recovery_guard import recovery_status
        restored = recovery_status(root)
        conn = connect(root)
        try:
            migrate(conn)
        finally:
            conn.close()
        manager = ProcessingManager(root) if processing_enabled and not restored else None
        _app.state.processing_manager = manager
        if manager:
            manager.start()
        try:
            yield
        finally:
            board_projection.close()
            if manager:
                manager.close()

    app = FastAPI(title="TFG preauditoría P05", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.data_root = root
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    def log_denial(request: Request) -> None:
        cookie = request.cookies.get("tfg_session")
        digest = token_digest(cookie) if cookie else None
        conn = None
        try:
            conn = connect(root, timeout=0)
            known = conn.execute("SELECT user_id FROM sessions WHERE token_hash = ?", (digest,)).fetchone() if digest else None
            route = request.scope.get("route")
            route_name = route.path if route is not None else "unmatched"
            with transaction(conn):
                conn.execute("INSERT INTO audit_events VALUES (?, ?, 'access_denied', 'route', ?, ?)",
                             (str(uuid4()), known["user_id"] if known else None, route_name, now_utc()))
        except sqlite3.Error:
            # Preserve the denial even if the audit store is unavailable.
            pass
        finally:
            if conn is not None:
                conn.close()

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem):
        if exc.status in {401, 403}:
            log_denial(request)
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(sqlite3.OperationalError)
    async def sqlite_contention(_request: Request, exc: sqlite3.OperationalError):
        if getattr(exc, "sqlite_errorcode", 0) & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return JSONResponse({"detail": "Hay otra escritura en curso; actualizá la vista y reintentá"},
                                status_code=503, headers={"Retry-After": "1"})
        raise exc

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        if request.method in UNSAFE:
            expected_origin = origin or str(request.base_url).rstrip("/")
            if request.headers.get("origin") != expected_origin:
                log_denial(request)
                response = JSONResponse({"detail": "Origen no permitido"}, status_code=403)
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response
        response = await call_next(request)
        digest = getattr(request.state, "validated_session_digest", None)
        if digest:
            refresh_activity_if_available(root, digest)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def connection():
        conn = connect(root)
        try:
            yield conn
        finally:
            conn.close()

    def token_hash(request: Request,
                   conn: sqlite3.Connection = Depends(connection)) -> str:
        cookie = request.cookies.get("tfg_session")
        if cookie is None:
            raise Problem(401, "Sesión requerida")
        digest = token_digest(cookie)
        session = current_session(conn, digest, touch=False)
        if session is None:
            raise Problem(401, "Sesión ausente o vencida")
        if request.method in UNSAFE and not csrf_valid(session, request.headers.get("X-CSRF-Token")):
            raise Problem(403, "Comprobación CSRF fallida")
        batch_id=request.path_params.get('batch_id')
        if batch_id and request.scope['route'].name in ('closure_confirm','closure_preview'):
            dataset_id=request.path_params['dataset_id']
            if conn.execute('SELECT 1 FROM invoice_review_duties WHERE dataset_id=? LIMIT 1',(dataset_id,)).fetchone():
                from .service import authorized_dataset
                authorized_dataset(conn,digest,dataset_id,'reviewer')
                raise Problem(409,'El cierre de Imágenes se realiza en Planilla: primero el pase, luego la confirmación del auditor.')
        if batch_id and request.method in UNSAFE and request.scope['route'].name not in {
                'new_revision','handoff_send','audit_adjust','audit_confirm','search_practices','preview_selected_decisions','closure_preview'}:
            locked=conn.execute('SELECT h.revision_id FROM revisions r LEFT JOIN invoice_handoffs h ON h.revision_id=r.id '
                                'JOIN batches b ON b.id=r.batch_id WHERE r.batch_id=? AND b.dataset_id=? ORDER BY r.ordinal DESC LIMIT 1',
                                (batch_id,request.path_params['dataset_id'])).fetchone()
            if locked and locked['revision_id']:
                from .service import authorized_dataset
                from .invoice_handoff import LOCK_MESSAGE
                authorized_dataset(conn,digest,request.path_params['dataset_id'],'reviewer')
                raise Problem(409,LOCK_MESSAGE)
        request.state.validated_session_digest = digest
        return digest

    @app.get("/")
    def home():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ready", "stage": "P05"}

    @app.post("/api/session")
    def login(body: LoginBody, request: Request, conn: sqlite3.Connection = Depends(connection)):
        try:
            user = authenticate(conn, body.username, body.password,
                                request.client.host if request.client else "unknown")
        except AccountLocked:
            raise Problem(429, "Ingreso restringido temporalmente") from None
        if user is None:
            raise Problem(401, "Credenciales inválidas")
        token, csrf = issue_session(conn, user["id"])
        response = JSONResponse({"username": user["username"], "role": user["role"], "csrf_token": csrf})
        response.set_cookie("tfg_session", token, max_age=8 * 3600, secure=not insecure_local,
                            httponly=True, samesite="lax", path="/")
        return response

    @app.delete("/api/session")
    def logout(digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        with transaction(conn):
            user = actor(conn, digest)
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            event(conn, user["id"], "logout", "user", user["id"])
        response = Response(status_code=204)
        response.delete_cookie("tfg_session", path="/", secure=not insecure_local,
                               httponly=True, samesite="lax")
        return response

    @app.get("/api/me")
    def me(digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        user = current_session(conn, digest)
        return {"username": user["username"], "role": user["role"],
                "csrf_token": user["csrf_token"]}

    @app.get("/api/datasets")
    def datasets(digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return list_datasets(conn, digest)

    @app.post("/api/datasets", status_code=201)
    def new_dataset(body: DatasetBody, digest: str = Depends(token_hash),
                    conn: sqlite3.Connection = Depends(connection)):
        return create_dataset(conn, digest, body.label)

    @app.patch("/api/datasets/{dataset_id}")
    def change_dataset(dataset_id: str, body: RenameBody, digest: str = Depends(token_hash),
                       conn: sqlite3.Connection = Depends(connection)):
        return rename_dataset(conn, digest, dataset_id, body.expected_version, body.label)

    @app.post("/api/datasets/{dataset_id}/access")
    def access(dataset_id: str, body: AccessBody, digest: str = Depends(token_hash),
               conn: sqlite3.Connection = Depends(connection)):
        return grant_access(conn, digest, dataset_id, body.expected_version, body.username, body.role, body.invoice_duty)

    @app.post("/api/datasets/{dataset_id}/batches")
    async def stage_batch(dataset_id: str, request: Request,
                          expected_version: int = Header(alias="X-Expected-Version", ge=1),
                          filename: str = Header(alias="X-Source-Filename"),
                          digest: str = Depends(token_hash),
                          conn: sqlite3.Connection = Depends(connection)):
        parts = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise Problem(413, "Archivo demasiado grande para la carga local")
            parts.append(chunk)
        result, created = create_batch(conn, root, digest, dataset_id, expected_version,
                                       filename, b"".join(parts))
        return JSONResponse(result, status_code=201 if created else 200)

    @app.get("/api/datasets/{dataset_id}/batches")
    def batches(dataset_id: str, digest: str = Depends(token_hash),
                conn: sqlite3.Connection = Depends(connection)):
        return list_batches(conn, digest, dataset_id)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/invoice-preview")
    def invoice_preview(dataset_id: str, batch_id: str, period: str,
                        digest: str = Depends(token_hash),
                        conn: sqlite3.Connection = Depends(connection)):
        return preview_invoice(conn, root, digest, dataset_id, batch_id, period)

    @app.post("/api/datasets/{dataset_id}/batches/{batch_id}/invoice-import")
    def invoice_import(dataset_id: str, batch_id: str, body: ConfirmInvoiceBody,
                       digest: str = Depends(token_hash),
                       conn: sqlite3.Connection = Depends(connection)):
        if not body.period_confirmed:
            raise Problem(422, "Confirmá explícitamente el período antes de incorporar")
        result, created = confirm_invoice(conn, root, digest, dataset_id, batch_id,
                                          body.period, body.expected_version)
        return JSONResponse(result, status_code=201 if created else 200)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/invoice-import")
    def get_invoice_import(dataset_id: str, batch_id: str, digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return invoice_metadata(conn, digest, dataset_id, batch_id)

    @app.post("/api/datasets/{dataset_id}/batches/{batch_id}/control-runs")
    def analyze(dataset_id: str, batch_id: str, body: AnalyzeBody,
                digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        result, created = run_controls(conn, digest, dataset_id, batch_id, body.expected_version)
        return JSONResponse(result, status_code=201 if created else 200)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/processing-attempts')
    def start_processing(dataset_id: str, batch_id: str, body: ProcessingBody,
                         digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        attempt, created = enqueue_processing(conn,digest,dataset_id,batch_id,**body.model_dump())
        return JSONResponse(attempt,status_code=202 if created else 200)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/processing-attempts')
    def processing_history(dataset_id: str, batch_id: str, digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return processing_attempts(conn,digest,dataset_id,batch_id)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/processing-attempts/{attempt_id}')
    def processing_status(dataset_id: str, batch_id: str, attempt_id: str, digest: str = Depends(token_hash),
                          conn: sqlite3.Connection = Depends(connection)):
        return processing_attempts(conn,digest,dataset_id,batch_id,attempt_id)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/processing-attempts/{attempt_id}/retry')
    def retry_processing_attempt(dataset_id: str, batch_id: str, attempt_id: str, body: RetryProcessingBody,
                                 digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        attempt, created = retry_processing(conn,digest,dataset_id,batch_id,attempt_id,**body.model_dump())
        return JSONResponse(attempt,status_code=202 if created else 200)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/control-runs")
    def batch_control_runs(dataset_id: str, batch_id: str, digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return list_runs(conn, digest, dataset_id, batch_id)

    @app.get("/api/datasets/{dataset_id}/control-runs/{run_id}")
    def control_run(dataset_id: str, run_id: str, digest: str = Depends(token_hash),
                    conn: sqlite3.Connection = Depends(connection)):
        return run_summary(conn, digest, dataset_id, run_id)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/analysis-history')
    def analysis_history_list(dataset_id: str, batch_id: str, offset: int = 0, limit: int = 50,
                              digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .analysis_history import history
        return history(conn, digest, dataset_id, batch_id=batch_id, offset=offset, limit=limit)

    @app.get('/api/datasets/{dataset_id}/analysis-history/{identity}')
    def analysis_history_detail(dataset_id: str, identity: str, offset: int = 0, limit: int = 50,
                                digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .analysis_history import history
        return history(conn, digest, dataset_id, identity=identity, offset=offset, limit=limit)

    @app.get("/api/datasets/{dataset_id}/control-runs/{run_id}/rows/{source_row}")
    def control_row(dataset_id: str, run_id: str, source_row: int,
                    digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return row_results(conn, digest, dataset_id, run_id, source_row)

    @app.post("/api/datasets/{dataset_id}/batches/{batch_id}/alerts/materialize")
    def materialize_existing(dataset_id: str, batch_id: str, body: AnalyzeBody,
                             digest: str = Depends(token_hash),
                             conn: sqlite3.Connection = Depends(connection)):
        return prepare_existing_alerts(conn, digest, dataset_id, batch_id, body.expected_version)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/alerts")
    def batch_alerts(dataset_id: str, batch_id: str, offset: int = 0, limit: int = 50,
                     include_historical: bool = False,
                     digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return list_alerts(conn, digest, dataset_id, batch_id, offset, limit, include_historical)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/export-provisional")
    def export_provisional(dataset_id: str, batch_id: str,
                           digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        content, sha256, manifest = provisional_export(conn, root, digest, dataset_id, batch_id)
        filename = f"revision-{manifest['batch']['revision_id']}-provisional.zip"
        return Response(content=content, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                 "X-Content-SHA256": sha256})

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/closure-preview')
    def closure_preview(dataset_id: str, batch_id: str, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .closure import preview
        return preview(conn,digest,dataset_id,batch_id)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/closure-limitations',status_code=201)
    def closure_limitation(dataset_id: str, batch_id: str, body: ClosureLimitationBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .closure import save_limitation
        return save_limitation(conn,digest,dataset_id,batch_id,**body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/closure-summary')
    def closure_summary(dataset_id: str,batch_id: str,revision_id: str | None = None,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .closure_views import closed_summary
        return closed_summary(conn,digest,dataset_id,batch_id,revision_id)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/closure-members')
    def closure_members(dataset_id: str,batch_id: str,group_key: str,scope_sha256: str,offset: int=0,limit: int=50,
                        revision_id: str | None=None,expected_dataset_version: int | None=None,expected_revision_version: int | None=None,
                        digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .closure_views import members
        return members(conn,digest,dataset_id,batch_id,group_key,scope_sha256,offset,limit,revision_id,
                       expected_dataset_version,expected_revision_version)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/closure',status_code=201)
    def closure_confirm(dataset_id: str, batch_id: str, body: ClosureBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .closure import close
        return close(conn,root,digest,dataset_id,batch_id,**body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/export-closed')
    def closed_export(dataset_id: str, batch_id: str, revision_id: str | None = None, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .closure import download
        content,sha,revision = download(conn,root,digest,dataset_id,batch_id,revision_id)
        return Response(content=content,media_type='application/zip',headers={
            'Content-Disposition':f'attachment; filename="revision-{revision}-closed.zip"','X-Content-SHA256':sha})

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/revisions')
    def revision_history(dataset_id: str, batch_id: str, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .revisions import history
        return history(conn,digest,dataset_id,batch_id)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/revisions',status_code=201)
    def new_revision(dataset_id: str, batch_id: str, body: NewRevisionBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .revisions import start
        return start(conn,digest,dataset_id,batch_id,**body.model_dump())

    @app.get('/api/datasets/{dataset_id}/auditor-handoffs')
    def auditor_inbox(dataset_id: str,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_handoff import inbox
        return inbox(conn,digest,dataset_id)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/handoff')
    def handoff_status(dataset_id: str,batch_id: str,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_handoff import status
        return status(conn,root,digest,dataset_id,batch_id)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/handoff',status_code=201)
    def handoff_send(dataset_id: str,batch_id: str,body: HandoffBody,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_handoff import send
        return send(conn,root,digest,dataset_id,batch_id,body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/handoff/audit')
    def audit_summary(dataset_id: str,batch_id: str,offset: int=Query(default=0,ge=0),limit: int=Query(default=50,ge=1,le=100),
                      digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_audit import summary
        return summary(conn,root,digest,dataset_id,batch_id,offset,limit)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/handoff/audit/rows/{number}')
    def audit_adjust(dataset_id: str,batch_id: str,number: int,body: AuditAdjustmentBody,
                     digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_audit import adjust
        return adjust(conn,digest,dataset_id,batch_id,number,body.model_dump())

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/handoff/audit/close')
    def audit_confirm(dataset_id: str,batch_id: str,body: AuditCloseBody,
                      digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_audit import confirm
        return confirm(conn,root,digest,dataset_id,batch_id,body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/handoff/audit/excel')
    def audit_excel(dataset_id: str,batch_id: str,revision_id: str | None=None,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_audit import download
        return Response(download(conn,digest,dataset_id,batch_id,revision_id),
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="Debitos-Imagenes-HPC.xlsx"','Cache-Control':'no-store'})

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{number}/budget-link')
    def bind_image_budget(dataset_id: str,batch_id: str,number: int,body: ImageBudgetBody,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .image_budgets import bind
        return bind(conn,root,digest,dataset_id,batch_id,number,body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/observations.pdf')
    def image_pdf(dataset_id: str,batch_id: str,revision_id: str | None=None,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .image_reports import pdf_download
        return Response(pdf_download(conn,root,digest,dataset_id,batch_id,revision_id),media_type='application/pdf',
                        headers={'Content-Disposition':'attachment; filename="Observaciones-HPC.pdf"','Cache-Control':'no-store'})

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/handoff/decisions')
    def handoff_decisions(dataset_id: str,batch_id: str,offset: int=Query(default=0,ge=0),limit: int=Query(default=50,ge=1,le=100),
                          digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .invoice_handoff import received
        return received(conn,digest,dataset_id,batch_id,offset,limit)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{number}/administrative-decision')
    def administrative_decision(dataset_id: str,batch_id: str,number: int,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .row_decisions import detail
        return detail(conn,root,digest,dataset_id,batch_id,number)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{number}/administrative-decision',status_code=201)
    def save_administrative_decision(dataset_id: str,batch_id: str,number: int,body: RowDecisionBody,digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        from .row_decisions import save
        return save(conn,root,digest,dataset_id,batch_id,number,body.model_dump())

    @app.get('/api/datasets/{dataset_id}/observation-inbox')
    def observation_inbox(dataset_id: str, all_cases: bool = False, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .observation_workflow import inbox
        return inbox(conn, digest, dataset_id, all_cases)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/observations')
    def observation_page(dataset_id: str, batch_id: str, source_row: int, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .observation_workflow import page
        return page(conn, digest, dataset_id, batch_id, source_row)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/observations', status_code=201)
    def observation_save(dataset_id: str, batch_id: str, source_row: int, body: ObservationBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .observation_workflow import save
        return save(conn, digest, dataset_id, batch_id, source_row, **body.model_dump())

    @app.get("/api/datasets/{dataset_id}/alerts/{alert_id}")
    def get_alert(dataset_id: str, alert_id: str, digest: str = Depends(token_hash),
                  conn: sqlite3.Connection = Depends(connection)):
        return alert_detail(conn, digest, dataset_id, alert_id)

    @app.post("/api/datasets/{dataset_id}/batches/{batch_id}/decisions")
    def decide(dataset_id: str, batch_id: str, body: DecideBody,
               digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return decide_alerts(conn, digest, dataset_id, batch_id,
                             body.expected_dataset_version, body.expected_revision_version,
                             [item.model_dump() for item in body.items], body.state,
                             body.foundation, body.evidence_note, preview_sha256=body.preview_sha256)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/decision-preview')
    def preview_selected_decisions(dataset_id: str, batch_id: str, body: DecisionPreviewBody,
                                   digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return decision_preview(conn,digest,dataset_id,batch_id,body.expected_dataset_version,
                                body.expected_revision_version,[item.model_dump() for item in body.items])

    @app.post("/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/work-fields")
    def correct_work_field(dataset_id: str, batch_id: str, source_row: int,
                           body: WorkChangeBody, digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return change_work_field(conn, digest, dataset_id, batch_id, source_row,
                                 body.field, body.value, body.reason,
                                 body.expected_dataset_version, body.expected_revision_version)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/work-fields")
    def get_work_history(dataset_id: str, batch_id: str, source_row: int,
                         digest: str = Depends(token_hash),
                         conn: sqlite3.Connection = Depends(connection)):
        return work_field_history(conn, digest, dataset_id, batch_id, source_row)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/proposals")
    def get_proposal_history(dataset_id: str, batch_id: str, source_row: int,
                             digest: str = Depends(token_hash),
                             conn: sqlite3.Connection = Depends(connection)):
        return proposal_history(conn, root, digest, dataset_id, batch_id, source_row)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/consultations')
    def get_consultations(dataset_id: str, batch_id: str, source_row: int,
                          digest: str=Depends(token_hash), conn: sqlite3.Connection=Depends(connection)):
        from .medical_consultations import history
        return history(conn, digest, dataset_id, batch_id, source_row)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/consultations', status_code=201)
    def post_consultation(dataset_id: str, batch_id: str, source_row: int, body: ConsultationBody,
                          digest: str=Depends(token_hash), conn: sqlite3.Connection=Depends(connection)):
        from .medical_consultations import save
        return save(conn, digest, dataset_id, batch_id, source_row, **body.model_dump())

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/consultations/{consultation_id}/responses', status_code=201)
    def post_external_response(dataset_id: str, batch_id: str, source_row: int, consultation_id: str,
                               body: ExternalResponseBody, digest: str=Depends(token_hash), conn: sqlite3.Connection=Depends(connection)):
        from .medical_consultations import save
        return save(conn, digest, dataset_id, batch_id, source_row, consultation_id=consultation_id, **body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/rn14-proposal')
    def get_rn14_proposal(dataset_id: str,batch_id: str,source_row: int,
                          digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        return rn14_proposal_preview(conn,root,digest,dataset_id,batch_id,source_row)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/rn14-proposal',status_code=201)
    def post_rn14_proposal(dataset_id: str,batch_id: str,source_row: int,body: Rn14ProposalBody,
                           digest: str=Depends(token_hash),conn: sqlite3.Connection=Depends(connection)):
        return save_rn14_proposal(conn,root,digest,dataset_id,batch_id,source_row,**body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/economic-applicability')
    def get_economic_applicability(dataset_id: str, batch_id: str, source_row: int, source_id: str,
                                  digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return economic_preview(conn, root, digest, dataset_id, batch_id, source_row, source_id)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/economic-applicability', status_code=201)
    def post_economic_applicability(dataset_id: str, batch_id: str, source_row: int, body: EconomicApplicabilityBody,
                                   digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return save_economic_reference(conn, root, digest, dataset_id, batch_id, source_row, **body.model_dump())

    @app.post("/api/datasets/{dataset_id}/batches/{batch_id}/provider-scope")
    def set_provider_scope(dataset_id: str, batch_id: str, body: ProviderScopeBody,
                           digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return confirm_provider_scope(conn, root, digest, dataset_id, batch_id,
                                      body.source_id, body.provider, body.billing_unit,
                                      body.confirmation_note, body.expected_dataset_version,
                                      body.expected_revision_version, billing_unit_note=body.billing_unit_note)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/provider-scope")
    def get_provider_scope(dataset_id: str, batch_id: str,
                           digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return provider_scope_history(conn, digest, dataset_id, batch_id)

    @app.post("/api/datasets/{dataset_id}/evidence-pdfs")
    async def upload_evidence_pdf(dataset_id: str, request: Request,
                                  expected_version: int = Header(alias="X-Expected-Version", ge=1),
                                  source_id: str = Header(alias="X-Source-Id"),
                                  filename: str = Header(alias="X-Source-Filename"),
                                  category: str = Header(alias="X-Evidence-Category"),
                                  provenance_note: str = Header(alias="X-Provenance-Note"),
                                  expected_sha256: str = Header(alias="X-Expected-SHA256"),
                                  digest: str = Depends(token_hash),
                                  conn: sqlite3.Connection = Depends(connection)):
        parts = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise Problem(413, "PDF demasiado grande para la carga local")
            parts.append(chunk)
        result, created = register_evidence_pdf(
            conn, root, digest, dataset_id, source_id, expected_version, filename,
            category, provenance_note, expected_sha256, b"".join(parts))
        return JSONResponse(result, status_code=201 if created else 200)

    @app.get("/api/datasets/{dataset_id}/evidence-pdfs")
    def evidence_pdfs(dataset_id: str, digest: str = Depends(token_hash),
                      conn: sqlite3.Connection = Depends(connection)):
        return list_evidence_documents(conn, digest, dataset_id)

    @app.get("/api/datasets/{dataset_id}/evidence-pdfs/{document_id}/file")
    def evidence_pdf(dataset_id: str, document_id: str,
                     digest: str = Depends(token_hash),
                     conn: sqlite3.Connection = Depends(connection)):
        content, sha256 = evidence_pdf_bytes(conn, root, digest, dataset_id, document_id)
        return Response(content=content, media_type="application/pdf",
                        headers={"X-Content-SHA256": sha256,
                                 "Content-Disposition": 'attachment; filename="evidence.pdf"'})

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/documents')
    def row_document_history(dataset_id: str, batch_id: str, source_row: int,
                             digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return row_documents.history(conn, digest, dataset_id, batch_id, source_row)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/documents')
    async def row_document_upload(dataset_id: str, batch_id: str, source_row: int, request: Request,
        expected_dataset_version: int = Header(alias='X-Expected-Version', ge=1),
        expected_revision_version: int = Header(alias='X-Revision-Version', ge=1),
        revision_id: str = Header(alias='X-Revision-Id'), request_id: str = Header(alias='X-Request-Id'),
        category: str = Header(alias='X-Document-Category'), original_name: str = Header(alias='X-Source-Filename'),
        provenance: str = Header(alias='X-Provenance-Note'), expected_sha256: str = Header(alias='X-Expected-SHA256'),
        digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        # Reject inaccessible rows before buffering private content.
        row_documents._context(conn, digest, dataset_id, batch_id, source_row)
        parts=[]; total=0
        async for chunk in request.stream():
            total+=len(chunk)
            if total>row_documents.MAX_DOCUMENT_BYTES: raise Problem(413, 'El PDF supera 10 MiB')
            parts.append(chunk)
        result=row_documents.register(conn,root,digest,dataset_id,batch_id,source_row,
            expected_dataset_version=expected_dataset_version, expected_revision_version=expected_revision_version,
            revision_id=revision_id,request_id=request_id,category=category,original_name=unquote(original_name),
            provenance=unquote(provenance),expected_sha256=expected_sha256,content=b''.join(parts))
        return JSONResponse(result,status_code=201 if result['created'] else 200)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/documents/{document_id}/reviews')
    def row_document_review(dataset_id: str,batch_id: str,source_row: int,document_id: str,body: RowDocumentReviewBody,
                            digest: str = Depends(token_hash),conn: sqlite3.Connection = Depends(connection)):
        return row_documents.review(conn,root,digest,dataset_id,batch_id,source_row,document_id,**body.model_dump())

    @app.get('/api/datasets/{dataset_id}/row-documents/{document_id}/file')
    def row_document_file(dataset_id: str,document_id: str,digest: str = Depends(token_hash),
                          conn: sqlite3.Connection = Depends(connection)):
        content,sha=row_documents.original(conn,root,digest,dataset_id,document_id)
        return Response(content=content,media_type='application/pdf',headers={
            'Content-Disposition':'attachment; filename="documento-aportado.pdf"',
            'X-Content-SHA256':sha,'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})

    @app.get("/api/datasets/{dataset_id}/sources")
    def sources(dataset_id: str, digest: str = Depends(token_hash),
                conn: sqlite3.Connection = Depends(connection)):
        return list_sources(conn, digest, dataset_id)

    @app.post('/api/datasets/{dataset_id}/authorization-uploads')
    async def stage_authorizations(dataset_id: str, request: Request,
                                   expected_version: int = Header(alias='X-Expected-Version', ge=1),
                                   filename: str = Header(alias='X-Source-Filename'),
                                   digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                raise Problem(413, 'JSON demasiado grande para esta importación local')
            chunks.append(chunk)
        result, created = stage_authorization(conn, root, digest, dataset_id, expected_version, filename, b''.join(chunks))
        return JSONResponse(result, status_code=201 if created else 200)

    @app.get('/api/datasets/{dataset_id}/authorization-captures')
    def authorization_captures(dataset_id: str, digest: str = Depends(token_hash),
                                conn: sqlite3.Connection = Depends(connection)):
        return authorization_inventory(conn, digest, dataset_id)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/category-history')
    def category_versions(dataset_id:str,batch_id:str,source_row:int,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from .practice_requests import category_history
        return category_history(conn,digest,dataset_id,batch_id,source_row)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/category-history/{ordinal}/file')
    def category_file(dataset_id:str,batch_id:str,source_row:int,ordinal:int,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from urllib.parse import quote
        from .practice_requests import history_file
        filename,content=history_file(conn,root,digest,dataset_id,batch_id,source_row,ordinal)
        return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/practice-requests',status_code=201)
    def request_practice(dataset_id:str,batch_id:str,source_row:int,body:PracticeRequestBody,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from .practice_requests import create
        return create(conn,digest,dataset_id,batch_id,source_row,**body.model_dump())

    @app.get('/api/datasets/{dataset_id}/practice-requests')
    def requests_for_dataset(dataset_id:str,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from .practice_requests import listing
        return listing(conn,digest,dataset_id)

    @app.post('/api/datasets/{dataset_id}/practice-requests/{identity}/answer')
    def answer_request(dataset_id:str,identity:str,body:PracticeAnswerBody,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from .practice_requests import answer
        return answer(conn,digest,dataset_id,identity,**body.model_dump())

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/display-category',status_code=201)
    async def register_category(dataset_id:str,batch_id:str,source_row:int,request:Request,
                                version:int=Header(alias='X-Dataset-Version'),revision:int=Header(alias='X-Revision-Version'),
                                code:str=Header(alias='X-Practice-Code'),family:str=Header(alias='X-Family'),
                                sheet:str=Header(alias='X-Sheet'),evidence_row:int=Header(alias='X-Evidence-Row'),
                                previous:int|None=Header(default=None,alias='X-Category-Version'),
                                reason:str|None=Header(default=None,alias='X-Correction-Reason'),
                                evidence_column:int=Header(alias='X-Evidence-Column'),filename:str=Header(alias='X-Source-Filename'),digest:str=Depends(token_hash),
                                conn:sqlite3.Connection=Depends(connection)):
        from urllib.parse import unquote
        from .display_categories import save_category
        from .service import authorized_dataset,check_version
        _,dataset=authorized_dataset(conn,digest,dataset_id,'reviewer')
        check_version(dataset,version)
        content=bytearray()
        async for chunk in request.stream():
            if len(content)+len(chunk)>MAX_SOURCE_BYTES:raise Problem(413,'El nomenclador supera el tamaño permitido.')
            content.extend(chunk)
        return save_category(conn,root,digest,dataset_id,batch_id,source_row,version=version,revision=revision,
                             code=unquote(code),family=family,sheet=unquote(sheet),evidence_row=evidence_row,
                             evidence_column=evidence_column,filename=unquote(filename),content=bytes(content),
                             previous=previous,reason=unquote(reason) if reason else None)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/practice-search')
    def search_practices(dataset_id: str, batch_id: str, body: PracticeSearchBody,
                         digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        # Search text stays out of URLs and access logs. This endpoint never writes business data.
        return practice_search(conn, digest, dataset_id, batch_id, body.model_dump(exclude_none=True), root=root,projection=board_projection)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/practice-detail')
    def get_practice_detail(dataset_id: str, batch_id: str, source_row: int,
                            digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return practice_detail(conn, digest, dataset_id, batch_id, source_row)

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/authorization-scope')
    def get_authorization_scope(dataset_id: str, batch_id: str, digest: str = Depends(token_hash),
                                conn: sqlite3.Connection = Depends(connection)):
        return scope_history(conn, root, digest, dataset_id, batch_id)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/authorization-scope')
    def select_authorization_scope(dataset_id: str, batch_id: str, body: AuthorizationScopeBody,
                                   digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return save_scope(conn, root, digest, dataset_id, batch_id, **body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/authorization-correspondence')
    def get_authorization_correspondence(dataset_id: str, batch_id: str, source_row: int,
                                         digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return correspondence(conn, root, digest, dataset_id, batch_id, source_row)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/incorporation-group')
    def record_incorporation(dataset_id:str,batch_id:str,body:IncorporationGroupBody,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from .csv_actions import record_group
        return record_group(conn,root,digest,dataset_id,batch_id,**body.model_dump())

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/verified-assignment')
    def verify_assignment(dataset_id:str,batch_id:str,source_row:int,body:CsvAssignmentBody,digest:str=Depends(token_hash),conn:sqlite3.Connection=Depends(connection)):
        from .csv_actions import reassign
        return reassign(conn,root,digest,dataset_id,batch_id,source_row,**body.model_dump())

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/csv-coverage-review',status_code=201)
    def acknowledge_csv(dataset_id: str, batch_id: str, source_row: int, body: CsvReviewBody,
                        digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .csv_reviews import acknowledge
        return acknowledge(conn,root,digest,dataset_id,batch_id,source_row,**body.model_dump())

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/authorization-link')
    def review_authorization_link(dataset_id: str, batch_id: str, source_row: int, body: AuthorizationLinkBody,
                                  digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return save_link(conn, root, digest, dataset_id, batch_id, source_row, **body.model_dump())

    @app.get('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/authorization-check-preview')
    def get_authorization_check_preview(dataset_id: str, batch_id: str, source_row: int,
                                        digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return authorization_check_preview(conn, root, digest, dataset_id, batch_id, source_row)

    @app.post('/api/datasets/{dataset_id}/batches/{batch_id}/rows/{source_row}/authorization-input')
    def declare_authorization_input(dataset_id: str, batch_id: str, source_row: int, body: AuthorizationInputBody,
                                     digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return save_authorization_input(conn, root, digest, dataset_id, batch_id, source_row, **body.model_dump())

    @app.get('/api/datasets/{dataset_id}/authorization-uploads/{upload_id}/preview')
    def authorization_preview(dataset_id: str, upload_id: str, digest: str = Depends(token_hash),
                               conn: sqlite3.Connection = Depends(connection)):
        return preview_authorization(conn, root, digest, dataset_id, upload_id)

    @app.post('/api/datasets/{dataset_id}/authorization-uploads/{upload_id}/import')
    def import_authorizations(dataset_id: str, upload_id: str, body: AuthorizationImportBody,
                                digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        result, created = confirm_authorization(conn, root, digest, dataset_id, upload_id,
                                                body.expected_version, body.preview_sha256, body.provenance_note,
                                                reinterpret_capture_id=body.reinterpret_capture_id)
        return JSONResponse(result, status_code=201 if created else 200)

    @app.get('/api/datasets/{dataset_id}/authorization-uploads/{upload_id}/file')
    def download_authorizations(dataset_id: str, upload_id: str, digest: str = Depends(token_hash),
                                  conn: sqlite3.Connection = Depends(connection)):
        content, sha = authorization_original(conn, root, digest, dataset_id, upload_id)
        return Response(content=content, media_type='application/json',
                         headers={'X-Content-SHA256': sha, 'Content-Disposition': 'attachment; filename="authorization-original.json"'})

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/documentary-assessments", status_code=201)
    def post_documentary_assessment(dataset_id: str, source_id: str, body: DocumentaryAssessmentBody,
                                    digest: str = Depends(token_hash),
                                    conn: sqlite3.Connection = Depends(connection)):
        return save_documentary_assessment(conn, root, digest, dataset_id, source_id, **body.model_dump())

    @app.get("/api/datasets/{dataset_id}/sources/{source_id}/documentary-assessments")
    def get_documentary_assessments(dataset_id: str, source_id: str, provider: str,
                                    code: str, tariff_seq: int,
                                    digest: str = Depends(token_hash),
                                    conn: sqlite3.Connection = Depends(connection)):
        return documentary_history(conn, root, digest, dataset_id, source_id, provider, code, tariff_seq)

    @app.get("/api/datasets/{dataset_id}/sources/{source_id}/value-candidates")
    def value_candidates(dataset_id: str, source_id: str, code: str,
                         performed_on: str | None = None, provider: str | None = None,
                         digest: str = Depends(token_hash),
                         conn: sqlite3.Connection = Depends(connection)):
        return candidate_values(conn, root, digest, dataset_id, source_id,
                                code, performed_on, provider)

    from . import agreement_declarations as declarations

    @app.get("/api/datasets/{dataset_id}/sources/{source_id}/agreement-declarations")
    def agreement_history(dataset_id: str, source_id: str, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return declarations.history(conn,digest,dataset_id,source_id)

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/agreement-declarations/preview")
    def agreement_preview(dataset_id: str, source_id: str, body: AgreementDeclarationBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return declarations.preview(conn,root,digest,dataset_id,source_id,**body.model_dump())

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/agreement-declarations", status_code=201)
    def agreement_save(dataset_id: str, source_id: str, body: AgreementDeclarationSaveBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return declarations.save(conn,root,digest,dataset_id,source_id,**body.model_dump())

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/agreement-declarations/{declaration_id}/withdraw")
    def agreement_withdraw(dataset_id: str, source_id: str, declaration_id: str, body: AgreementWithdrawalBody, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return declarations.withdraw(conn,digest,dataset_id,source_id,declaration_id,**body.model_dump())

    @app.get("/api/datasets/{dataset_id}/sources/{source_id}/hpc-values/{tariff_seq}")
    def hpc_values_history(dataset_id: str, source_id: str, tariff_seq: int,
                           digest: str = Depends(token_hash),
                           conn: sqlite3.Connection = Depends(connection)):
        return value_history(conn, root, digest, dataset_id, source_id, tariff_seq)

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/hpc-values", status_code=201)
    def record_hpc_value(dataset_id: str, source_id: str, body: HpcValueBody,
                         digest: str = Depends(token_hash),
                         conn: sqlite3.Connection = Depends(connection)):
        return save_value_version(conn, root, digest, dataset_id, source_id, **body.model_dump())

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/hpc-status", status_code=201)
    def record_hpc_status(dataset_id: str, source_id: str, body: HpcStatusBody,
                          digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return save_status(conn, root, digest, dataset_id, source_id, **body.model_dump())

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/hpc-percentage/preview")
    def preview_hpc_percentage(dataset_id: str, source_id: str, body: HpcPercentageBody,
                               digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return preview_percentage(conn, root, digest, dataset_id, source_id, **body.model_dump())

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/hpc-percentage/apply", status_code=201)
    def apply_hpc_percentage(dataset_id: str, source_id: str, body: HpcPercentageApplyBody,
                             digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return apply_percentage(conn, root, digest, dataset_id, source_id, **body.model_dump())

    @app.get("/api/datasets/{dataset_id}/sources/{source_id}/code-correspondences")
    def code_pairs(dataset_id: str, source_id: str, digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .code_correspondences import listing
        return listing(conn, root, digest, dataset_id, source_id)

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/code-correspondences", status_code=201)
    def confirm_code_pairs(dataset_id: str, source_id: str, body: CodeCorrespondenceBody,
                           digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        from .code_correspondences import save
        return save(conn, root, digest, dataset_id, source_id, **body.model_dump())

    @app.get("/api/datasets/{dataset_id}/sources/{source_id}/local-hpc")
    def local_hpc_listing(dataset_id: str, source_id: str, query: str | None = None,
                          digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return list_local_hpc(conn,digest,dataset_id,source_id,query)

    @app.post("/api/datasets/{dataset_id}/sources/{source_id}/local-hpc", status_code=201)
    def record_local_hpc(dataset_id: str, source_id: str, body: LocalHpcBody,
                         digest: str = Depends(token_hash), conn: sqlite3.Connection = Depends(connection)):
        return save_local_hpc(conn,root,digest,dataset_id,source_id,**body.model_dump())

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/hpc-comparison")
    def hpc_comparison(dataset_id: str, batch_id: str, source_id: str,
                       status: str = "all", offset: int = 0, limit: int = 50,
                       source_row: int | None = None,
                       digest: str = Depends(token_hash),
                       conn: sqlite3.Connection = Depends(connection)):
        return compare_batch(conn, root, digest, dataset_id, batch_id, source_id,
                             status=status, offset=offset, limit=limit, source_row=source_row)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/reference-readiness")
    def hpc_reference_readiness(dataset_id: str, batch_id: str, source_id: str,
                                status: str = "differences", offset: int = 0,
                                limit: int = 50, source_row: int | None = None,
                                digest: str = Depends(token_hash),
                                conn: sqlite3.Connection = Depends(connection)):
        return reference_readiness(conn, root, digest, dataset_id, batch_id, source_id,
                                   status=status, offset=offset, limit=limit,
                                   source_row=source_row)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}")
    def get_batch(dataset_id: str, batch_id: str, digest: str = Depends(token_hash),
                  conn: sqlite3.Connection = Depends(connection)):
        return batch_metadata(conn, digest, dataset_id, batch_id)

    @app.get("/api/datasets/{dataset_id}/batches/{batch_id}/file")
    def download_batch(dataset_id: str, batch_id: str, digest: str = Depends(token_hash),
                       conn: sqlite3.Connection = Depends(connection)):
        content, sha256 = batch_content(conn, root, digest, dataset_id, batch_id)
        return Response(content=content, media_type="application/octet-stream",
                        headers={"X-Content-SHA256": sha256})

    return app


app = create_app()
