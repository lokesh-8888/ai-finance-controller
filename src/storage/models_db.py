"""Database models, enums, schemas, and double-entry invariants for financial storage."""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from src.domain.models import RiskPriority, ScenarioType


class ExceptionStatus(str, Enum):
    """Operational lifecycle status of an un-reconciled financial exception."""
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ActorType(str, Enum):
    """Originator of a reconciliation state change or remediation."""
    AI_AGENT = "AI_AGENT"
    HUMAN_CONTROLLER = "HUMAN_CONTROLLER"
    SYSTEM = "SYSTEM"


class RemediationActionType(str, Enum):
    """Available 1-click human controller actions."""
    APPROVE_VARIANCE = "APPROVE_VARIANCE"
    POST_GL_ENTRY = "POST_GL_ENTRY"
    FILE_DISPUTE = "FILE_DISPUTE"
    WRITE_OFF = "WRITE_OFF"


class UnbalancedJournalEntryError(ValueError):
    """Raised when an attempted journal entry violates sum(Debits) == sum(Credits)."""
    pass


class StorageError(Exception):
    """Raised on database integrity, hash mismatch, or storage execution failures."""
    pass


class JournalEntryLine(BaseModel):
    """Individual debit or credit posting leg in integer cents."""
    model_config = ConfigDict(validate_assignment=True)

    account: str = Field(..., description="GL Account name or account number (e.g. 1010-Operating Cash)")
    debit_cents: StrictInt = Field(default=0, ge=0, description="Debit amount in integer cents")
    credit_cents: StrictInt = Field(default=0, ge=0, description="Credit amount in integer cents")


class CompensatingJournalEntry(BaseModel):
    """Compensating double-entry ledger record strictly validating sum(Debits) == sum(Credits)."""
    model_config = ConfigDict(validate_assignment=True)

    entry_id: str = Field(..., description="Unique journal voucher reference (e.g. JV-2026-0001)")
    exception_id: str = Field(..., description="Reference to target exception ID")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC creation timestamp"
    )
    lines: List[JournalEntryLine] = Field(..., min_length=2, description="At least two legs for double-entry")
    memo: str = Field(..., description="Audit rationale and business justification")
    created_by: str = Field(default="HUMAN_CONTROLLER", description="Actor who authorized the entry")

    @model_validator(mode="after")
    def validate_double_entry_equality(self) -> "CompensatingJournalEntry":
        total_debits = sum(line.debit_cents for line in self.lines)
        total_credits = sum(line.credit_cents for line in self.lines)

        if total_debits == 0 and total_credits == 0:
            raise UnbalancedJournalEntryError("Journal entry cannot have zero total debits and credits.")

        if total_debits != total_credits:
            raise UnbalancedJournalEntryError(
                f"Double-entry balance violation: Total Debits ({total_debits} cents) "
                f"!= Total Credits ({total_credits} cents). Variance: {total_debits - total_credits} cents."
            )
        return self

    def __init__(self, **data):
        from pydantic import ValidationError
        try:
            super().__init__(**data)
        except ValidationError as e:
            for err in e.errors():
                msg = err.get("msg", "")
                if "Double-entry balance violation" in msg or "cannot have zero total debits" in msg:
                    raise UnbalancedJournalEntryError(msg) from e
            raise

    @classmethod
    def create_simple(
        cls,
        entry_id: str,
        exception_id: str,
        debit_account: str,
        credit_account: str,
        amount_cents: int,
        memo: str,
        created_by: str = "HUMAN_CONTROLLER",
    ) -> "CompensatingJournalEntry":
        """Convenience factory for standard 2-leg balancing compensating entries."""
        if amount_cents <= 0:
            raise UnbalancedJournalEntryError("Journal entry amount must be strictly positive integer cents.")

        lines = [
            JournalEntryLine(account=debit_account, debit_cents=amount_cents, credit_cents=0),
            JournalEntryLine(account=credit_account, debit_cents=0, credit_cents=amount_cents),
        ]
        return cls(
            entry_id=entry_id,
            exception_id=exception_id,
            lines=lines,
            memo=memo,
            created_by=created_by,
        )


class AuditLogRecord(BaseModel):
    """Cryptographically chained immutable audit log entry."""
    model_config = ConfigDict(validate_assignment=True)

    id: Optional[int] = None
    timestamp: str
    event_type: str
    actor: str
    record_id: str
    before_state: Optional[str] = None
    after_state: str
    rationale: str
    hash_signature: str
    prev_hash: str


class RemediationRecord(BaseModel):
    """Historical record of human controller intervention and decision."""
    model_config = ConfigDict(validate_assignment=True)

    remediation_id: str
    exception_id: str
    action_type: RemediationActionType
    actor: str
    timestamp: str
    parameters_json: str
    notes: str


class ExceptionRecord(BaseModel):
    """Operational exception record persisted in SQLite."""
    model_config = ConfigDict(validate_assignment=True)

    exception_id: str
    scenario_type: ScenarioType
    priority: RiskPriority
    amount_cents: StrictInt
    status: ExceptionStatus
    details_json: str
    created_at: str
    updated_at: str
