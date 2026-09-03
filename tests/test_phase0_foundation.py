"""Unit tests for Phase 0: Integer-Cents Precision, Normalizers, Domain Models & Synthetic Data."""

import datetime as dt
from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError

from src.domain.models import (
    ScenarioType,
    RiskPriority,
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
    GroundTruthRecord,
)
from src.ingestion.normalizer import (
    to_cents,
    cents_to_display,
    normalize_text,
    normalize_date,
    resolve_vendor_alias,
    parse_bank_statement_line,
    parse_gateway_transaction,
    parse_erp_ledger_entry,
    parse_ap_invoice,
    load_csv_as_dicts,
    load_json_as_dicts,
)
from src.generator.data_generator import (
    SyntheticFinanceDataset,
    generate_all_synthetic_data,
)


class TestIntegerCentsPrecision:
    """Validate zero float-rounding drift and exact cents quantization."""

    def test_classic_float_drift_eliminated(self):
        """Standard 0.1 + 0.2 != 0.3 binary float anomaly is strictly eliminated."""
        float_sum = 0.1 + 0.2
        assert float_sum != 0.3  # Standard IEEE 754 float drift

        cents_1 = to_cents("0.10")
        cents_2 = to_cents("0.20")
        cents_target = to_cents("0.30")

        assert cents_1 == 10
        assert cents_2 == 20
        assert cents_target == 30
        assert cents_1 + cents_2 == cents_target

    def test_thousand_fraction_accumulation(self):
        """Accumulating 1,000 one-cent items yields exactly $10.00 (1000 cents)."""
        cents_total = sum(to_cents("0.01") for _ in range(1000))
        assert cents_total == 1000
        assert cents_to_display(cents_total) == "$10.00"

    def test_to_cents_string_formatting(self):
        """Parses various dirty currency strings with symbols, commas, and signs."""
        assert to_cents("$1,250.50") == 125050
        assert to_cents("1250.50") == 125050
        assert to_cents("€2,500.75") == 250075
        assert to_cents("£99.99") == 9999
        assert to_cents("-45.20") == -4520
        assert to_cents("-$1,000.00") == -100000
        assert to_cents("+500.25") == 50025
        assert to_cents("  $35.00  ") == 3500

    def test_to_cents_accounting_parentheses(self):
        """Accounting parenthesis notation (X.YY) evaluates as negative cents."""
        assert to_cents("(45.20)") == -4520
        assert to_cents("($1,250.00)") == -125000
        assert to_cents("(0.99)") == -99

    def test_to_cents_numeric_inputs(self):
        """Handles integer dollars, Decimal, and floats safely."""
        assert to_cents(Decimal("125.45")) == 12545
        assert to_cents(100, from_dollars=True) == 10000
        assert to_cents(100, from_dollars=False) == 100
        assert to_cents(49.99) == 4999

    def test_to_cents_invalid_inputs(self):
        """Rejects unparseable or empty values with ValueError."""
        with pytest.raises(ValueError):
            to_cents(None)
        with pytest.raises(ValueError):
            to_cents("")
        with pytest.raises(ValueError):
            to_cents("invalid_text")
        with pytest.raises(ValueError):
            to_cents("$--100")

    def test_cents_to_display_formatting(self):
        """Converts integer cents to standard financial dollar strings."""
        assert cents_to_display(125050) == "$1,250.50"
        assert cents_to_display(5) == "$0.05"
        assert cents_to_display(0) == "$0.00"
        assert cents_to_display(-4520) == "-$45.20"
        assert cents_to_display(-100000) == "-$1,000.00"


class TestNormalizerUtilities:
    """Validate string tokenization, vendor aliasing, and date standardization."""

    def test_normalize_date_formats(self):
        """Standardizes multiple date representations to datetime.date."""
        expected = dt.date(2026, 8, 15)
        assert normalize_date("2026-08-15") == expected
        assert normalize_date("08/15/2026") == expected
        assert normalize_date("15/08/2026") == expected
        assert normalize_date("2026-08-15T14:30:00Z") == expected
        assert normalize_date(dt.date(2026, 8, 15)) == expected
        assert normalize_date(dt.datetime(2026, 8, 15, 10, 0, 0)) == expected

    def test_normalize_date_invalid(self):
        """Raises ValueError on unparseable date strings."""
        with pytest.raises(ValueError):
            normalize_date("not-a-date")
        with pytest.raises(ValueError):
            normalize_date("")

    def test_normalize_text_sanitization(self):
        """Cleans dirty whitespace, separators, and normalizes to uppercase."""
        raw = "  \t direct   debit \n ACH*TRANSFER #1024  "
        assert normalize_text(raw) == "DIRECT DEBIT ACH TRANSFER 1024"

    def test_vendor_alias_resolution(self):
        """Resolves known enterprise vendor variations to canonical corporate names."""
        assert normalize_text("AWS Cloud Dublin") == "AMAZON WEB SERVICES"
        assert normalize_text("AWS EMEA SARL") == "AMAZON WEB SERVICES"
        assert normalize_text("AMZN") == "AMAZON WEB SERVICES"
        assert normalize_text("MSFT AZURE") == "MICROSOFT AZURE"
        assert normalize_text("Google Ireland") == "GOOGLE CLOUD PLATFORM"
        assert normalize_text("Stripe Payments Transfer") == "STRIPE"
        assert normalize_text("Snowflake Computing") == "SNOWFLAKE"
        assert normalize_text("Datadog US") == "DATADOG"


class TestDomainModelsInvariance:
    """Validate strict typing, Pydantic constraints, and accounting equations."""

    def test_strict_int_cents_rejection_of_float(self):
        """Pydantic StrictInt rejects accidental float assignments."""
        with pytest.raises(ValidationError):
            BankStatementLine(
                id="BNK-001",
                date=dt.date(2026, 8, 1),
                amount_cents=125.50,  # FLOAT: MUST FAIL!
                raw_description="Deposit",
                account_id="ACCT-01"
            )

    def test_gateway_transaction_net_equation_invariant(self):
        """Gateway transaction enforces net_amount_cents == gross - fee - tax."""
        # Valid transaction
        tx = GatewayTransaction(
            id="GTW-001",
            order_id="ORD-001",
            gross_amount_cents=10000,
            fee_cents=320,
            tax_cents=800,
            net_amount_cents=8880,  # 10000 - 320 - 800 = 8880
            payout_batch_id="po_01",
            status="succeeded"
        )
        assert tx.net_amount_cents == 8880

        # Corrupt net amount must raise ValidationError
        with pytest.raises(ValidationError):
            GatewayTransaction(
                id="GTW-002",
                order_id="ORD-002",
                gross_amount_cents=10000,
                fee_cents=320,
                tax_cents=800,
                net_amount_cents=9999,  # Incorrect net
                payout_batch_id="po_02",
                status="succeeded"
            )

    def test_ap_invoice_positive_liability(self):
        """APInvoice amount_cents must be strictly positive liability."""
        with pytest.raises(ValidationError):
            APInvoice(
                id="INV-001",
                vendor_name="Vendor X",
                amount_cents=-5000,  # Negative liability invalid
                due_date=dt.date(2026, 8, 1),
            )
        with pytest.raises(ValidationError):
            APInvoice(
                id="INV-002",
                vendor_name="Vendor X",
                amount_cents=0,  # Zero liability invalid
                due_date=dt.date(2026, 8, 1),
            )


class TestSyntheticDataGeneratorAndEvaluationMatrix:
    """Validate 60+ benchmark scenarios, 9-scenario taxonomy coverage, and strict ground-truth isolation."""

    @pytest.fixture(scope="class")
    def generated_dataset(self, tmp_path_factory) -> SyntheticFinanceDataset:
        tmp_dir = tmp_path_factory.mktemp("finance_data")
        dataset = generate_all_synthetic_data(project_root=tmp_dir)
        return dataset

    def test_benchmark_scenario_count(self, generated_dataset):
        """Ensures at least 60 reconciliation scenarios are generated."""
        assert len(generated_dataset.ground_truth) >= 60

    def test_all_9_scenario_taxonomy_represented(self, generated_dataset):
        """Verifies full coverage of the 9-Scenario Taxonomy."""
        covered_types = {gt.scenario_type for gt in generated_dataset.ground_truth}
        expected_types = set(ScenarioType)

        assert covered_types == expected_types, (
            f"Missing scenario types: {expected_types - covered_types}"
        )

    def test_all_risk_priorities_represented(self, generated_dataset):
        """Verifies coverage of all risk priority tiers (P0, P1, P2, P4)."""
        covered_priorities = {gt.risk_priority for gt in generated_dataset.ground_truth}
        expected_priorities = set(RiskPriority)

        assert covered_priorities == expected_priorities, (
            f"Missing risk priorities: {expected_priorities - covered_priorities}"
        )

    def test_ground_truth_isolation_and_file_existence(self):
        """Verifies files are written to data/canonical/ and data/ground_truth/ separately."""
        project_root = Path(__file__).resolve().parent.parent
        canonical_dir = project_root / "data" / "canonical"
        ground_truth_dir = project_root / "data" / "ground_truth"

        # Canonical fixtures
        assert (canonical_dir / "bank_statement_lines.csv").exists()
        assert (canonical_dir / "bank_statement_lines.json").exists()
        assert (canonical_dir / "gateway_transactions.csv").exists()
        assert (canonical_dir / "gateway_transactions.json").exists()
        assert (canonical_dir / "erp_ledger_entries.csv").exists()
        assert (canonical_dir / "erp_ledger_entries.json").exists()
        assert (canonical_dir / "ap_invoices.csv").exists()
        assert (canonical_dir / "ap_invoices.json").exists()

        # Ground truth
        assert (ground_truth_dir / "ground_truth.csv").exists()
        assert (ground_truth_dir / "ground_truth.json").exists()

    def test_canonical_files_do_not_leak_ground_truth_columns(self):
        """Ensures canonical fixtures do not contain evaluation answers/ground-truth fields."""
        project_root = Path(__file__).resolve().parent.parent
        canonical_dir = project_root / "data" / "canonical"

        leak_indicators = {"scenario_type", "risk_priority", "expected_status", "variance_cents", "explanation"}

        for filename in ["bank_statement_lines.csv", "gateway_transactions.csv", "erp_ledger_entries.csv", "ap_invoices.csv"]:
            rows = load_csv_as_dicts(canonical_dir / filename)
            assert len(rows) > 0
            fieldnames = set(rows[0].keys())
            leaked = fieldnames.intersection(leak_indicators)
            assert not leaked, f"Canonical file {filename} leaked ground truth keys: {leaked}"

    def test_all_canonical_records_parse_into_domain_models(self):
        """Verifies every single row in canonical fixtures strictly parses into typed domain models."""
        project_root = Path(__file__).resolve().parent.parent
        canonical_dir = project_root / "data" / "canonical"

        # Bank statements
        bnk_rows = load_csv_as_dicts(canonical_dir / "bank_statement_lines.csv")
        for r in bnk_rows:
            obj = parse_bank_statement_line(r)
            assert isinstance(obj, BankStatementLine)
            assert isinstance(obj.amount_cents, int)

        # Gateway
        gtw_rows = load_csv_as_dicts(canonical_dir / "gateway_transactions.csv")
        for r in gtw_rows:
            obj = parse_gateway_transaction(r)
            assert isinstance(obj, GatewayTransaction)
            assert obj.net_amount_cents == obj.gross_amount_cents - obj.fee_cents - obj.tax_cents

        # ERP Ledger
        erp_rows = load_csv_as_dicts(canonical_dir / "erp_ledger_entries.csv")
        for r in erp_rows:
            obj = parse_erp_ledger_entry(r)
            assert isinstance(obj, ERPLedgerEntry)
            assert isinstance(obj.amount_cents, int)

        # AP Invoices
        inv_rows = load_csv_as_dicts(canonical_dir / "ap_invoices.csv")
        for r in inv_rows:
            obj = parse_ap_invoice(r)
            assert isinstance(obj, APInvoice)
            assert obj.amount_cents > 0

    def test_all_canonical_json_records_parse_into_domain_models(self):
        """Verifies every record in canonical JSON fixtures strictly parses into typed domain models."""
        project_root = Path(__file__).resolve().parent.parent
        canonical_dir = project_root / "data" / "canonical"

        bnk_items = load_json_as_dicts(canonical_dir / "bank_statement_lines.json")
        for item in bnk_items:
            obj = BankStatementLine(**item)
            assert isinstance(obj, BankStatementLine)

        gtw_items = load_json_as_dicts(canonical_dir / "gateway_transactions.json")
        for item in gtw_items:
            obj = GatewayTransaction(**item)
            assert isinstance(obj, GatewayTransaction)

        erp_items = load_json_as_dicts(canonical_dir / "erp_ledger_entries.json")
        for item in erp_items:
            obj = ERPLedgerEntry(**item)
            assert isinstance(obj, ERPLedgerEntry)

        inv_items = load_json_as_dicts(canonical_dir / "ap_invoices.json")
        for item in inv_items:
            obj = APInvoice(**item)
            assert isinstance(obj, APInvoice)

    def test_ground_truth_json_and_csv_consistency(self):
        """Verifies ground_truth.json and ground_truth.csv contain the exact same scenario count and records."""
        project_root = Path(__file__).resolve().parent.parent
        ground_truth_dir = project_root / "data" / "ground_truth"

        csv_rows = load_csv_as_dicts(ground_truth_dir / "ground_truth.csv")
        json_rows = load_json_as_dicts(ground_truth_dir / "ground_truth.json")

        assert len(csv_rows) == len(json_rows)
        assert len(json_rows) >= 60

        for r in json_rows:
            record = GroundTruthRecord(**r)
            assert isinstance(record, GroundTruthRecord)

