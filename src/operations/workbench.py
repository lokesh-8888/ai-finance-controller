"""Human-in-the-loop 1-click remediation workbench with atomic double-entry ledger persistence."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from src.domain.models import RiskPriority, ScenarioType
from src.ingestion.normalizer import cents_to_display
from src.storage.audit_trail import AuditTrailService
from src.storage.database import DatabaseManager
from src.storage.models_db import (
    CompensatingJournalEntry,
    ExceptionRecord,
    ExceptionStatus,
    RemediationActionType,
    StorageError,
    UnbalancedJournalEntryError,
)


class RemediationResult(BaseModel):
    """Result of an executed 1-click human controller action."""
    model_config = ConfigDict(validate_assignment=True)

    success: bool
    action_type: RemediationActionType
    exception_id: str
    new_status: ExceptionStatus
    audit_log_id: int
    journal_entry_id: Optional[str] = None
    dispute_ticket_id: Optional[str] = None
    message: str


class RemediationWorkbench:
    """Provides 1-click remediation actions for financial exceptions with atomic audit logging."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()

    def register_exception(
        self,
        exception_id: str,
        scenario_type: ScenarioType,
        priority: RiskPriority,
        amount_cents: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> ExceptionRecord:
        """Register or update an un-reconciled exception in the operational database."""
        now_utc = datetime.now(timezone.utc).isoformat()
        details_str = json.dumps(details or {}, sort_keys=True)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO exceptions (
                    exception_id, scenario_type, priority, amount_cents,
                    status, details_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exception_id) DO UPDATE SET
                    scenario_type = excluded.scenario_type,
                    priority = excluded.priority,
                    amount_cents = excluded.amount_cents,
                    details_json = excluded.details_json,
                    updated_at = excluded.updated_at;
                """,
                (
                    exception_id,
                    scenario_type.value,
                    priority.value,
                    amount_cents,
                    ExceptionStatus.OPEN.value,
                    details_str,
                    now_utc,
                    now_utc,
                )
            )
            cursor.close()

            AuditTrailService.log_event(
                conn=conn,
                event_type="EXCEPTION_REGISTERED",
                actor="SYSTEM",
                record_id=exception_id,
                after_state={"status": ExceptionStatus.OPEN.value, "priority": priority.value},
                rationale=f"Registered {scenario_type.value} exception ({cents_to_display(amount_cents)})",
            )

        return ExceptionRecord(
            exception_id=exception_id,
            scenario_type=scenario_type,
            priority=priority,
            amount_cents=amount_cents,
            status=ExceptionStatus.OPEN,
            details_json=details_str,
            created_at=now_utc,
            updated_at=now_utc,
        )

    def approve_variance(
        self,
        exception_id: str,
        reason: str,
        actor: str = "HUMAN_CONTROLLER",
    ) -> RemediationResult:
        """Action 1: Approve allowable fee/tax variance and mark as resolved."""
        now_utc = datetime.now(timezone.utc).isoformat()
        rem_id = f"REM-APP-{uuid.uuid4().hex[:8].upper()}"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM exceptions WHERE exception_id = ?;", (exception_id,))
            row = cursor.fetchone()
            if not row:
                raise StorageError(f"Exception ID '{exception_id}' not found.")

            before_state = {"status": row["status"]}

            # 1. Update exception status
            cursor.execute(
                "UPDATE exceptions SET status = ?, updated_at = ? WHERE exception_id = ?;",
                (ExceptionStatus.RESOLVED.value, now_utc, exception_id)
            )

            # 2. Record remediation decision
            params = json.dumps({"reason": reason}, sort_keys=True)
            cursor.execute(
                """
                INSERT INTO remediation_records (
                    remediation_id, exception_id, action_type, actor, timestamp, parameters_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (rem_id, exception_id, RemediationActionType.APPROVE_VARIANCE.value, actor, now_utc, params, reason)
            )

            # 3. Log cryptographic audit entry
            audit_record = AuditTrailService.log_event(
                conn=conn,
                event_type="APPROVE_VARIANCE",
                actor=actor,
                record_id=exception_id,
                before_state=before_state,
                after_state={"status": ExceptionStatus.RESOLVED.value},
                rationale=reason,
            )
            cursor.close()

        return RemediationResult(
            success=True,
            action_type=RemediationActionType.APPROVE_VARIANCE,
            exception_id=exception_id,
            new_status=ExceptionStatus.RESOLVED,
            audit_log_id=audit_record.id or 0,
            message=f"Variance approved for '{exception_id}': {reason}",
        )

    def post_compensating_gl_entry(
        self,
        exception_id: str,
        debit_account: str,
        credit_account: str,
        amount_cents: int,
        memo: str,
        actor: str = "HUMAN_CONTROLLER",
    ) -> RemediationResult:
        """Action 2: Post balanced double-entry compensating entry to clear unreconciled balances."""
        entry_id = f"JV-{datetime.now().year}-{uuid.uuid4().hex[:6].upper()}"
        rem_id = f"REM-GL-{uuid.uuid4().hex[:8].upper()}"
        now_utc = datetime.now(timezone.utc).isoformat()

        # Enforce double-entry invariant (raises UnbalancedJournalEntryError if unbalanced)
        journal_entry = CompensatingJournalEntry.create_simple(
            entry_id=entry_id,
            exception_id=exception_id,
            debit_account=debit_account,
            credit_account=credit_account,
            amount_cents=amount_cents,
            memo=memo,
            created_by=actor,
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM exceptions WHERE exception_id = ?;", (exception_id,))
            row = cursor.fetchone()
            if not row:
                raise StorageError(f"Exception ID '{exception_id}' not found.")

            before_state = {"status": row["status"]}

            # 1. Insert compensating double-entry ledger row
            cursor.execute(
                """
                INSERT INTO journal_entries (
                    entry_id, exception_id, timestamp, debit_account, credit_account,
                    debit_amount_cents, credit_amount_cents, memo, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    entry_id,
                    exception_id,
                    now_utc,
                    debit_account,
                    credit_account,
                    amount_cents,
                    amount_cents,
                    memo,
                    actor,
                )
            )

            # 2. Update exception status to RESOLVED
            cursor.execute(
                "UPDATE exceptions SET status = ?, updated_at = ? WHERE exception_id = ?;",
                (ExceptionStatus.RESOLVED.value, now_utc, exception_id)
            )

            # 3. Record remediation decision
            params = json.dumps(
                {
                    "journal_entry_id": entry_id,
                    "debit_account": debit_account,
                    "credit_account": credit_account,
                    "amount_cents": amount_cents,
                },
                sort_keys=True
            )
            cursor.execute(
                """
                INSERT INTO remediation_records (
                    remediation_id, exception_id, action_type, actor, timestamp, parameters_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (rem_id, exception_id, RemediationActionType.POST_GL_ENTRY.value, actor, now_utc, params, memo)
            )

            # 4. Log cryptographic audit entry
            audit_record = AuditTrailService.log_event(
                conn=conn,
                event_type="POST_GL_ENTRY",
                actor=actor,
                record_id=exception_id,
                before_state=before_state,
                after_state={
                    "status": ExceptionStatus.RESOLVED.value,
                    "journal_entry_id": entry_id,
                    "amount_cents": amount_cents,
                },
                rationale=memo,
            )
            cursor.close()

        return RemediationResult(
            success=True,
            action_type=RemediationActionType.POST_GL_ENTRY,
            exception_id=exception_id,
            new_status=ExceptionStatus.RESOLVED,
            audit_log_id=audit_record.id or 0,
            journal_entry_id=entry_id,
            message=f"Compensating entry {entry_id} posted ({cents_to_display(amount_cents)}): {memo}",
        )

    def file_dispute(
        self,
        exception_id: str,
        dispute_reason: str,
        actor: str = "HUMAN_CONTROLLER",
    ) -> RemediationResult:
        """Action 3: Mark transaction disputed, lock from auto-matching, and create dispute ticket."""
        ticket_id = f"DISP-{datetime.now().year}-{uuid.uuid4().hex[:6].upper()}"
        rem_id = f"REM-DISP-{uuid.uuid4().hex[:8].upper()}"
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM exceptions WHERE exception_id = ?;", (exception_id,))
            row = cursor.fetchone()
            if not row:
                raise StorageError(f"Exception ID '{exception_id}' not found.")

            before_state = {"status": row["status"]}

            # 1. Update exception status to DISPUTED
            cursor.execute(
                "UPDATE exceptions SET status = ?, updated_at = ? WHERE exception_id = ?;",
                (ExceptionStatus.DISPUTED.value, now_utc, exception_id)
            )

            # 2. Record remediation decision
            params = json.dumps({"ticket_id": ticket_id, "dispute_reason": dispute_reason}, sort_keys=True)
            cursor.execute(
                """
                INSERT INTO remediation_records (
                    remediation_id, exception_id, action_type, actor, timestamp, parameters_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (rem_id, exception_id, RemediationActionType.FILE_DISPUTE.value, actor, now_utc, params, dispute_reason)
            )

            # 3. Log cryptographic audit entry
            audit_record = AuditTrailService.log_event(
                conn=conn,
                event_type="FILE_DISPUTE",
                actor=actor,
                record_id=exception_id,
                before_state=before_state,
                after_state={"status": ExceptionStatus.DISPUTED.value, "ticket_id": ticket_id},
                rationale=dispute_reason,
            )
            cursor.close()

        return RemediationResult(
            success=True,
            action_type=RemediationActionType.FILE_DISPUTE,
            exception_id=exception_id,
            new_status=ExceptionStatus.DISPUTED,
            audit_log_id=audit_record.id or 0,
            dispute_ticket_id=ticket_id,
            message=f"Dispute ticket {ticket_id} opened for '{exception_id}': {dispute_reason}",
        )

    def write_off_uncollectible(
        self,
        exception_id: str,
        justification: str,
        actor: str = "HUMAN_CONTROLLER",
    ) -> RemediationResult:
        """Action 4: Write off orphan receivable or unrecoverable item to bad debt expense."""
        now_utc = datetime.now(timezone.utc).isoformat()
        rem_id = f"REM-WO-{uuid.uuid4().hex[:8].upper()}"
        entry_id = f"JV-WO-{datetime.now().year}-{uuid.uuid4().hex[:6].upper()}"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM exceptions WHERE exception_id = ?;", (exception_id,))
            row = cursor.fetchone()
            if not row:
                raise StorageError(f"Exception ID '{exception_id}' not found.")

            before_state = {"status": row["status"]}
            amt_cents = abs(row["amount_cents"])

            # 1. Post double-entry write-off entry
            # Debit: Bad Debt Expense (6050), Credit: AR / Clearing (1100)
            cursor.execute(
                """
                INSERT INTO journal_entries (
                    entry_id, exception_id, timestamp, debit_account, credit_account,
                    debit_amount_cents, credit_amount_cents, memo, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    entry_id,
                    exception_id,
                    now_utc,
                    "6050-Bad Debt Expense",
                    "1100-Accounts Receivable Clearing",
                    amt_cents,
                    amt_cents,
                    f"Write-off uncollectible: {justification}",
                    actor,
                )
            )

            # 2. Update exception status to WRITTEN_OFF
            cursor.execute(
                "UPDATE exceptions SET status = ?, updated_at = ? WHERE exception_id = ?;",
                (ExceptionStatus.WRITTEN_OFF.value, now_utc, exception_id)
            )

            # 3. Record remediation decision
            params = json.dumps(
                {"journal_entry_id": entry_id, "amount_cents": amt_cents, "justification": justification},
                sort_keys=True
            )
            cursor.execute(
                """
                INSERT INTO remediation_records (
                    remediation_id, exception_id, action_type, actor, timestamp, parameters_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (rem_id, exception_id, RemediationActionType.WRITE_OFF.value, actor, now_utc, params, justification)
            )

            # 4. Log cryptographic audit entry
            audit_record = AuditTrailService.log_event(
                conn=conn,
                event_type="WRITE_OFF",
                actor=actor,
                record_id=exception_id,
                before_state=before_state,
                after_state={
                    "status": ExceptionStatus.WRITTEN_OFF.value,
                    "journal_entry_id": entry_id,
                    "amount_cents": amt_cents,
                },
                rationale=justification,
            )
            cursor.close()

        return RemediationResult(
            success=True,
            action_type=RemediationActionType.WRITE_OFF,
            exception_id=exception_id,
            new_status=ExceptionStatus.WRITTEN_OFF,
            audit_log_id=audit_record.id or 0,
            journal_entry_id=entry_id,
            message=f"Exception '{exception_id}' written off to bad debt ({cents_to_display(amt_cents)}): {justification}",
        )
