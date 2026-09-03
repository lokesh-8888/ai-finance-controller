"""Unit, invariant, and tamper-detection tests for Phase 3: Risk Prioritizer, Workbench & Audit Trail."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import pytest

from src.agent.schemas import RecommendedAction
from src.domain.models import RiskPriority, ScenarioType
from src.operations.risk_prioritizer import OperationalRiskPrioritizer
from src.operations.workbench import RemediationWorkbench
from src.storage.audit_trail import AuditTrailService, GENESIS_HASH
from src.storage.database import DatabaseManager
from src.storage.models_db import (
    CompensatingJournalEntry,
    ExceptionStatus,
    JournalEntryLine,
    RemediationActionType,
    UnbalancedJournalEntryError,
)


class TestOperationalRiskPrioritization:
    """Validate P0-P4 risk categorization and integer-cents financial exposure calculation."""

    def test_p0_critical_for_large_unbooked_wire(self):
        """Unbooked wire of $15,000 (> $10k threshold) triggers P0_CRITICAL."""
        res = OperationalRiskPrioritizer.prioritize(
            exception_id="EX-P0-01",
            record_id="BNK-0055",
            scenario_type=ScenarioType.UNEXPLAINED_MISMATCH,
            amount_cents=1500000,
            memo="WIRE INWARD REF 883921 PRIVATE UNIDENTIFIED",
            recommended_action=RecommendedAction.ESCALATE_FRAUD,
        )
        assert res.priority == RiskPriority.P0_CRITICAL
        assert res.financial_exposure_cents == 1500000
        assert "P0 Critical" in res.rationale

    def test_p1_high_for_duplicate_disbursement(self):
        """Duplicate cash disbursement of $1,750 triggers P1_HIGH."""
        res = OperationalRiskPrioritizer.prioritize(
            exception_id="EX-P1-01",
            record_id="BNK-0052",
            scenario_type=ScenarioType.DUPLICATE,
            amount_cents=-175000,
            memo="ACH DEBIT FIGMA DESIGN (DUPLICATE POSTING)",
        )
        assert res.priority == RiskPriority.P1_HIGH
        assert res.financial_exposure_cents == 175000

    def test_p1_high_for_aged_missing_settlement(self):
        """Missing settlement aged 6 days (>= T+5) triggers P1_HIGH."""
        res = OperationalRiskPrioritizer.prioritize(
            exception_id="EX-P1-02",
            record_id="GTW-0040",
            scenario_type=ScenarioType.MISSING_SETTLEMENT,
            amount_cents=145000,
            age_days=6,
        )
        assert res.priority == RiskPriority.P1_HIGH

    def test_p2_medium_for_sales_tax_variance(self):
        """8.25% state sales tax difference triggers P2_MEDIUM."""
        res = OperationalRiskPrioritizer.prioritize(
            exception_id="EX-P2-01",
            record_id="BNK-0058",
            scenario_type=ScenarioType.TAX_DIFFERENCE,
            amount_cents=8250,
            memo="STATE SALES TAX 8.25% WITHHELD",
        )
        assert res.priority == RiskPriority.P2_MEDIUM
        assert res.financial_exposure_cents == 8250

    def test_p4_normal_for_timing_difference(self):
        """T+2 cross-month reporting cutoff triggers P4_NORMAL."""
        res = OperationalRiskPrioritizer.prioritize(
            exception_id="EX-P4-01",
            record_id="BNK-0059",
            scenario_type=ScenarioType.TIMING_DIFFERENCE,
            amount_cents=350000,
            memo="CROSS-MONTH SETTLEMENT AUG-SEP",
        )
        assert res.priority == RiskPriority.P4_NORMAL

    def test_risk_exposure_summary_aggregation(self):
        """Exposure summary correctly sums integer cents across risk tiers."""
        e1 = OperationalRiskPrioritizer.prioritize("E1", "R1", ScenarioType.UNEXPLAINED_MISMATCH, 1500000, memo="UNIDENTIFIED")
        e2 = OperationalRiskPrioritizer.prioritize("E2", "R2", ScenarioType.DUPLICATE, 200000)
        e3 = OperationalRiskPrioritizer.prioritize("E3", "R3", ScenarioType.TAX_DIFFERENCE, 8250)
        e4 = OperationalRiskPrioritizer.prioritize("E4", "R4", ScenarioType.TIMING_DIFFERENCE, 50000)

        summary = OperationalRiskPrioritizer.compute_exposure_summary([e1, e2, e3, e4])

        assert summary.total_exceptions == 4
        assert summary.total_exposure_cents == 1500000 + 200000 + 8250 + 50000
        assert summary.p0_critical_count == 1
        assert summary.p0_critical_exposure_cents == 1500000
        assert summary.p1_high_count == 1
        assert summary.p1_high_exposure_cents == 200000
        assert summary.p2_medium_count == 1
        assert summary.p2_medium_exposure_cents == 8250
        assert summary.p4_normal_count == 1
        assert summary.p4_normal_exposure_cents == 50000


class TestDoubleEntryLedgerInvariant:
    """Validate strict enforcement of sum(Debits) == sum(Credits)."""

    def test_balanced_simple_entry_succeeds(self):
        """Standard 2-leg balanced entry initializes cleanly."""
        entry = CompensatingJournalEntry.create_simple(
            entry_id="JV-2026-0001",
            exception_id="EX-01",
            debit_account="6010-Processing Fees",
            credit_account="1010-Cash",
            amount_cents=2930,
            memo="Stripe gateway fee reconciliation",
        )
        assert sum(l.debit_cents for l in entry.lines) == 2930
        assert sum(l.credit_cents for l in entry.lines) == 2930

    def test_unbalanced_entry_raises_error(self):
        """Attempting an unbalanced journal entry raises UnbalancedJournalEntryError."""
        with pytest.raises(UnbalancedJournalEntryError) as exc_info:
            CompensatingJournalEntry(
                entry_id="JV-BAD-01",
                exception_id="EX-02",
                lines=[
                    JournalEntryLine(account="Cash", debit_cents=5000, credit_cents=0),
                    JournalEntryLine(account="Expense", debit_cents=0, credit_cents=4500),
                ],
                memo="Unbalanced entry test",
            )
        assert "Double-entry balance violation" in str(exc_info.value)

    def test_zero_or_negative_amount_raises_error(self):
        """Non-positive journal entry amounts are strictly rejected."""
        with pytest.raises(UnbalancedJournalEntryError):
            CompensatingJournalEntry.create_simple(
                entry_id="JV-BAD-02",
                exception_id="EX-03",
                debit_account="Cash",
                credit_account="Expense",
                amount_cents=0,
                memo="Zero amount",
            )


class TestRemediationWorkbenchActions:
    """Test all 4 human controller 1-click remediation actions with atomic audit persistence."""

    @pytest.fixture
    def workbench(self):
        db = DatabaseManager(":memory:")
        return RemediationWorkbench(db)

    def test_action_1_approve_variance(self, workbench):
        """Approving variance updates status to RESOLVED and logs audit event."""
        workbench.register_exception(
            exception_id="EX-TEST-01",
            scenario_type=ScenarioType.FEE_DIFFERENCE,
            priority=RiskPriority.P4_NORMAL,
            amount_cents=320,
        )

        res = workbench.approve_variance(
            exception_id="EX-TEST-01",
            reason="Allowable Stripe card processing fee variation within 0.05% tolerance",
        )

        assert res.success is True
        assert res.new_status == ExceptionStatus.RESOLVED
        assert res.action_type == RemediationActionType.APPROVE_VARIANCE
        assert res.audit_log_id > 0

        # Verify audit trail
        with workbench.db.get_connection() as conn:
            logs = AuditTrailService.get_history_for_record(conn, "EX-TEST-01")
            assert len(logs) == 2  # EXCEPTION_REGISTERED + APPROVE_VARIANCE
            assert logs[-1].event_type == "APPROVE_VARIANCE"
            assert "Allowable Stripe" in logs[-1].rationale

    def test_action_2_post_compensating_gl_entry(self, workbench):
        """Posting compensating GL creates a balanced ledger row and resolves exception."""
        workbench.register_exception(
            exception_id="EX-TEST-02",
            scenario_type=ScenarioType.TAX_DIFFERENCE,
            priority=RiskPriority.P2_MEDIUM,
            amount_cents=8250,
        )

        res = workbench.post_compensating_gl_entry(
            exception_id="EX-TEST-02",
            debit_account="2200-Sales Tax Payable",
            credit_account="1100-AR Clearing",
            amount_cents=8250,
            memo="Reclassify state sales tax deduction",
        )

        assert res.success is True
        assert res.new_status == ExceptionStatus.RESOLVED
        assert res.journal_entry_id is not None

        # Verify journal entry in database
        with workbench.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM journal_entries WHERE entry_id = ?;", (res.journal_entry_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["debit_amount_cents"] == 8250
            assert row["credit_amount_cents"] == 8250

    def test_action_3_file_dispute(self, workbench):
        """Filing a dispute marks record DISPUTED and creates a dispute ticket."""
        workbench.register_exception(
            exception_id="EX-TEST-03",
            scenario_type=ScenarioType.UNEXPLAINED_MISMATCH,
            priority=RiskPriority.P0_CRITICAL,
            amount_cents=12450,
        )

        res = workbench.file_dispute(
            exception_id="EX-TEST-03",
            dispute_reason="Customer charge disputed with Stripe - settlement shortage of $124.50",
        )

        assert res.success is True
        assert res.new_status == ExceptionStatus.DISPUTED
        assert res.dispute_ticket_id.startswith("DISP-")

        with workbench.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM exceptions WHERE exception_id = 'EX-TEST-03';")
            assert cursor.fetchone()["status"] == ExceptionStatus.DISPUTED.value

    def test_action_4_write_off_uncollectible(self, workbench):
        """Writing off uncollectible creates bad debt expense entry and marks WRITTEN_OFF."""
        workbench.register_exception(
            exception_id="EX-TEST-04",
            scenario_type=ScenarioType.MISSING_SETTLEMENT,
            priority=RiskPriority.P1_HIGH,
            amount_cents=210000,
        )

        res = workbench.write_off_uncollectible(
            exception_id="EX-TEST-04",
            justification="Vendor bankrupt, uncollectible receivable written off to bad debt expense",
        )

        assert res.success is True
        assert res.new_status == ExceptionStatus.WRITTEN_OFF

        with workbench.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM journal_entries WHERE exception_id = 'EX-TEST-04';")
            je = cursor.fetchone()
            assert je["debit_account"] == "6050-Bad Debt Expense"
            assert je["credit_account"] == "1100-Accounts Receivable Clearing"
            assert je["debit_amount_cents"] == 210000


class TestSQLiteAuditTrailAndTamperDetection:
    """Verify cryptographic SHA-256 hash chaining, integrity verification, and WAL mode."""

    def test_genesis_hash_and_hash_chaining(self):
        """Each audit log entry links cryptographically to the preceding entry's hash."""
        db = DatabaseManager(":memory:")
        with db.get_connection() as conn:
            e1 = AuditTrailService.log_event(conn, "TEST_E1", "ACTOR1", "REC-1", {"v": 1}, "Rationale 1")
            e2 = AuditTrailService.log_event(conn, "TEST_E2", "ACTOR2", "REC-2", {"v": 2}, "Rationale 2")
            e3 = AuditTrailService.log_event(conn, "TEST_E3", "ACTOR3", "REC-3", {"v": 3}, "Rationale 3")

            assert e1.prev_hash == GENESIS_HASH
            assert e2.prev_hash == e1.hash_signature
            assert e3.prev_hash == e2.hash_signature

            # Chain verification passes
            valid, err = AuditTrailService.verify_chain_integrity(conn)
            assert valid is True
            assert err is None

    def test_tamper_detection_on_modified_record(self):
        """Modifying an audit record payload in SQLite breaks cryptographic verification."""
        db = DatabaseManager(":memory:")
        with db.get_connection() as conn:
            AuditTrailService.log_event(conn, "EVENT_A", "ACTOR", "REC-1", {"status": "OPEN"}, "Init")
            AuditTrailService.log_event(conn, "EVENT_B", "ACTOR", "REC-1", {"status": "RESOLVED"}, "Approve")

            # Verify initially valid
            valid, _ = AuditTrailService.verify_chain_integrity(conn)
            assert valid is True

            # Adversarial tamper: modify row 2 after_state directly in SQLite
            cursor = conn.cursor()
            cursor.execute("UPDATE audit_logs SET after_state = '{\"status\": \"HACKED\"}' WHERE id = 2;")
            cursor.close()

            # Verification must fail with tamper alert
            valid, err = AuditTrailService.verify_chain_integrity(conn)
            assert valid is False
            assert "Tamper detected at record ID 2" in str(err)

    def test_concurrent_multithreaded_audit_writes(self, tmp_path):
        """WAL mode allows concurrent threads to write audit records safely without database locks."""
        db_file = tmp_path / "concurrent_wal.db"
        db = DatabaseManager(db_file)

        def write_audit(worker_idx: int):
            with db.get_connection() as conn:
                AuditTrailService.log_event(
                    conn=conn,
                    event_type=f"CONCURRENT_OP_{worker_idx}",
                    actor=f"WORKER_{worker_idx}",
                    record_id=f"REC-WORKER-{worker_idx}",
                    after_state={"worker": worker_idx},
                    rationale=f"Worker {worker_idx} concurrent task execution",
                )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write_audit, range(30)))

        # Verify all 30 records were written and cryptographic chain holds
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM audit_logs;")
            assert cursor.fetchone()["cnt"] == 30

            valid, err = AuditTrailService.verify_chain_integrity(conn)
            assert valid is True, f"Integrity check failed: {err}"
