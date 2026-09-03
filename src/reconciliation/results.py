"""Reconciliation data transfer objects, audit evidence schemas, and metric collectors."""

from typing import Any, Dict, List
from pydantic import BaseModel, ConfigDict, Field

from src.domain.models import ScenarioType


class ReconciliationMatch(BaseModel):
    """Represents a validated reconciliation match with an audit evidence chain."""
    model_config = ConfigDict(validate_assignment=True)

    match_id: str = Field(..., description="Unique match identifier (e.g. MATCH-0001)")
    scenario_type: ScenarioType = Field(..., description="Taxonomy classification for the match")
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Deterministic confidence level (1.0 for exact, 0.98 for fees, 0.95 for batches)"
    )
    bank_line_ids: List[str] = Field(default_factory=list, description="Associated BankStatementLine IDs")
    gateway_tx_ids: List[str] = Field(default_factory=list, description="Associated GatewayTransaction IDs")
    erp_entry_ids: List[str] = Field(default_factory=list, description="Associated ERPLedgerEntry IDs")
    invoice_ids: List[str] = Field(default_factory=list, description="Associated APInvoice IDs")
    matched_amount_cents: int = Field(..., description="Reconciled nominal amount in integer cents")
    variance_cents: int = Field(default=0, description="Mathematical variance in integer cents (e.g. fees)")
    rule_name: str = Field(..., description="Matching rule/stage that created this match")
    evidence: List[str] = Field(default_factory=list, description="Step-by-step deterministic audit trail")


class ReconciliationMetrics(BaseModel):
    """Aggregate execution metrics for reconciliation stages."""
    model_config = ConfigDict(validate_assignment=True)

    total_bank_lines: int = Field(default=0)
    total_gateway_txs: int = Field(default=0)
    total_erp_entries: int = Field(default=0)
    total_ap_invoices: int = Field(default=0)
    stage1_exact_matches: int = Field(default=0)
    stage2_batch_matches: int = Field(default=0)
    total_matched_entities: int = Field(default=0)
    residual_unmatched_count: int = Field(default=0)
    deterministic_match_rate_pct: float = Field(default=0.0)
    execution_time_ms: float = Field(default=0.0)


class BatchReconciliationOutput(BaseModel):
    """Comprehensive output bundle returned by the reconciliation engine."""
    model_config = ConfigDict(validate_assignment=True)

    matches: List[ReconciliationMatch] = Field(default_factory=list)
    residual_unmatched: Dict[str, List[Any]] = Field(default_factory=dict)
    metrics: ReconciliationMetrics = Field(default_factory=ReconciliationMetrics)
