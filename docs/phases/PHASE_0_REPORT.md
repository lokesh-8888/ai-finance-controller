# Phase 0 Verification Report: Project Foundation, Integer-Cents Domain Models & Ground-Truth Dataset

## 1. Executive Summary

Phase 0 establishes the foundational data architecture, strict monetary domain schemas, multi-source ingestion normalizers, and synthetic benchmark generator for the **AI Finance Controller**.

A primary challenge in enterprise financial automation is **floating-point rounding drift** (e.g., standard IEEE 754 float drift like `0.1 + 0.2 = 0.30000000000000004`), which can cause spurious reconciliation breaks, miscalculated gateway fees, and corrupted trial balances. Phase 0 eliminates this risk by mandating **strict integer-cents arithmetic** across all data structures and computation layers.

Furthermore, Phase 0 decouples the **Canonical Source Datasets** from the **Ground-Truth Evaluation Matrix** to prevent data contamination and ensure zero information leakage during future reconciliation engine testing.

---

## 2. Directory & Repository Architecture

```text
ai-finance-controller/
├── src/
│   ├── domain/                  # Strict financial domain schemas & taxonomy enums
│   │   ├── __init__.py
│   │   └── models.py            # Pydantic v2 integer-cents models & validators
│   ├── ingestion/               # Multi-source parsers, token sanitizers, & converters
│   │   ├── __init__.py
│   │   └── normalizer.py        # Date standardizer, text normalizer, to_cents()
│   └── generator/               # Deterministic synthetic data generator
│       ├── __init__.py
│       └── data_generator.py    # 60-scenario generator & ground truth exporter
├── data/
│   ├── canonical/               # Benchmark fixtures for ingestion (isolated)
│   │   ├── bank_statement_lines.csv / .json
│   │   ├── gateway_transactions.csv / .json
│   │   ├── erp_ledger_entries.csv / .json
│   │   └── ap_invoices.csv / .json
│   └── ground_truth/            # Independent evaluation matrix (zero leakage)
│       ├── ground_truth.csv
│       └── ground_truth.json
├── tests/                       # Pytest test suite
│   ├── __init__.py
│   └── test_phase0_foundation.py # 22 automated test cases (100% passing)
├── docs/phases/
│   └── PHASE_0_REPORT.md        # This phase report
├── requirements.txt
└── README.md
```

---

## 3. Strict Integer-Cents Precision Architecture

### 3.1 Design Rationale
- **Zero Float Representation Drift**: Financial amounts are stored as integers representing cents (`$1,250.50` -> `125050` cents).
- **Decimal Intermediate Quantization**: The `to_cents()` normalizer accepts strings, floats, ints, or Decimals, stripping currency symbols (`$`, `€`, `£`), handling accounting parentheses notation `($45.20)` -> `-4520`, and quantizing using `ROUND_HALF_UP` before casting to `int`.
- **Pydantic `StrictInt` Guard**: All monetary fields (`amount_cents`, `gross_amount_cents`, `fee_cents`, `tax_cents`, `net_amount_cents`, `variance_cents`) are declared as `pydantic.StrictInt`. Attempting to assign floating-point numbers triggers an immediate `ValidationError`.

### 3.2 Gateway Accounting Equation Invariant
The `GatewayTransaction` model enforces the fundamental settlement identity via a model validator:
$$\text{net\_amount\_cents} = \text{gross\_amount\_cents} - \text{fee\_cents} - \text{tax\_cents}$$
Any transaction violating this equation is rejected at ingestion.

---

## 4. Financial Domain Schemas & Taxonomies

### 4.1 Data Source Schemas

| Model | Primary Keys / Refs | Fields | Purpose |
| :--- | :--- | :--- | :--- |
| **`BankStatementLine`** | `id`, `reference_code` | `id`, `date`, `amount_cents`, `raw_description`, `reference_code`, `account_id` | Cleared transactions on commercial bank statement |
| **`GatewayTransaction`**| `id`, `order_id` | `id`, `order_id`, `gross_amount_cents`, `fee_cents`, `tax_cents`, `net_amount_cents`, `payout_batch_id`, `status` | Credit card / Stripe / merchant processor charges & payouts |
| **`ERPLedgerEntry`** | `id`, `invoice_id` | `id`, `invoice_id`, `gl_account_code`, `amount_cents`, `customer_vendor_name`, `entry_date`, `doc_type` | Double-entry journal entries from ERP (NetSuite, SAP) |
| **`APInvoice`** | `id`, `vendor_name` | `id`, `vendor_name`, `amount_cents`, `due_date`, `currency`, `fx_rate`, `status` | Accounts Payable bills received from external suppliers |

### 4.2 The 9-Scenario Reconciliation Taxonomy Enum (`ScenarioType`)
1. **`EXACT_MATCH`**: 1:1 perfect parity between bank statement, gateway charge / AP invoice, and ERP journal entry.
2. **`FEE_DIFFERENCE`**: Discrepancy explained by merchant processing fee deductions (e.g. Stripe $2.9\% + \$0.30$).
3. **`TAX_DIFFERENCE`**: Discrepancy caused by sales tax or VAT withheld by marketplace facilitators.
4. **`REFUND`**: Chargebacks, customer returns, or credit adjustments requiring reverse matching.
5. **`ADJUSTMENT`**: Bank adjustments, fee credits, or manual GL reconciliations.
6. **`TIMING_DIFFERENCE`**: In-flight settlements crossing accounting cutoffs (e.g., weekend T+2 clearing).
7. **`MISSING_SETTLEMENT`**: Captured gateway charge or booked AP bill with no corresponding bank movement.
8. **`DUPLICATE`**: Repeated statement posting or accidental double-booked invoice.
9. **`UNEXPLAINED_MISMATCH`**: Discrepancy with no rule-based explanation requiring human controller escalation.

### 4.3 Risk Priority Tiers (`RiskPriority`)
- **`P0_CRITICAL`**: Unidentified bank deposits, unexplained material cash variances ($> \$100$).
- **`P1_HIGH`**: Duplicate payments, missing settlements, unmapped tax discrepancies.
- **`P2_MEDIUM`**: Merchant fee deductions, bundled batch settlements, cross-period timing differences.
- **`P4_NORMAL`**: Clean 1:1 exact matches, resolved vendor aliases.

---

## 5. Synthetic Benchmark Dataset & Ground Truth Matrix

### 5.1 Cohort Composition (60 Scenarios)
The synthetic generator (`src/generator/data_generator.py`) generates 60 deterministic scenarios across 5 specialized cohorts:

1. **30 Exact Matches (50%)**:
   - 15 Customer Inward Receipts (Gateway -> Bank Deposit -> ERP Cash Receipt)
   - 15 Vendor Outward Disbursements (AP Invoice -> Bank Debit -> ERP AP Payment)
2. **10 Net-of-Fee Stripe Batches (16.7%)**:
   - Gross amounts ($80 to $3,200) reduced by standard card fees ($2.9\% + \$0.30$), producing clean explainable variances.
3. **5 Split / Bundled Batch Wire Deposits (8.3%)**:
   - 1 consolidated bank statement line reconciling to 2–4 individual gateway transactions and ERP revenue entries.
4. **5 FX Currency & Vendor Alias Variants (8.3%)**:
   - Foreign exchange conversions (EUR / GBP -> USD) with currency exchange rates.
   - Normalization of disparate vendor descriptors (e.g. `AWS CLOUD DUBLIN` -> `AMAZON WEB SERVICES`, `MSFT AZURE` -> `MICROSOFT AZURE`).
5. **10 Quarantined Honest Anomalies (16.7%)**:
   - Bank statement duplicate debit (`P1_HIGH`)
   - ERP duplicate invoice booking (`P1_HIGH`)
   - Unsettled gateway capture (`P1_HIGH`)
   - Unpaid booked AP invoice (`P1_HIGH`)
   - Unexplained $124.50 deposit shortage (`P0_CRITICAL`)
   - Unidentified $15,000.00 bank wire (`P0_CRITICAL`)
   - Customer return chargeback matching credit memo (`P2_MEDIUM`)
   - Partial return adjustment (`P2_MEDIUM`)
   - 8.25% state sales tax withholding discrepancy (`P1_HIGH`)
   - Cross-month-end reporting cutoff timing difference (`P2_MEDIUM`)

### 5.2 Generated Dataset Metrics

| Dataset / Table | File Format | Record Count | Location |
| :--- | :--- | :--- | :--- |
| **Bank Statement Lines** | CSV & JSON | **59 records** | `data/canonical/bank_statement_lines.*` |
| **Gateway Transactions** | CSV & JSON | **45 records** | `data/canonical/gateway_transactions.*` |
| **ERP Ledger Entries** | CSV & JSON | **69 records** | `data/canonical/erp_ledger_entries.*` |
| **AP Invoices** | CSV & JSON | **23 records** | `data/canonical/ap_invoices.*` |
| **Total Ingestion Entities** | - | **196 records** | - |
| **Ground Truth Evaluation Matrix** | CSV & JSON | **60 scenarios** | `data/ground_truth/ground_truth.*` |

### 5.3 Anti-Cheating & Ground-Truth Isolation
- Canonical fixtures contain **only** source-native fields (`id`, `date`, `amount_cents`, `raw_description`, etc.).
- The Ground-Truth Matrix resides in an isolated directory (`data/ground_truth/`) containing evaluation keys (`scenario_type`, `risk_priority`, `expected_status`, `variance_cents`, `explanation`).
- Automated tests verify that no ground-truth columns leak into canonical files.

---

## 6. Automated Test Suite Results

The automated test suite (`tests/test_phase0_foundation.py`) exercises the entire foundation across 22 comprehensive test cases.

```text
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-8.3.2, pluggy-1.6.0
rootdir: C:\Users\omglo\.gemini\antigravity-ide\scratch\ai-finance-controller
collected 22 items

tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_classic_float_drift_eliminated PASSED
tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_thousand_fraction_accumulation PASSED
tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_to_cents_string_formatting PASSED
tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_to_cents_accounting_parentheses PASSED
tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_to_cents_numeric_inputs PASSED
tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_to_cents_invalid_inputs PASSED
tests/test_phase0_foundation.py::TestIntegerCentsPrecision::test_cents_to_display_formatting PASSED
tests/test_phase0_foundation.py::TestNormalizerUtilities::test_normalize_date_formats PASSED
tests/test_phase0_foundation.py::TestNormalizerUtilities::test_normalize_date_invalid PASSED
tests/test_phase0_foundation.py::TestNormalizerUtilities::test_normalize_text_sanitization PASSED
tests/test_phase0_foundation.py::TestNormalizerUtilities::test_vendor_alias_resolution PASSED
tests/test_phase0_foundation.py::TestDomainModelsInvariance::test_strict_int_cents_rejection_of_float PASSED
tests/test_phase0_foundation.py::TestDomainModelsInvariance::test_gateway_transaction_net_equation_invariant PASSED
tests/test_phase0_foundation.py::TestDomainModelsInvariance::test_ap_invoice_positive_liability PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_benchmark_scenario_count PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_all_9_scenario_taxonomy_represented PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_all_risk_priorities_represented PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_ground_truth_isolation_and_file_existence PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_canonical_files_do_not_leak_ground_truth_columns PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_all_canonical_records_parse_into_domain_models PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_all_canonical_json_records_parse_into_domain_models PASSED
tests/test_phase0_foundation.py::TestSyntheticDataGeneratorAndEvaluationMatrix::test_ground_truth_json_and_csv_consistency PASSED

============================= 22 passed in 0.33s ==============================
```

---

## 7. Issues Encountered and Resolved

1. **Pydantic Model Field Name Collision (`date: date`)**:
   - *Issue*: Pydantic v2 failed to construct `BankStatementLine` because field name `date` collided with imported type `datetime.date`.
   - *Resolution*: Updated imports to `import datetime as dt` and referenced type annotations as `dt.date`.
2. **Double Negative String Parsing in `to_cents`**:
   - *Issue*: Malformed input `"--100"` was partially stripped, leading to successful conversion instead of raising `ValueError`.
   - *Resolution*: Implemented strict check `if "-" in clean_str or "+" in clean_str:` after stripping the first valid sign, ensuring multiple or misplaced signs trigger `ValueError`.
3. **Pydantic Strict Mode on Dict/JSON Deserialization**:
   - *Issue*: `strict=True` at model level rejected standard ISO-8601 strings (`"2026-08-01"`) and Enum strings (`"EXACT_MATCH"`) when deserializing dicts/JSON.
   - *Resolution*: Kept `StrictInt` on all monetary fields (retaining zero tolerance for floats) while allowing standard Pydantic date and enum string parsing during dictionary and JSON ingestion.

---

## 8. Conclusion and Readiness for Phase 1

Phase 0 is **complete** and verified. The financial domain schemas guarantee zero float drift, the normalizer handles multi-source dirty data, the synthetic benchmark dataset provides 60 diverse scenarios covering all 9 reconciliation categories, and the ground-truth matrix is securely isolated for unbiased evaluation.

The system is fully ready for **Phase 1: Deterministic Multi-Source Ingestion & Rule-Based Matching Engine**.
