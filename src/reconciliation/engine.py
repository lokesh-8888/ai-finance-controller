"""Multi-pass deterministic reconciliation engine coordinating Stage 1 & Stage 2."""

import time
from typing import List, Optional

from src.domain.models import (
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
)
from src.reconciliation.exact_matcher import ExactMatcher
from src.reconciliation.batch_solver import BatchSolver
from src.reconciliation.results import (
    BatchReconciliationOutput,
    ReconciliationMatch,
    ReconciliationMetrics,
)
from src.reconciliation.state_manager import ReconciliationStateManager


class ReconciliationEngine:
    """Orchestrates deterministic multi-pass financial reconciliation.

    Execution Flow:
    1. Ingestion & atomic bijective state initialization.
    2. Pass 1 (Stage 1): O(1) multi-key exact reference and amount matching.
    3. Pass 2 (Stage 2): Net-of-fee card settlement and combinatorial subset-sum batch solving.
    4. Residual Pool Packaging: Routes remaining un-reconciled items to exception queue for AI investigation.
    5. Metrics computation: throughput, deterministic match rate, and timing.
    """

    def __init__(
        self,
        date_tolerance_days: int = 5,
        max_subset_size: int = 6,
    ):
        self.date_tolerance_days = date_tolerance_days
        self.max_subset_size = max_subset_size

    def reconcile(
        self,
        bank_lines: List[BankStatementLine],
        gateway_txs: List[GatewayTransaction],
        erp_entries: List[ERPLedgerEntry],
        ap_invoices: List[APInvoice],
    ) -> BatchReconciliationOutput:
        """Run full deterministic reconciliation pipeline on supplied multi-source data."""
        start_time = time.perf_counter()

        # Step 1: Initialize atomic bijective state
        state = ReconciliationStateManager(
            bank_lines=bank_lines,
            gateway_txs=gateway_txs,
            erp_entries=erp_entries,
            ap_invoices=ap_invoices,
        )

        all_matches: List[ReconciliationMatch] = []

        # Step 2: Stage 1 - Exact 1:1 Matcher
        exact_matcher = ExactMatcher(state_manager=state)
        stage1_matches = exact_matcher.reconcile()
        all_matches.extend(stage1_matches)

        # Step 3: Stage 2 - Batch Solver & Fee Calculator
        batch_solver = BatchSolver(
            state_manager=state,
            date_tolerance_days=self.date_tolerance_days,
            max_subset_size=self.max_subset_size,
        )
        stage2_matches = batch_solver.reconcile()
        all_matches.extend(stage2_matches)

        # Step 4: Extract Residual Unmatched Pool (for Stage 3 AI Investigator)
        residual = state.get_unmatched_pool()

        # Step 5: Compute Metrics & Execution Profiling
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        total_records = len(bank_lines) + len(gateway_txs) + len(erp_entries) + len(ap_invoices)
        locked_entities = state.get_locked_count()
        residual_count = (
            len(residual["bank_lines"])
            + len(residual["gateway_txs"])
            + len(residual["erp_entries"])
            + len(residual["ap_invoices"])
        )

        match_rate = (locked_entities / total_records * 100.0) if total_records > 0 else 0.0

        metrics = ReconciliationMetrics(
            total_bank_lines=len(bank_lines),
            total_gateway_txs=len(gateway_txs),
            total_erp_entries=len(erp_entries),
            total_ap_invoices=len(ap_invoices),
            stage1_exact_matches=len(stage1_matches),
            stage2_batch_matches=len(stage2_matches),
            total_matched_entities=locked_entities,
            residual_unmatched_count=residual_count,
            deterministic_match_rate_pct=round(match_rate, 2),
            execution_time_ms=round(duration_ms, 2),
        )

        return BatchReconciliationOutput(
            matches=all_matches,
            residual_unmatched=residual,
            metrics=metrics,
        )
