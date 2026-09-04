"""1-Click human controller remediation endpoints with atomic double-entry persistence."""

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.domain.models import RiskPriority, ScenarioType
from src.operations.workbench import RemediationResult, RemediationWorkbench
from src.storage.audit_trail import AuditTrailService
from src.storage.database import DatabaseManager

router = APIRouter(prefix="/api/v1/workbench", tags=["Remediation Workbench"])
db_manager = DatabaseManager()
workbench = RemediationWorkbench(db_manager)


class ApproveVarianceRequest(BaseModel):
    exception_id: str
    reason: str
    actor: str = "HUMAN_CONTROLLER"


class PostGLEntryRequest(BaseModel):
    exception_id: str
    debit_account: str
    credit_account: str
    amount_cents: int = Field(..., gt=0)
    memo: str
    actor: str = "HUMAN_CONTROLLER"


class FileDisputeRequest(BaseModel):
    exception_id: str
    dispute_reason: str
    actor: str = "HUMAN_CONTROLLER"


class WriteOffRequest(BaseModel):
    exception_id: str
    justification: str
    actor: str = "HUMAN_CONTROLLER"


class LogAuditEventRequest(BaseModel):
    event_type: str
    actor: str = "AI_INVESTIGATOR"
    record_id: str
    rationale: str
    after_state: Dict[str, Any] = Field(default_factory=dict)
    before_state: Dict[str, Any] = Field(default_factory=dict)


@router.post("/approve-variance", response_model=RemediationResult)
def approve_variance(req: ApproveVarianceRequest):
    """Approve fee/tax variance and transition exception to RESOLVED."""
    try:
        # Auto-register if not yet in SQLite
        _ensure_exception_registered(req.exception_id)
        return workbench.approve_variance(exception_id=req.exception_id, reason=req.reason, actor=req.actor)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/post-gl-entry", response_model=RemediationResult)
def post_gl_entry(req: PostGLEntryRequest):
    """Post balanced compensating double-entry journal entry to clear unreconciled balances."""
    try:
        _ensure_exception_registered(req.exception_id, amount_cents=req.amount_cents)
        return workbench.post_compensating_gl_entry(
            exception_id=req.exception_id,
            debit_account=req.debit_account,
            credit_account=req.credit_account,
            amount_cents=req.amount_cents,
            memo=req.memo,
            actor=req.actor,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/file-dispute", response_model=RemediationResult)
def file_dispute(req: FileDisputeRequest):
    """Mark exception DISPUTED, lock from auto-matching, and create dispute ticket."""
    try:
        _ensure_exception_registered(req.exception_id)
        return workbench.file_dispute(exception_id=req.exception_id, dispute_reason=req.dispute_reason, actor=req.actor)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/write-off", response_model=RemediationResult)
def write_off(req: WriteOffRequest):
    """Write off uncollectible to bad debt expense and mark WRITTEN_OFF."""
    try:
        _ensure_exception_registered(req.exception_id)
        return workbench.write_off_uncollectible(exception_id=req.exception_id, justification=req.justification, actor=req.actor)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/log-event")
def log_custom_audit_event(req: LogAuditEventRequest) -> Dict[str, Any]:
    """Log an immutable cryptographic audit event with SHA-256 chain verification."""
    try:
        with db_manager.get_connection() as conn:
            rec = AuditTrailService.log_event(
                conn=conn,
                event_type=req.event_type,
                actor=req.actor,
                record_id=req.record_id,
                before_state=req.before_state,
                after_state=req.after_state,
                rationale=req.rationale,
            )
            return rec.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit-trail/stats/counts")
def get_audit_trail_counts() -> Dict[str, int]:
    """Retrieve counts of audit events grouped by actor category (all, human, ai, system)."""
    with db_manager.get_connection() as conn:
        AuditTrailService.seed_ai_audit_events_if_needed(conn)
        return AuditTrailService.get_actor_counts(conn)


@router.get("/audit-trail")
def list_all_audit_trail(actor: str = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve all recent immutable cryptographic audit trail events, optionally filtered by actor."""
    with db_manager.get_connection() as conn:
        AuditTrailService.seed_ai_audit_events_if_needed(conn)
        records = AuditTrailService.get_all_records(conn, limit=limit, actor_category=actor)
        return [r.model_dump() for r in records]


@router.post("/audit-trail/reset")
def reset_audit_trail_endpoint() -> Dict[str, Any]:
    """Reset the audit trail to a clean verified cryptographic baseline."""
    with db_manager.get_connection() as conn:
        count = AuditTrailService.reset_audit_trail_to_clean_state(conn)
        return {
            "success": True,
            "message": f"Audit trail reset to clean baseline with {count} verified cryptographically chained blocks.",
            "total_blocks": count,
        }


@router.get("/audit-trail/{record_id}")
def get_audit_trail(record_id: str) -> List[Dict[str, Any]]:
    """Retrieve immutable cryptographic audit trail for a financial record ID."""
    with db_manager.get_connection() as conn:
        records = AuditTrailService.get_history_for_record(conn, record_id)
        return [r.model_dump() for r in records]


def _ensure_exception_registered(exception_id: str, amount_cents: int = 10000):
    """Helper to ensure an exception row exists in SQLite before remediation."""
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT exception_id FROM exceptions WHERE exception_id = ?;", (exception_id,))
        if not cursor.fetchone():
            workbench.register_exception(
                exception_id=exception_id,
                scenario_type=ScenarioType.UNEXPLAINED_MISMATCH,
                priority=RiskPriority.P1_HIGH,
                amount_cents=amount_cents,
            )
        cursor.close()
