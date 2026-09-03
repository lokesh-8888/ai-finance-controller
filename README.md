<div align="center">

# 🏛️ AI Finance Controller
### *Autonomous Multi-Source Financial Reconciliation & Forward Cash Ops*

[![Tests](https://img.shields.io/badge/Pytest-81%20Passed%20(100%25)-00C853?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](docker-compose.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

<p align="center">
  <b>Closes the multi-source financial operations loop across Bank Statements, Payment Gateways, ERP Ledgers, and AP Invoices.</b><br>
  <i>Deterministic 1:1 matching, combinatorial batch solvers, evidence-grounded AI exception investigation, 1-click remediation, and forward cash forecasting.</i>
</p>

[Key Features](#-key-features) •
[System Architecture](#-system-architecture) •
[Interactive Console](#-interactive-operations-console) •
[Benchmark Results](#-evaluation--benchmark-results) •
[Quickstart](#-quickstart) •
[Documentation](#-documentation)

---

</div>

## 📌 Executive Summary

> **The 2026 Financial Operations Consensus:**  
> *Verification capacity, not generation speed, is the enterprise bottleneck. A false-positive financial match is worse than an uncollected invoice. Financial truth must remain deterministic and auditable; AI should investigate ambiguity and provide decision support, not invent financial facts.*

The **AI Finance Controller** is a production-grade, closed-loop financial verification and treasury engine designed to eliminate manual spreadsheet reconciliation:
- **4-Way Multi-Source Parity:** Ingests and normalizes raw records from **Bank Statement Feeds**, **Payment Gateways** (Stripe/Razorpay), **ERP General Ledger**, and **Accounts Payable (AP) Vendor Invoices**.
- **Integer-Cents Precision Math:** Monetary values are strictly calculated in integer cents to eliminate floating-point drift (.1 + 0.2 \neq 0.3$).
- **Deterministic-First Core (,250\text{ rec/sec}$):** Bijective atomic set locking prevents double-matching, while bounded subset-sum algorithms resolve grouped batch wire deposits.
- **Evidence-Grounded AI Investigator:** Resolves ambiguous fee variances, tax withholding (GST/Sales tax), and FX currency drift with an **ambiguity gap threshold ($< 8\%$)** that routes close calls to human review.
- **1-Click Human Remediation Workbench:** Instant controller actions (Approve Variance, Post GL Entry, File Dispute, Write-Off) with tamper-evident **SHA-256 hash-chained audit logging** in SQLite WAL mode.
- **Real-Time Cash Position & Multi-Horizon Forecaster:** Computes settled cash vs. in-flight +2$ receivables and projects 7-day, 14-day, and 30-day cash runway with liquidity waterfall bridges.

---

## 🏛️ System Architecture

`mermaid
flowchart TD
    subgraph S1 [1. Multi-Source Ingestion & Normalization]
        direction TB
        B[Bank Statement Lines<br><b>59 Records</b>]
        G[Payment Gateway Payouts<br><b>45 Records</b>]
        E[ERP General Ledger<br><b>69 Records</b>]
        A[AP Vendor Invoices<br><b>23 Records</b>]
    end

    subgraph S2 [2. Deterministic 1:1 Matcher & Batch Solver]
        direction TB
        EXACT[Stage 1: O(1) Exact Hash Matcher<br>Reference & Token Parity]
        LOCK[Bijective 1:1 Atomic Set Locking<br>Zero Double-Matching Invariant]
        BATCH[Stage 2: Combinatorial Subset-Sum<br>Grouped Deposits & Fee Bounds]
        DET_OUT[48 Matched Batches<br><b>80.00% Baseline Match Rate</b>]
    end

    subgraph S3 [3. Agentic AI Exception Investigator]
        direction TB
        RES[12 Residual Exceptions]
        SAN[Prompt Sanitization & Token Defense]
        GATE[Ambiguity Gating Policy<br>Gap < 8% -> Human Review | Conf < 40% -> Quarantine]
        LLM{Pluggable Provider<br>OpenAI / Gemini / Local Heuristic}
        AI_OUT[12 Forensic Diagnoses<br><b>+20.00% Accuracy Lift</b>]
    end

    subgraph S4 [4. Operational Risk & 1-Click Remediation]
        direction TB
        RP[P0-P4 Risk Prioritizer<br>P0 Critical: Fraud & Unbooked Wires]
        WB[1-Click Controller Workbench<br>Approve | Post GL | Dispute | Write-Off]
        WAL[(SQLite WAL Database<br>Cryptographic SHA-256 Audit Trail)]
    end

    subgraph S5 [5. Treasury Cash Position & Forecaster]
        direction TB
        CP[Multi-Tier Cash Positioning<br>Settled + In-Flight - Committed AP]
        FC[7d / 14d / 30d Forward Forecaster<br>Daily Burn Rate & Cash Runway]
        WF[Liquidity Waterfall Bridge]
    end

    subgraph S6 [6. Operations Console & Grounded Copilot]
        direction TB
        UI[Interactive Fintech Console<br>Dark Mode Tailwind + Chart.js]
        DRAWER[Slide-Out Forensic Inspection Drawer]
        COP[Grounded Financial Copilot<br>Zero-Hallucination Q&A]
        MEMO[Month-End Audit Memo<br>Markdown / JSON / CSV Workpapers]
    end

    B & G & E & A --> EXACT --> LOCK --> BATCH --> DET_OUT
    BATCH --> RES --> SAN --> LLM --> GATE --> AI_OUT
    AI_OUT --> RP --> WB --> WAL
    DET_OUT & WAL --> CP --> FC --> WF
    CP & FC & WF & WB & GATE --> UI & DRAWER & COP & MEMO
`

---

## ⚖️ Deterministic Rules vs. AI Cognitive Reasoning

| Financial Problem | Why Deterministic Rules Win | Where AI Cognitive Reasoning Excels |
| :--- | :--- | :--- |
| **Exact Dollar Matches** | (1)$ Hash lookups on integer cents with 0 token cost | Unnecessary overhead for LLMs |
| **Double-Match Prevention** | Bijective atomic set locking mathematically guarantees 1:1 parity | LLMs cannot maintain atomic state across multi-step execution |
| **Batch Wire Bundles** | Bounded subset-sum algorithm ( \in [2, 6]$) finds exact sum in $< 1\text{ ms}$ | LLMs struggle with combinatorial arithmetic across large sets |
| **Interchange / Gateway Fees** | Checks mathematical bounds (.0\% - 3.5\% + \.30$) | Explains custom fee tier variance to human controllers |
| **Tax Line Discrepancies** | Flags dollar mismatch | Identifies specific tax withholding (e.g. 18% GST or 8.25% Sales Tax) |
| **Vendor Name Aliases** | Levenshtein token distance | Maps dirty invoice memos (AWS CLOUD DUBLIN) to AMAZON WEB SERVICES |
| **Ambiguity Handling** | Rejects unmatched record | Quantifies candidate confidence gap; flags human review if gap $< 8\%$ |

---

## ✨ Key Features

### 1. 4-Way Multi-Source Ingestion & Integer-Cents Engine
- Standardizes data streams from Commercial Banks, Stripe/Razorpay, ERP Subledgers, and Accounts Payable.
- Eliminates float rounding bugs by enforcing StrictInt integer cents across all schemas.

### 2. 9-Scenario Financial Taxonomy
Classifies every transaction into an explicit, auditable financial category:
1. EXACT_MATCH: 1:1 exact reference and nominal amount parity.
2. FEE_DIFFERENCE: Payment processor deductions (.9\% + \.30$) verified as structured evidence.
3. TAX_DIFFERENCE: State or marketplace tax withholding identified.
4. REFUND: Customer return / chargeback reversals offset against gross receipts.
5. ADJUSTMENT: Consolidated wire payout batch rollups.
6. TIMING_DIFFERENCE: In-flight +2$ settlements and cutoff delays.
7. MISSING_SETTLEMENT: Unsettled card transactions or uncollected receivables.
8. DUPLICATE: Repeated capture attempts or double-booked entries.
9. UNEXPLAINED_MISMATCH: Material discrepancies quarantined for human investigation.

### 3. P0–P4 Operational Risk Prioritization
- **P0_CRITICAL**: Unbooked wires $\ge \,000$, unauthorized debits, or potential fraud (highest operational risk).
- **P1_HIGH**: Unexplained variances, duplicate disbursements, missing settlements $\ge T+5$ days.
- **P2_MEDIUM**: Tax variances, customer credit adjustments, ambiguous candidates.
- **P4_NORMAL**: Routine in-flight timing delays, standard interchange variances.

### 4. 1-Click Human Remediation Workbench
- 🟢 **Approve Variance**: Clears allowable fee/tax variances within policy thresholds.
- 📝 **Post GL Entry**: Automatically generates balanced double-entry compensating vouchers ($\sum \text{Debits} == \sum \text{Credits}$).
- 🚨 **File Dispute**: Freezes the transaction and issues a DISP-YYYY-XXXX dispute tracking ticket.
- 🗑️ **Write-Off**: Routes uncollectible balances to Bad Debt Expense.

### 5. Multi-Horizon Treasury Cash Forecaster
- **Settled Cash Balance**: Reconciled cash confirmed in bank accounts.
- **In-Flight Gateway Receivables**: Card charges captured awaiting +2$ payout.
- **Committed AP Obligations**: Scheduled vendor invoices due within payment terms.
- **7-Day / 14-Day / 30-Day Forward Projections**: Daily cash roll-forward modeling runway in months and highlighting liquidity trough dates.

### 6. Grounded Financial Copilot (NL-to-SQL)
- Conversational controller assistant embedded in the UI.
- Queries live SQLite tables to answer questions (*"What is our match rate?"*, *"Show P0 exceptions"*, *"What is our 30-day runway?"*) with zero hallucination.

---

## 📊 Evaluation & Benchmark Results

### Full Automated Pytest Test Suite
`	ext
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-8.3.2
collected 81 items

tests/test_phase0_foundation.py ......................                  [ 27%]
tests/test_phase1_deterministic_engine.py .........                     [ 38%]
tests/test_phase2_ai_investigator.py ............                       [ 53%]
tests/test_phase3_operations_and_audit.py ................              [ 72%]
tests/test_phase4_cash_forecasting.py .........                         [ 83%]
tests/test_phase5_e2e_dashboard_and_copilot.py .............            [100%]

============================= 81 passed in 1.73s ==============================
`

### 20-Seed Monte Carlo Robustness Benchmark (1,200 Scenarios)
To prove the system does not rely on cherry-picked data, the engine was evaluated across 20 distinct random seeds (101 to 120):

`	ext
======================================================================
  AI FINANCE CONTROLLER -- 20-SEED ROBUSTNESS BENCHMARK RESULTS
======================================================================
  Total Independent Seed Runs : 20 (1,200 total synthetic scenarios)
  Mean Classification Accuracy: 100.00% +/- 0.00%
  Mean Macro Precision        : 100.00% +/- 0.00%
  Mean Macro Recall           : 100.00% +/- 0.00%
  Mean Macro F1 Score         : 1.0000 +/- 0.0000
  Fraud False Positive Rate   : 0.00% (Max: 0.00%)
  Deterministic Throughput    : 71,250 records/second
======================================================================
  [SUCCESS] Zero-Tolerance Fraud Security Invariant Verified Across All Seeds!
`

---

## 🖥️ Interactive Operations Console

The web console provides a modern, dark-mode operations interface:

- **Executive KPI Cards**: Real-time Reconciled Volume, Match Rate, AI Recovery Rate, Quarantined Fraud Exposure, and Adjusted Net Cash.
- **Chart.js Visualizations**: 30-Day Forward Cash Trajectory Chart & Liquidity Waterfall Bridge.
- **4-Way Transaction Stream Explorer**: Filterable table with tabs (ALL, MATCHED, AI_INVESTIGATED, EXCEPTIONS) and instant search.
- **Slide-Out Forensic Inspection Drawer**: Inspects candidate record links, rule traces, AI chain-of-thought, and remediation buttons.
- **1-Click Remediation Modals**: Interactive modals to approve, adjust, dispute, or write off records.

---

## ⚡ Quickstart

### Option A: Local Python Run

`ash
# 1. Clone the repository
git clone https://github.com/lokesh-8888/ai-finance-controller.git
cd ai-finance-controller

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the Web Console & REST API
python run.py --app
# Console: http://localhost:8000
# OpenAPI Docs: http://localhost:8000/docs
`

### Option B: Docker Compose (1-Click Deployment)

`ash
docker compose up --build
`
- Web Console: [http://localhost:8000](http://localhost:8000)
- REST API Documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option C: CLI Commands

`ash
# Run the 20-Seed Monte Carlo Robustness Benchmark
python run.py --benchmark --runs 20

# Generate the Month-End Executive Audit Memo (Markdown, JSON & CSV)
python run.py --report

# Run the Full Automated Test Suite (81 Tests)
pytest -v
`

---

## 📡 REST API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| GET | /health | Service and database health check |
| GET | / | Serves the interactive Fintech Operations Console |
| POST | /api/v1/reconcile/run | Triggers a fresh 4-way multi-source reconciliation batch |
| GET | /api/v1/reconcile/kpis | Returns live reconciliation KPIs and match statistics |
| GET | /api/v1/reconcile/records | Returns 4-way transaction stream with status filtering |
| GET | /api/v1/reconcile/records/{id} | Returns forensic deep-dive evidence for the inspection drawer |
| POST | /api/v1/workbench/actions/approve-variance | 1-Click human controller variance approval |
| POST | /api/v1/workbench/actions/post-gl-entry | Posts balanced compensating double-entry journal voucher |
| POST | /api/v1/workbench/actions/file-dispute | Freezes transaction and creates dispute ticket |
| POST | /api/v1/workbench/actions/write-off | Posts bad debt write-off entry |
| GET | /api/v1/forecast/position | Returns real-time multi-tier treasury cash position |
| GET | /api/v1/forecast/horizons | Returns 7-day, 14-day, and 30-day forward cash forecast |
| GET | /api/v1/forecast/waterfall | Returns Chart.js liquidity waterfall bridge data |
| POST | /api/v1/copilot/query | Grounded natural language copilot query endpoint |
| GET | /api/v1/reports/audit-memo | Generates and exports executive Month-End Audit Memo |

---

## 📂 Phase Verification Documentation

Detailed technical architecture, algorithms, invariant proofs, and test execution logs for each phase:

- 📘 [Phase 0 Report: Foundation, Domain Models & Synthetic Generator](docs/phases/PHASE_0_REPORT.md)
- 📘 [Phase 1 Report: Deterministic 1:1 Matcher & Combinatorial Batch Solver](docs/phases/PHASE_1_REPORT.md)
- 📘 [Phase 2 Report: Agentic AI Investigator, Ambiguity Gating & Evaluation](docs/phases/PHASE_2_REPORT.md)
- 📘 [Phase 3 Report: Operational Risk, 1-Click Workbench & SQLite Audit Trail](docs/phases/PHASE_3_REPORT.md)
- 📘 [Phase 4 Report: Real-Time Cash Positioning & Multi-Horizon Forecaster](docs/phases/PHASE_4_REPORT.md)
- 📘 [Phase 5 Report: Interactive Console, Grounded Copilot & Robustness Suite](docs/phases/PHASE_5_REPORT.md)

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
