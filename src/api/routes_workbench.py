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


class PostGLEntryRequest(BaseModel):
    exception_id: str
    debit_account: str
    credit_account: str
    amount_cents: int = Field(..., gt=0)
    memo: str


class FileDisputeRequest(BaseModel):
    exception_id: str
    dispute_reason: str


class WriteOffRequest(BaseModel):
    exception_id: str
    justification: str


@router.post("/approve-variance", response_model=RemediationResult)
def approve_variance(req: ApproveVarianceRequest):
    """Approve fee/tax variance and transition exception to RESOLVED."""
    try:
        # Auto-register if not yet in SQLite
        _ensure_exception_registered(req.exception_id)
        return workbench.approve_variance(exception_id=req.exception_id, reason=req.reason)
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
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/file-dispute", response_model=RemediationResult)
def file_dispute(req: FileDisputeRequest):
    """Mark exception DISPUTED, lock from auto-matching, and create dispute ticket."""
    try:
        _ensure_exception_registered(req.exception_id)
        return workbench.file_dispute(exception_id=req.exception_id, dispute_reason=req.dispute_reason)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/write-off", response_model=RemediationResult)
def write_off(req: WriteOffRequest):
    """Write off uncollectible to bad debt expense and mark WRITTEN_OFF."""
    try:
        _ensure_exception_registered(req.exception_id)
        return workbench.write_off_uncollectible(exception_id=req.exception_id, justification=req.justification)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
