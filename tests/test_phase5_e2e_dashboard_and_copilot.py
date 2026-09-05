"""Comprehensive End-to-End, API, Copilot, Robustness Benchmark, and Reporting tests for Phase 5."""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from src.api.main import app
from src.copilot.assistant import GroundedFinancialCopilot
from src.evaluation.robustness_benchmark import RobustnessBenchmark
from src.reporting.audit_report import MonthEndAuditReportGenerator


@pytest.fixture
def client():
    """Starlette TestClient fixture for FastAPI endpoints."""
    return TestClient(app)


class TestFastAPIEndpoints:
    """Validate all REST endpoints across Reconcile, Workbench, Forecast, Copilot, and Reports."""

    def test_health_check_endpoint(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"

    def test_ui_root_endpoint_serves_html(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "AI Finance Controller" in res.text
        assert "trajectoryChart" in res.text
        assert "inspectorDrawer" in res.text

    def test_reconciliation_kpis_endpoint(self, client):
        res = client.get("/api/v1/reconcile/kpis")
        assert res.status_code == 200
        data = res.json()
        assert data["total_scenarios"] == 200
        assert data["deterministic_match_rate_pct"] >= 75.0
        assert data["ai_recovery_rate_pct"] >= 10.0
        assert data["final_accuracy_pct"] >= 95.0
        assert data["p0_exceptions_count"] >= 2
        assert data["p0_exposure_cents"] > 0

    def test_transaction_stream_and_filtering(self, client):
        # All records
        res_all = client.get("/api/v1/reconcile/records?status=ALL")
        assert res_all.status_code == 200
        records = res_all.json()
        assert len(records) == 200

        # Matched filter
        res_matched = client.get("/api/v1/reconcile/records?status=MATCHED")
        assert res_matched.status_code == 200
        matched = res_matched.json()
        assert len(matched) > 0

        # Exceptions filter
        res_exceptions = client.get("/api/v1/reconcile/records?status=EXCEPTIONS")
        assert res_exceptions.status_code == 200
        exceptions = res_exceptions.json()
        assert len(exceptions) > 0

        # Search filter
        res_search = client.get("/api/v1/reconcile/records?search=BNK-0189")
        assert res_search.status_code == 200
        search_results = res_search.json()
        assert len(search_results) >= 1
        assert "8.25% state sales tax" in search_results[0]["explanation"]

    def test_record_forensic_detail_endpoint(self, client):
        res = client.get("/api/v1/reconcile/records/BNK-0189")
        assert res.status_code == 200
        data = res.json()
        assert data["scenario_id"] == "SCEN-ANOM-194"
        assert data["scenario_type"] == "TAX_DIFFERENCE"
        assert len(data["sources"]) >= 1
        assert len(data["rule_trace"]) >= 1

    def test_workbench_remediation_actions(self, client):
        # 1. Approve Variance
        res_app = client.post(
            "/api/v1/workbench/approve-variance",
            json={"exception_id": "API-EX-001", "reason": "Standard gateway interchange delta"},
        )
        assert res_app.status_code == 200
        assert res_app.json()["new_status"] == "RESOLVED"

        # 2. Post Compensating GL Entry
        res_gl = client.post(
            "/api/v1/workbench/post-gl-entry",
            json={
                "exception_id": "API-EX-002",
                "debit_account": "6010-Bank Fees",
                "credit_account": "1010-Operating Cash",
                "amount_cents": 5000,
                "memo": "Compensating fee voucher",
            },
        )
        assert res_gl.status_code == 200
        assert res_gl.json()["new_status"] == "RESOLVED"
        assert "journal_entry_id" in res_gl.json()

        # 3. File Dispute
        res_disp = client.post(
            "/api/v1/workbench/file-dispute",
            json={"exception_id": "API-EX-003", "dispute_reason": "Unrecognized debit"},
        )
        assert res_disp.status_code == 200
        assert res_disp.json()["new_status"] == "DISPUTED"
        assert "dispute_ticket_id" in res_disp.json()

        # 4. Write-off
        res_wo = client.post(
            "/api/v1/workbench/write-off",
            json={"exception_id": "API-EX-004", "justification": "Debtor bankruptcy"},
        )
        assert res_wo.status_code == 200
        assert res_wo.json()["new_status"] == "WRITTEN_OFF"

    def test_forecast_endpoints(self, client):
        # Position
        res_pos = client.get("/api/v1/forecast/position")
        assert res_pos.status_code == 200
        assert res_pos.json()["settled_cash_cents"] > 0

        # Projections
        res_proj = client.get("/api/v1/forecast/projections")
        assert res_proj.status_code == 200
        assert len(res_proj.json()["daily_projections"]) == 30

        # Waterfall
        res_wf = client.get("/api/v1/forecast/waterfall")
        assert res_wf.status_code == 200
        assert res_wf.json()["closing_balance_cents"] > 0

        # Trajectory
        res_tr = client.get("/api/v1/forecast/trajectory")
        assert res_tr.status_code == 200
        assert len(res_tr.json()["dates"]) == 30


class TestGroundedFinancialCopilot:
    """Validate copilot natural language reasoning and grounded data citations."""

    @pytest.fixture
    def copilot(self):
        return GroundedFinancialCopilot()

    def test_copilot_match_rate_overview(self, copilot):
        resp = copilot.query("What is our overall reconciliation match rate?")
        assert resp.intent == "MATCH_RATE_OVERVIEW"
        assert "final reconciliation rate" in resp.answer
        assert resp.key_metrics["deterministic_accuracy_pct"] >= 75.0
        assert resp.key_metrics["post_ai_final_accuracy_pct"] >= 95.0
        assert resp.key_metrics["fraud_false_positive_rate"] == 0.0

    def test_copilot_p0_critical_fraud_query(self, copilot):
        resp = copilot.query("List all P0 critical exceptions and unbooked wires")
        assert resp.intent == "P0_CRITICAL_EXCEPTIONS"
        assert "$15,000.00" in resp.answer
        assert resp.key_metrics["p0_critical_count"] >= 2
        assert resp.key_metrics["total_p0_exposure_cents"] > 0

    def test_copilot_cash_runway_query(self, copilot):
        resp = copilot.query("What is our projected cash runway and 30-day cash position?")
        assert resp.intent == "CASH_RUNWAY_POSITION"
        assert "Adjusted Net Cash" in resp.answer
        assert "runway_months" in resp.key_metrics

    def test_copilot_specific_record_lookup(self, copilot):
        resp = copilot.query("Explain why record BNK-0189 had a variance")
        assert resp.intent == "RECORD_LOOKUP"
        assert "TAX_DIFFERENCE" in resp.answer
        assert "8.25% state sales tax" in resp.answer


class TestRobustnessBenchmarkSuite:
    """Validate multi-seed independent benchmark execution and statistical outputs."""

    def test_robustness_benchmark_3_seeds_execution(self):
        """Execute a 3-seed slice to verify Monte Carlo distribution calculation."""
        report = RobustnessBenchmark.run_benchmark(seeds=[101, 102, 103])
        assert report.total_runs == 3
        assert len(report.runs) == 3

        # Every run achieves high accuracy and 0% fraud FPR
        for run in report.runs:
            assert run.accuracy >= 0.95
            assert run.f1_macro >= 0.95
            assert run.fraud_fpr == 0.0

        assert report.mean_accuracy >= 0.95
        assert report.mean_f1 >= 0.95
        assert report.mean_fraud_fpr == 0.0
        assert report.max_fraud_fpr == 0.0


class TestMonthEndAuditReportGenerator:
    """Validate Month-End Audit Memo export in Markdown, JSON, and CSV."""

    def test_report_generation_and_file_outputs(self, tmp_path):
        generator = MonthEndAuditReportGenerator()
        files = generator.generate(output_dir=tmp_path)

        assert files["markdown"].exists()
        assert files["json"].exists()
        assert files["csv"].exists()

        # Check Markdown content
        md_text = files["markdown"].read_text(encoding="utf-8")
        assert "Executive Month-End Reconciliation Audit Memo" in md_text
        assert "SOX-404 Internal Controls" in md_text
        assert "$15,000.00" in md_text

        # Check CSV content
        csv_text = files["csv"].read_text(encoding="utf-8")
        assert "scenario_id,scenario_type,risk_priority" in csv_text
        assert "SCEN-ANOM-" in csv_text

    def test_audit_trail_api_endpoints_and_actor_filtering(self, client):
        # 1. Test counts endpoint
        res_counts = client.get("/api/v1/workbench/audit-trail/stats/counts")
        assert res_counts.status_code == 200
        counts = res_counts.json()
        assert "all" in counts
        assert "human" in counts
        assert "ai" in counts
        assert "system" in counts
        assert counts["ai"] >= 1

        # 2. Test filtering by actor
        res_ai = client.get("/api/v1/workbench/audit-trail?actor=ai")
        assert res_ai.status_code == 200
        ai_data = res_ai.json()
        assert len(ai_data) > 0
        assert all("AI" in r["actor"] for r in ai_data)

        res_human = client.get("/api/v1/workbench/audit-trail?actor=human")
        assert res_human.status_code == 200
        human_data = res_human.json()
        assert len(human_data) > 0

        # 3. Test log-event endpoint
        res_log = client.post(
            "/api/v1/workbench/log-event",
            json={
                "event_type": "AI_TEST_LOG",
                "actor": "AI_INVESTIGATOR",
                "record_id": "TEST-REC-999",
                "rationale": "Automated verification test",
                "after_state": {"verified": True},
            },
        )
        assert res_log.status_code == 200
        log_data = res_log.json()
        assert log_data["actor"] == "AI_INVESTIGATOR"
        assert log_data["hash_signature"] is not None

    def test_audit_memo_endpoint_markdown_and_json(self, client):
        # 1. Default markdown format
        res_md = client.get("/api/v1/reports/audit-memo")
        assert res_md.status_code == 200
        assert "text/markdown" in res_md.headers.get("content-type", "")
        assert "Executive Month-End Reconciliation Audit Memo" in res_md.text

        # 2. Explicit JSON format
        res_json = client.get("/api/v1/reports/audit-memo?format=json")
        assert res_json.status_code == 200
        data = res_json.json()
        assert "markdown_memo" in data
        assert "benchmark_report" in data
        assert "Executive Month-End Reconciliation Audit Memo" in data["markdown_memo"]


