"""Unit and invariant test suite for Phase 1: Deterministic Engine & Combinatorial Solver."""

import datetime as dt
import time
from pathlib import Path
import pytest

from src.domain.models import (
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
    ScenarioType,
)
from src.ingestion.normalizer import (
    load_json_as_dicts,
)
from src.reconciliation.fee_calculator import GatewayFeeCalculator
from src.reconciliation.state_manager import ReconciliationStateManager
from src.reconciliation.exact_matcher import ExactMatcher
from src.reconciliation.batch_solver import BatchSolver
from src.reconciliation.engine import ReconciliationEngine


class TestBijectiveStateLocking:
    """Validate bijective atomic set locking and zero phantom assignments."""

    def test_atomic_pair_locking_and_duplicate_rejection(self):
        """Locking (A, B) succeeds; subsequent attempt to lock (A, C) or (D, B) is rejected."""
        manager = ReconciliationStateManager()

        # Initial pair lock must succeed
        assert manager.lock_pair("BNK-001", "GTW-001", rule="TEST_RULE") is True
        assert manager.is_locked("BNK-001") is True
        assert manager.is_locked("GTW-001") is True

        # Attempting to lock either party again with a different partner must FAIL
        assert manager.lock_pair("BNK-001", "GTW-002") is False
        assert manager.lock_pair("BNK-002", "GTW-001") is False

        # Independent pair lock must succeed
        assert manager.lock_pair("BNK-002", "GTW-002") is True
        assert manager.get_locked_count() == 4

    def test_atomic_group_locking(self):
        """Locking an anchor with multiple members succeeds only if all are free."""
        manager = ReconciliationStateManager()

        # Successful group lock (1:3)
        assert manager.lock_group("BNK-WIRE-01", ["GTW-10", "GTW-11", "GTW-12"]) is True
        assert manager.is_locked("BNK-WIRE-01") is True
        assert manager.is_locked("GTW-10") is True

        # If any member is already locked, entire group lock must fail
        assert manager.lock_group("BNK-WIRE-02", ["GTW-12", "GTW-13"]) is False
        # Unlocked member GTW-13 remains free
        assert manager.is_locked("GTW-13") is False

    def test_unmatched_pool_filtration(self):
        """Unlocked residual pool correctly excludes locked records."""
        b1 = BankStatementLine(id="B1", date=dt.date(2026, 8, 1), amount_cents=1000, raw_description="Dep", account_id="A1")
        b2 = BankStatementLine(id="B2", date=dt.date(2026, 8, 2), amount_cents=2000, raw_description="Dep", account_id="A1")

        manager = ReconciliationStateManager(bank_lines=[b1, b2])
        assert len(manager.get_unmatched_pool()["bank_lines"]) == 2

        manager.lock_pair("B1", "OTHER")
        unmatched = manager.get_unmatched_pool()["bank_lines"]
        assert len(unmatched) == 1
        assert unmatched[0].id == "B2"


class TestGatewayFeeCalculator:
    """Validate mathematical fee calculations and merchant bracket limits."""

    def test_standard_stripe_fee_formula(self):
        """Standard Stripe pricing: 2.9% + $0.30 (30 cents)."""
        # Gross $100.00 -> 10000 * 0.029 = 290 + 30 = 320 cents ($3.20)
        assert GatewayFeeCalculator.calculate_stripe_fee(10000) == 320

        # Gross $500.00 -> 50000 * 0.029 = 1450 + 30 = 1480 cents ($14.80)
        assert GatewayFeeCalculator.calculate_stripe_fee(50000) == 1480

        # Gross $0 or negative -> 0
        assert GatewayFeeCalculator.calculate_stripe_fee(0) == 0

    def test_net_settlement_validation(self):
        """Validates Bank Deposit == Gross - Fee within fee brackets."""
        gross = 100000  # $1,000.00
        expected_fee = GatewayFeeCalculator.calculate_stripe_fee(gross)  # 2930 cents ($29.30)
        net_deposit = gross - expected_fee  # 97070 cents ($970.70)

        # Exact Stripe match
        is_valid, fee, expl = GatewayFeeCalculator.validate_net_settlement(gross, net_deposit)
        assert is_valid is True
        assert fee == expected_fee
        assert "standard Stripe fee" in expl

        # Discrepancy outside merchant brackets is rejected
        is_valid_bad, _, _ = GatewayFeeCalculator.validate_net_settlement(gross, 80000)  # $200 fee on $1000 is 20%!
        assert is_valid_bad is False

        # Non-positive variance is rejected
        is_valid_zero, _, _ = GatewayFeeCalculator.validate_net_settlement(gross, gross)
        assert is_valid_zero is False


class TestCombinatorialSubsetSumSolver:
    """Validate bounded subset-sum search with early branch pruning."""

    def test_subset_sum_solution_found(self):
        """Resolves 1 deposit to 3 ERP invoices matching the exact sum."""
        manager = ReconciliationStateManager()
        solver = BatchSolver(state_manager=manager, max_subset_size=4)

        candidates = [
            {"id": "E1", "amount_cents": 15000},
            {"id": "E2", "amount_cents": 25000},
            {"id": "E3", "amount_cents": 60000},
            {"id": "E4", "amount_cents": 40000},
        ]
        target = 100000  # 15000 + 25000 + 60000 = 100000

        solution = solver._solve_subset_sum(
            target=target,
            candidates=candidates,
            get_val=lambda x: x["amount_cents"],
            max_k=4,
        )

        assert solution is not None
        assert len(solution) == 3
        assert sum(s["amount_cents"] for s in solution) == target

    def test_subset_sum_no_solution(self):
        """Returns None when no subset can form the target."""
        manager = ReconciliationStateManager()
        solver = BatchSolver(state_manager=manager)

        candidates = [
            {"id": "E1", "amount_cents": 1000},
            {"id": "E2", "amount_cents": 2000},
        ]
        target = 50000

        solution = solver._solve_subset_sum(
            target=target,
            candidates=candidates,
            get_val=lambda x: x["amount_cents"],
        )
        assert solution is None


class TestReconciliationThroughputBenchmark:
    """Validate engine throughput exceeds 2,000 records/sec."""

    def test_throughput_benchmark_2000_records(self):
        """Engine processes > 2,000 synthetic records in < 1 second."""
        bank_lines = []
        gateway_txs = []
        erp_entries = []

        base_dt = dt.date(2026, 8, 1)

        # Generate 1,000 1:1 pairs (3,000 records total across Bank, Gateway, ERP)
        for i in range(1000):
            order_id = f"ORD-BENCH-{i:05d}"
            amt = 10000 + (i * 10)

            bank_lines.append(BankStatementLine(
                id=f"BNK-B-{i:05d}",
                date=base_dt,
                amount_cents=amt,
                raw_description=f"DEPOSIT {order_id}",
                reference_code=order_id,
                account_id="ACCT-01"
            ))
            gateway_txs.append(GatewayTransaction(
                id=f"GTW-B-{i:05d}",
                order_id=order_id,
                gross_amount_cents=amt,
                fee_cents=0,
                tax_cents=0,
                net_amount_cents=amt,
                status="succeeded"
            ))
            erp_entries.append(ERPLedgerEntry(
                id=f"GL-B-{i:05d}",
                invoice_id=order_id,
                gl_account_code="1010-CASH",
                amount_cents=amt,
                customer_vendor_name=f"Customer {i}",
                entry_date=base_dt,
                doc_type="PAYMENT"
            ))

        engine = ReconciliationEngine()
        output = engine.reconcile(
            bank_lines=bank_lines,
            gateway_txs=gateway_txs,
            erp_entries=erp_entries,
            ap_invoices=[],
        )

        total_records = len(bank_lines) + len(gateway_txs) + len(erp_entries)
        time_sec = output.metrics.execution_time_ms / 1000.0
        throughput = total_records / time_sec if time_sec > 0 else 999999

        assert output.metrics.stage1_exact_matches == 1000
        assert throughput > 2000, f"Throughput was {throughput:.1f} rec/sec, expected > 2,000"
        assert output.metrics.execution_time_ms < 1000, f"Execution took {output.metrics.execution_time_ms} ms"


class TestCanonicalDatasetReconciliation:
    """Validate full multi-pass engine on Phase 0 benchmark canonical fixtures."""

    @pytest.fixture(scope="class")
    def canonical_data(self):
        project_root = Path(__file__).resolve().parent.parent
        canonical_dir = project_root / "data" / "canonical"

        bnk_items = load_json_as_dicts(canonical_dir / "bank_statement_lines.json")
        gtw_items = load_json_as_dicts(canonical_dir / "gateway_transactions.json")
        erp_items = load_json_as_dicts(canonical_dir / "erp_ledger_entries.json")
        inv_items = load_json_as_dicts(canonical_dir / "ap_invoices.json")

        return {
            "bank_lines": [BankStatementLine(**b) for b in bnk_items],
            "gateway_txs": [GatewayTransaction(**g) for g in gtw_items],
            "erp_entries": [ERPLedgerEntry(**e) for e in erp_items],
            "ap_invoices": [APInvoice(**i) for i in inv_items],
        }

    def test_canonical_reconciliation_end_to_end(self, canonical_data):
        """Reconciles canonical fixtures: verifies Stage 1 & Stage 2 matching and residual queue."""
        engine = ReconciliationEngine(date_tolerance_days=5)
        output = engine.reconcile(
            bank_lines=canonical_data["bank_lines"],
            gateway_txs=canonical_data["gateway_txs"],
            erp_entries=canonical_data["erp_entries"],
            ap_invoices=canonical_data["ap_invoices"],
        )

        metrics = output.metrics

        # 1. Total records
        assert metrics.total_bank_lines == len(canonical_data["bank_lines"])
        assert metrics.total_gateway_txs == len(canonical_data["gateway_txs"])
        assert metrics.total_erp_entries == len(canonical_data["erp_entries"])
        assert metrics.total_ap_invoices == len(canonical_data["ap_invoices"])

        # 2. Stage 1 should resolve exact customer receipts, vendor disbursements, and alias matches
        assert metrics.stage1_exact_matches >= 100, (
            f"Expected >= 100 Stage 1 exact matches, got {metrics.stage1_exact_matches}"
        )

        # 3. Stage 2 should resolve Stripe fee batches and clustered wire bundles
        assert metrics.stage2_batch_matches >= 30, (
            f"Expected >= 30 Stage 2 batch matches, got {metrics.stage2_batch_matches}"
        )

        # 4. Total matches should be >= 130
        assert len(output.matches) >= 130

        # 5. Residual pool must contain the seeded honest anomalies
        residual = output.residual_unmatched
        assert len(residual["bank_lines"]) > 0, "Expected residual bank anomalies"
        assert len(residual["gateway_txs"]) > 0, "Expected residual gateway anomalies"
        assert len(residual["erp_entries"]) > 0, "Expected residual ERP anomalies"
        assert len(residual["ap_invoices"]) > 0, "Expected residual AP anomalies"

        # 6. Check every match has valid audit evidence
        for match in output.matches:
            assert len(match.evidence) > 0
            assert match.confidence_score >= 0.95
            if match.scenario_type == ScenarioType.EXACT_MATCH:
                assert match.confidence_score == 1.0
                assert match.variance_cents == 0
            elif match.scenario_type == ScenarioType.FEE_DIFFERENCE:
                assert match.confidence_score == 0.98
                assert match.variance_cents > 0
