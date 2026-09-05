"""Synthetic data generator and ground-truth builder for AI Finance Controller.

Produces 60+ realistic multi-source scenarios covering the 9-Scenario Taxonomy,
generating canonical source fixtures (CSV/JSON) and an independent ground-truth evaluation matrix.
"""

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.domain.models import (
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
    GroundTruthRecord,
    ScenarioType,
    RiskPriority,
)
from src.ingestion.normalizer import cents_to_display


class SyntheticFinanceDataset:
    """Orchestrates generation of synthetic financial datasets and ground truth matrix."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.random = random.Random(seed)
        self.base_date = date(2026, 8, 1)

        self.bank_lines: List[BankStatementLine] = []
        self.gateway_txs: List[GatewayTransaction] = []
        self.erp_entries: List[ERPLedgerEntry] = []
        self.ap_invoices: List[APInvoice] = []
        self.ground_truth: List[GroundTruthRecord] = []

        # Counter trackers for clean ID formatting
        self._bnk_counter = 1
        self._gtw_counter = 1
        self._erp_counter = 1
        self._inv_counter = 1
        self._scen_counter = 1

    def _next_bnk_id(self) -> str:
        res = f"BNK-{self._bnk_counter:04d}"
        self._bnk_counter += 1
        return res

    def _next_gtw_id(self) -> str:
        res = f"GTW-{self._gtw_counter:04d}"
        self._gtw_counter += 1
        return res

    def _next_erp_id(self) -> str:
        res = f"GL-{self._erp_counter:05d}"
        self._erp_counter += 1
        return res

    def _next_inv_id(self) -> str:
        res = f"INV-2026-{self._inv_counter:04d}"
        self._inv_counter += 1
        return res

    def _next_scen_id(self, prefix: str = "SCEN") -> str:
        res = f"{prefix}-{self._scen_counter:03d}"
        self._scen_counter += 1
        return res

    def generate_all(self, total_count: int = 200) -> "SyntheticFinanceDataset":
        """Generate 200 benchmark scenarios across 5 specialized cohorts."""
        self._generate_exact_matches(count=100)
        self._generate_net_of_fee_stripe_batches(count=34)
        self._generate_split_bundled_batches(count=16)
        self._generate_fx_and_alias_variants(count=16)
        self._generate_honest_anomalies(count=34)
        return self

    def _generate_exact_matches(self, count: int = 100):
        """Generate 100 Exact Matches (1:1 clean parity).

        - 50 Customer Inward Receipts (Gateway -> Bank Deposit -> ERP Cash Receipt)
        - 50 Vendor Outward Disbursements (AP Invoice -> Bank Debit -> ERP AP Payment)
        """
        customers = [
            "Acme Corp", "Globex Global", "Initech LLC", "Umbrella Enterprises",
            "Hooli Cloud", "Stark Industries", "Wayne Logistics", "Cyberdyne Systems",
            "Soylent Corp", "Massive Dynamic", "Pied Piper", "Dunder Mifflin",
            "Wonka Confections", "Bluth Development", "Aperture Science",
            "Tyrell Corp", "Oscorp Tech", "Starlight Media", "Vandelay Industries",
            "Gekko & Co", "Oceanic Airlines", "Sterling Cooper", "Prestige Worldwide",
            "Weyland Yutani", "Buy N Large"
        ]

        vendors = [
            "Datadog Inc", "Snowflake Inc", "Figma Design", "Slack Technologies",
            "GitHub Inc", "Atlassian Corp", "Twilio API", "Zoom Video",
            "Notion Labs", "Fastly CDN", "Vercel Inc", "Cloudflare DNS",
            "Docker Inc", "MongoDB Atlas", "PagerDuty Operations",
            "Supabase Inc", "Postman Inc", "Stripe Infrastructure", "OpenAI LLC",
            "Linear Orbit", "Retool Inc", "Redis Labs", "Sentry Dev",
            "HashiCorp Inc", "Elastic NV"
        ]

        num_receipts = count // 2
        num_disbursements = count - num_receipts

        # 1. Customer Receipts (Inward)
        for i in range(num_receipts):
            cust = customers[i % len(customers)]
            amount_cents = self.random.randint(15000, 850000)  # $150.00 to $8,500.00
            tx_date = self.base_date + timedelta(days=self.random.randint(1, 25))
            order_ref = f"ORD-EXACT-{1000 + i}"
            batch_id = f"batch_direct_{i+1:03d}"

            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-EX")

            gtw = GatewayTransaction(
                id=gtw_id,
                order_id=order_ref,
                gross_amount_cents=amount_cents,
                fee_cents=0,
                tax_cents=0,
                net_amount_cents=amount_cents,
                payout_batch_id=batch_id,
                status="succeeded"
            )
            self.gateway_txs.append(gtw)

            bnk = BankStatementLine(
                id=bnk_id,
                date=tx_date,
                amount_cents=amount_cents,
                raw_description=f"CUSTOMER CHECKOUT DIRECT DEPOSIT {order_ref} {cust.upper()}",
                reference_code=f"REF-DEP-{1000 + i}",
                account_id="ACCT-OPERATING-01"
            )
            self.bank_lines.append(bnk)

            erp = ERPLedgerEntry(
                id=erp_id,
                invoice_id=order_ref,
                gl_account_code="1010-CASH",
                amount_cents=amount_cents,
                customer_vendor_name=cust,
                entry_date=tx_date,
                doc_type="PAYMENT"
            )
            self.erp_entries.append(erp)

            gt = GroundTruthRecord(
                scenario_id=scen_id,
                scenario_type=ScenarioType.EXACT_MATCH,
                risk_priority=RiskPriority.P4_NORMAL,
                bank_line_id=bnk_id,
                gateway_tx_id=gtw_id,
                erp_entry_id=erp_id,
                invoice_id=None,
                expected_status="MATCHED",
                variance_cents=0,
                explanation=f"1:1 clean parity across Gateway ({cents_to_display(amount_cents)}), Bank deposit, and ERP Cash receipt for {cust}."
            )
            self.ground_truth.append(gt)

        # 2. Vendor Disbursements (Outward)
        for i in range(num_disbursements):
            vend = vendors[i % len(vendors)]
            amount_cents = self.random.randint(25000, 950000)  # $250.00 to $9,500.00
            inv_date = self.base_date + timedelta(days=self.random.randint(1, 20))
            pay_date = inv_date + timedelta(days=self.random.randint(2, 6))

            inv_id = self._next_inv_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-EX")

            inv = APInvoice(
                id=inv_id,
                vendor_name=vend,
                amount_cents=amount_cents,
                due_date=pay_date,
                currency="USD",
                fx_rate=1.0,
                status="PAID"
            )
            self.ap_invoices.append(inv)

            bnk = BankStatementLine(
                id=bnk_id,
                date=pay_date,
                amount_cents=-amount_cents,
                raw_description=f"ACH OUTWARD VENDOR PMT {inv_id} {vend.upper()}",
                reference_code=f"ACH-OUT-{2000 + i}",
                account_id="ACCT-OPERATING-01"
            )
            self.bank_lines.append(bnk)

            erp = ERPLedgerEntry(
                id=erp_id,
                invoice_id=inv_id,
                gl_account_code="2010-AP",
                amount_cents=-amount_cents,
                customer_vendor_name=vend,
                entry_date=pay_date,
                doc_type="PAYMENT"
            )
            self.erp_entries.append(erp)

            gt = GroundTruthRecord(
                scenario_id=scen_id,
                scenario_type=ScenarioType.EXACT_MATCH,
                risk_priority=RiskPriority.P4_NORMAL,
                bank_line_id=bnk_id,
                gateway_tx_id=None,
                erp_entry_id=erp_id,
                invoice_id=inv_id,
                expected_status="MATCHED",
                variance_cents=0,
                explanation=f"1:1 clean match between AP Invoice {inv_id} ({cents_to_display(amount_cents)}), Bank debit, and ERP AP clearing for {vend}."
            )
            self.ground_truth.append(gt)

    def _generate_net_of_fee_stripe_batches(self, count: int = 34):
        """Generate 34 Net-of-fee Stripe batches.

        Stripe standard card fee: 2.9% + $0.30 (30 cents).
        Gross revenue is recorded in ERP; net deposit hits Bank.
        Difference is precisely accounted for by gateway fee schedule.
        """
        for i in range(count):
            gross_cents = self.random.randint(8000, 420000)  # $80.00 to $4,200.00
            fee_cents = int(round(gross_cents * 0.029)) + 30
            net_cents = gross_cents - fee_cents

            order_date = self.base_date + timedelta(days=self.random.randint(2, 24))
            settle_date = order_date + timedelta(days=2)  # T+2 settlement
            order_id = f"ORD-STRIPE-{4000 + i}"
            batch_id = f"po_stripe_{5000 + i}"

            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-FEE")

            gtw = GatewayTransaction(
                id=gtw_id,
                order_id=order_id,
                gross_amount_cents=gross_cents,
                fee_cents=fee_cents,
                tax_cents=0,
                net_amount_cents=net_cents,
                payout_batch_id=batch_id,
                status="succeeded"
            )
            self.gateway_txs.append(gtw)

            bnk = BankStatementLine(
                id=bnk_id,
                date=settle_date,
                amount_cents=net_cents,
                raw_description=f"STRIPE PAYMENTS PAYOUT TRANSFER {batch_id}",
                reference_code=batch_id,
                account_id="ACCT-OPERATING-01"
            )
            self.bank_lines.append(bnk)

            erp = ERPLedgerEntry(
                id=erp_id,
                invoice_id=order_id,
                gl_account_code="4000-REVENUE",
                amount_cents=gross_cents,
                customer_vendor_name="STRIPE PAYMENTS",
                entry_date=order_date,
                doc_type="INVOICE"
            )
            self.erp_entries.append(erp)

            gt = GroundTruthRecord(
                scenario_id=scen_id,
                scenario_type=ScenarioType.FEE_DIFFERENCE,
                risk_priority=RiskPriority.P2_MEDIUM,
                bank_line_id=bnk_id,
                gateway_tx_id=gtw_id,
                erp_entry_id=erp_id,
                invoice_id=None,
                expected_status="FEE_EXPLAINED",
                variance_cents=fee_cents,
                explanation=(
                    f"Customer gross payment of {cents_to_display(gross_cents)} was settled net {cents_to_display(net_cents)} "
                    f"after standard Stripe fee deduction of {cents_to_display(fee_cents)} (2.9% + $0.30)."
                )
            )
            self.ground_truth.append(gt)

    def _generate_split_bundled_batches(self, count: int = 16):
        """Generate 16 Split/bundled batch wire deposits (1 Bank line to N Gateway transactions)."""
        for i in range(count):
            batch_id = f"po_bundle_batch_{6000 + i}"
            settle_date = self.base_date + timedelta(days=self.random.randint(5, 27))
            num_txs = self.random.randint(2, 4)

            bundled_gtw_ids = []
            bundled_erp_ids = []
            total_net_cents = 0
            total_gross_cents = 0
            total_fee_cents = 0

            for j in range(num_txs):
                gross = self.random.randint(12000, 95000)  # $120.00 to $950.00
                fee = int(round(gross * 0.025))  # 2.5% merchant rate
                net = gross - fee
                total_gross_cents += gross
                total_fee_cents += fee
                total_net_cents += net

                order_id = f"ORD-BUNDLE-{7000 + i*10 + j}"
                gtw_id = self._next_gtw_id()
                erp_id = self._next_erp_id()
                bundled_gtw_ids.append(gtw_id)
                bundled_erp_ids.append(erp_id)

                gtw = GatewayTransaction(
                    id=gtw_id,
                    order_id=order_id,
                    gross_amount_cents=gross,
                    fee_cents=fee,
                    tax_cents=0,
                    net_amount_cents=net,
                    payout_batch_id=batch_id,
                    status="succeeded"
                )
                self.gateway_txs.append(gtw)

                erp = ERPLedgerEntry(
                    id=erp_id,
                    invoice_id=order_id,
                    gl_account_code="4000-REVENUE",
                    amount_cents=gross,
                    customer_vendor_name="STRIPE MERCHANT BUNDLE",
                    entry_date=settle_date - timedelta(days=1),
                    doc_type="INVOICE"
                )
                self.erp_entries.append(erp)

            bnk_id = self._next_bnk_id()
            bnk = BankStatementLine(
                id=bnk_id,
                date=settle_date,
                amount_cents=total_net_cents,
                raw_description=f"MERCHANT SETTLEMENT WIRE BUNDLE {batch_id} COUNT {num_txs}",
                reference_code=batch_id,
                account_id="ACCT-OPERATING-01"
            )
            self.bank_lines.append(bnk)

            scen_id = self._next_scen_id("SCEN-BUNDLE")
            gt = GroundTruthRecord(
                scenario_id=scen_id,
                scenario_type=ScenarioType.ADJUSTMENT,
                risk_priority=RiskPriority.P2_MEDIUM,
                bank_line_id=bnk_id,
                gateway_tx_id=",".join(bundled_gtw_ids),
                erp_entry_id=",".join(bundled_erp_ids),
                invoice_id=None,
                expected_status="BATCH_RECONCILED",
                variance_cents=total_fee_cents,
                explanation=(
                    f"Consolidated wire deposit of {cents_to_display(total_net_cents)} aggregates {num_txs} transactions "
                    f"totaling {cents_to_display(total_gross_cents)} gross minus {cents_to_display(total_fee_cents)} total fees."
                )
            )
            self.ground_truth.append(gt)

    def _generate_fx_and_alias_variants(self, count: int = 16):
        """Generate 16 FX Currency & Vendor Alias Variants.

        - 8 Multi-currency conversions (EUR, GBP, CAD, JPY, AUD, CHF, SGD, EUR)
        - 8 Vendor alias variations (e.g. AWS, Google Cloud, Snowflake, Stripe, Datadog)
        """
        fx_configs = [
            ("AWS Cloud Dublin", 120000, "EUR", 1.0850, "INTL WIRE OUT EUR AWS EMEA SARL FX 1.0850", "AMAZON WEB SERVICES"),
            ("DATADOG US", 85000, "GBP", 1.2800, "WIRE TRANSFER LONDON UK DATADOG INC GBP 850 FX 1.28", "DATADOG"),
            ("Shopify Canada", 240000, "CAD", 0.7450, "INTL WIRE CAD SHOPIFY COMMERCE FX 0.7450", "SHOPIFY"),
            ("SoftBank Tokyo", 45000000, "JPY", 0.0068, "WIRE TRANSFER TOKYO JAPAN JPY SOFTBANK FX 0.0068", "SOFTBANK"),
            ("Canva Sydney", 160000, "AUD", 0.6650, "INTL WIRE AUD CANVA PTY LTD FX 0.6650", "CANVA"),
            ("Logitech Vaud", 95000, "CHF", 1.1350, "WIRE TRANSFER SWITZERLAND CHF LOGITECH FX 1.1350", "LOGITECH"),
            ("Grab Singapore", 310000, "SGD", 0.7620, "INTL WIRE SGD GRAB TAXI HOLDINGS FX 0.7620", "GRAB"),
            ("Spotify Stockholm", 185000, "EUR", 1.0920, "INTL WIRE OUT EUR SPOTIFY AB FX 1.0920", "SPOTIFY"),
        ]

        for idx, (vend, foreign_amt, curr, fx_rate, desc, erp_vend) in enumerate(fx_configs):
            inv_id = self._next_inv_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-FX")
            usd_cents = int(round(foreign_amt * fx_rate))
            dt = self.base_date + timedelta(days=10 + idx)

            self.ap_invoices.append(APInvoice(
                id=inv_id,
                vendor_name=vend,
                amount_cents=foreign_amt,
                due_date=dt,
                currency=curr,
                fx_rate=fx_rate,
                status="PAID"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id,
                date=dt,
                amount_cents=-usd_cents,
                raw_description=desc,
                reference_code=f"FX-{curr}-{100 + idx}",
                account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id,
                invoice_id=inv_id,
                gl_account_code="6010-CLOUD-INFRA",
                amount_cents=-usd_cents,
                customer_vendor_name=erp_vend,
                entry_date=dt,
                doc_type="PAYMENT"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id,
                scenario_type=ScenarioType.TIMING_DIFFERENCE,
                risk_priority=RiskPriority.P2_MEDIUM,
                bank_line_id=bnk_id,
                gateway_tx_id=None,
                erp_entry_id=erp_id,
                invoice_id=inv_id,
                expected_status="FX_RESOLVED",
                variance_cents=0,
                explanation=f"{curr} {cents_to_display(foreign_amt)} invoice from '{vend}' converted to USD {cents_to_display(usd_cents)} at FX rate {fx_rate:.4f}, resolved to canonical '{erp_vend}'."
            ))

        alias_configs = [
            ("MSFT AZURE", "ACH DEBIT MICROSOFT CORP CLOUD SERVICES", "MICROSOFT AZURE", 450000),
            ("GOOGLE IRELAND", "DIRECT DEBIT GOOG CLOUD SERVICES REQ-404", "GOOGLE CLOUD PLATFORM", 320000),
            ("SNOWFLAKE COMPUTING", "ACH DISBURSEMENT SNOWFLAKE INC WAREHOUSE", "SNOWFLAKE", 580000),
            ("AWS", "AMAZON WEB SERVICES INC ACH OUT", "AMAZON WEB SERVICES", 275000),
            ("STRIPE INC", "STRIPE PAYOUT MERCHANT SERVICES", "STRIPE", 195000),
            ("DATADOG INC", "ACH DEBIT DATADOG MONITORING", "DATADOG", 340000),
            ("AMZN", "AMAZON CLOUD COMPUTING DEBIT", "AMAZON WEB SERVICES", 210000),
            ("GCP", "GOOGLE CLOUD INFRASTRUCTURE BILL", "GOOGLE CLOUD PLATFORM", 410000),
        ]

        for idx, (inv_vend, bank_desc, erp_vend, amt) in enumerate(alias_configs):
            inv_id = self._next_inv_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ALIAS")
            dt = self.base_date + timedelta(days=12 + idx)

            self.ap_invoices.append(APInvoice(
                id=inv_id,
                vendor_name=inv_vend,
                amount_cents=amt,
                due_date=dt,
                currency="USD",
                fx_rate=1.0,
                status="PAID"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id,
                date=dt,
                amount_cents=-amt,
                raw_description=bank_desc,
                reference_code=f"ACH-ALIAS-{300 + idx}",
                account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id,
                invoice_id=inv_id,
                gl_account_code="6020-SOFTWARE-SAAS",
                amount_cents=-amt,
                customer_vendor_name=erp_vend,
                entry_date=dt,
                doc_type="PAYMENT"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id,
                scenario_type=ScenarioType.EXACT_MATCH,
                risk_priority=RiskPriority.P4_NORMAL,
                bank_line_id=bnk_id,
                gateway_tx_id=None,
                erp_entry_id=erp_id,
                invoice_id=inv_id,
                expected_status="MATCHED",
                variance_cents=0,
                explanation=f"Vendor alias '{inv_vend}' and statement descriptor '{bank_desc}' normalized and resolved to canonical '{erp_vend}'."
            ))

    def _generate_honest_anomalies(self, count: int = 34):
        """Generate 34 Quarantined honest anomalies covering edge cases and full taxonomy enums.

        1. Duplicate bank statement lines (3 records, P1_HIGH)
        2. Duplicate ERP invoice entries (3 records, P1_HIGH)
        3. Missing settlement: Gateway charge succeeded but no bank deposit (4 records, P1_HIGH)
        4. Missing settlement: AP invoice open/unpaid, no bank withdrawal (4 records, P1_HIGH)
        5. Unexplained mismatch: Discrepancy/shortage with arbitrary drift (3 records, P0_CRITICAL)
        6. Unexplained mismatch: Unbooked bank wire / orphan inward deposit (3 records, P0_CRITICAL)
        7. Customer refund chargeback: Full return (4 records, P2_MEDIUM)
        8. Customer refund offset: Partial return against existing order (3 records, P2_MEDIUM)
        9. Tax difference: 8.25% sales tax collected on checkout omitted from ERP line (4 records, P1_HIGH)
        10. Timing difference: Cross-period month-end cutoff settlement (3 records, P2_MEDIUM)
        Total = 3 + 3 + 4 + 4 + 3 + 3 + 4 + 3 + 4 + 3 = 34 records.
        """
        # --- 1. Duplicate Bank Statement Lines (3 records) ---
        dup_bank_vendors = [
            ("Figma Design", 175000),
            ("Atlassian Corp", 240000),
            ("Docker Inc", 120000),
        ]
        for i, (vend, amt) in enumerate(dup_bank_vendors):
            dt = self.base_date + timedelta(days=20 + i)
            inv_id = self._next_inv_id()
            bnk_a = self._next_bnk_id()
            bnk_b = self._next_bnk_id()  # duplicate posting
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.ap_invoices.append(APInvoice(
                id=inv_id, vendor_name=vend, amount_cents=amt,
                due_date=dt, currency="USD", fx_rate=1.0, status="PAID"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_a, date=dt, amount_cents=-amt,
                raw_description=f"ACH DEBIT {vend.upper()} {inv_id}",
                reference_code=f"REF-DUP-{10 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_b, date=dt, amount_cents=-amt,
                raw_description=f"ACH DEBIT {vend.upper()} {inv_id} (DUPLICATE POSTING)",
                reference_code=f"REF-DUP-{10 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=inv_id, gl_account_code="2010-AP",
                amount_cents=-amt, customer_vendor_name=vend.upper(), entry_date=dt, doc_type="PAYMENT"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.DUPLICATE, risk_priority=RiskPriority.P1_HIGH,
                bank_line_id=f"{bnk_a},{bnk_b}", gateway_tx_id=None, erp_entry_id=erp_id, invoice_id=inv_id,
                expected_status="DUPLICATE_QUARANTINED", variance_cents=amt,
                explanation=f"Bank posted duplicate disbursement {bnk_b} of {cents_to_display(amt)} for invoice {inv_id}."
            ))

        # --- 2. Duplicate ERP Ledger Entries (3 records) ---
        dup_erp_vendors = [
            ("Slack Technologies", 98000),
            ("Notion Labs", 145000),
            ("Cloudflare DNS", 210000),
        ]
        for i, (vend, amt) in enumerate(dup_erp_vendors):
            dt = self.base_date + timedelta(days=21 + i)
            inv_id = self._next_inv_id()
            bnk_id = self._next_bnk_id()
            erp_a = self._next_erp_id()
            erp_b = self._next_erp_id()  # duplicate booking
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.ap_invoices.append(APInvoice(
                id=inv_id, vendor_name=vend, amount_cents=amt,
                due_date=dt, currency="USD", fx_rate=1.0, status="PAID"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt, amount_cents=-amt,
                raw_description=f"ACH OUTWARD PMT {inv_id} {vend.upper()}",
                reference_code=f"ACH-{vend[:5].upper()}-{20 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_a, invoice_id=inv_id, gl_account_code="2010-AP",
                amount_cents=-amt, customer_vendor_name=vend.upper(), entry_date=dt, doc_type="PAYMENT"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_b, invoice_id=inv_id, gl_account_code="2010-AP",
                amount_cents=-amt, customer_vendor_name=vend.upper(), entry_date=dt, doc_type="PAYMENT"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.DUPLICATE, risk_priority=RiskPriority.P1_HIGH,
                bank_line_id=bnk_id, gateway_tx_id=None, erp_entry_id=f"{erp_a},{erp_b}", invoice_id=inv_id,
                expected_status="DUPLICATE_QUARANTINED", variance_cents=amt,
                explanation=f"ERP contains duplicate ledger entry {erp_b} for single bank disbursement of {cents_to_display(amt)}."
            ))

        # --- 3. Missing Gateway Settlements (4 records) ---
        miss_gtw_configs = [
            ("ORD-MISS-3001", 145000, 4235),
            ("ORD-MISS-3002", 220000, 6410),
            ("ORD-MISS-3003", 98000, 2872),
            ("ORD-MISS-3004", 315000, 9165),
        ]
        for i, (ord_id, gross, fee) in enumerate(miss_gtw_configs):
            dt = self.base_date + timedelta(days=5 + i*2)
            gtw_id = self._next_gtw_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")
            net = gross - fee

            self.gateway_txs.append(GatewayTransaction(
                id=gtw_id, order_id=ord_id, gross_amount_cents=gross,
                fee_cents=fee, tax_cents=0, net_amount_cents=net,
                payout_batch_id="po_orphaned_unsettled", status="succeeded"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=ord_id, gl_account_code="4000-REVENUE",
                amount_cents=gross, customer_vendor_name="ORPHAN CUSTOMER",
                entry_date=dt, doc_type="INVOICE"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.MISSING_SETTLEMENT, risk_priority=RiskPriority.P1_HIGH,
                bank_line_id=None, gateway_tx_id=gtw_id, erp_entry_id=erp_id, invoice_id=None,
                expected_status="SETTLEMENT_MISSING", variance_cents=net,
                explanation=f"Gateway captured {cents_to_display(gross)} on {dt} but payout never credited to operating bank account."
            ))

        # --- 4. Missing AP Settlements / Unpaid Invoices (4 records) ---
        miss_ap_configs = [
            ("Vercel Inc", 210000),
            ("MongoDB Atlas", 340000),
            ("Fastly CDN", 165000),
            ("Twilio API", 280000),
        ]
        for i, (vend, amt) in enumerate(miss_ap_configs):
            dt = self.base_date + timedelta(days=7 + i*2)
            inv_id = self._next_inv_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.ap_invoices.append(APInvoice(
                id=inv_id, vendor_name=vend, amount_cents=amt,
                due_date=dt, currency="USD", fx_rate=1.0, status="OPEN"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=inv_id, gl_account_code="2010-AP",
                amount_cents=amt, customer_vendor_name=vend.upper(),
                entry_date=dt, doc_type="INVOICE"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.MISSING_SETTLEMENT, risk_priority=RiskPriority.P1_HIGH,
                bank_line_id=None, gateway_tx_id=None, erp_entry_id=erp_id, invoice_id=inv_id,
                expected_status="UNPAID_INVOICE", variance_cents=amt,
                explanation=f"AP Invoice {inv_id} for {cents_to_display(amt)} booked in ERP but pending bank wire settlement."
            ))

        # --- 5. Unexplained Shortages / Mismatches (3 records, P0_CRITICAL) ---
        unexp_configs = [
            (300000, 287550, "ORD-UNEXP-5001"),  # $124.50 shortage
            (500000, 478500, "ORD-UNEXP-5002"),  # $215.00 shortage
            (420000, 401025, "ORD-UNEXP-5003"),  # $189.75 shortage
        ]
        for i, (amt_exp, amt_act, ord_ref) in enumerate(unexp_configs):
            diff = amt_exp - amt_act
            dt = self.base_date + timedelta(days=23 + i)
            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.gateway_txs.append(GatewayTransaction(
                id=gtw_id, order_id=ord_ref, gross_amount_cents=amt_exp,
                fee_cents=0, tax_cents=0, net_amount_cents=amt_exp,
                payout_batch_id="po_corrupt_settle", status="succeeded"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt, amount_cents=amt_act,
                raw_description=f"INWARD DEPOSIT SETTLEMENT {ord_ref} SHORTAGE",
                reference_code=f"REF-SHORT-{5001 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=ord_ref, gl_account_code="1010-CASH",
                amount_cents=amt_exp, customer_vendor_name="Acme Corp",
                entry_date=dt, doc_type="PAYMENT"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.UNEXPLAINED_MISMATCH, risk_priority=RiskPriority.P0_CRITICAL,
                bank_line_id=bnk_id, gateway_tx_id=gtw_id, erp_entry_id=erp_id, invoice_id=None,
                expected_status="UNEXPLAINED_VARIANCE", variance_cents=diff,
                explanation=f"Critical unexplained variance of {cents_to_display(diff)} between bank deposit ({cents_to_display(amt_act)}) and ERP/Gateway ({cents_to_display(amt_exp)})."
            ))

        # --- 6. Unbooked Bank Wires / Orphan Deposits (3 records, P0_CRITICAL) ---
        orphan_configs = [
            (1500000, "883921"),  # $15,000.00
            (850000, "994812"),   # $8,500.00
            (1225000, "773105"),  # $12,250.00
        ]
        for i, (amt, ref) in enumerate(orphan_configs):
            dt = self.base_date + timedelta(days=24 + i)
            bnk_id = self._next_bnk_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt, amount_cents=amt,
                raw_description=f"WIRE INWARD REF {ref} PRIVATE UNIDENTIFIED",
                reference_code=f"WIRE-UNKNOWN-{ref}", account_id="ACCT-OPERATING-01"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.UNEXPLAINED_MISMATCH, risk_priority=RiskPriority.P0_CRITICAL,
                bank_line_id=bnk_id, gateway_tx_id=None, erp_entry_id=None, invoice_id=None,
                expected_status="UNBOOKED_DEPOSIT", variance_cents=amt,
                explanation=f"Unidentified bank wire of {cents_to_display(amt)} received with no matching ERP journal entry or customer billing record."
            ))

        # --- 7. Customer Full Refunds (4 records) ---
        full_refund_configs = [
            (15000, "ORD-REF-7001"),
            (22000, "ORD-REF-7002"),
            (34000, "ORD-REF-7003"),
            (18000, "ORD-REF-7004"),
        ]
        for i, (amt, ord_ref) in enumerate(full_refund_configs):
            dt = self.base_date + timedelta(days=22 + i)
            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.gateway_txs.append(GatewayTransaction(
                id=gtw_id, order_id=ord_ref, gross_amount_cents=-amt,
                fee_cents=0, tax_cents=0, net_amount_cents=-amt,
                payout_batch_id=f"po_refund_batch_{7001 + i}", status="refunded"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt, amount_cents=-amt,
                raw_description=f"STRIPE CUSTOMER REFUND CHARGEBACK {ord_ref}",
                reference_code=f"REF-CHG-{7001 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=ord_ref, gl_account_code="4010-SALES-RETURNS",
                amount_cents=-amt, customer_vendor_name="RETURN CUSTOMER",
                entry_date=dt, doc_type="CREDIT_MEMO"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.REFUND, risk_priority=RiskPriority.P2_MEDIUM,
                bank_line_id=bnk_id, gateway_tx_id=gtw_id, erp_entry_id=erp_id, invoice_id=None,
                expected_status="REFUND_MATCHED", variance_cents=0,
                explanation=f"Processed customer refund of {cents_to_display(amt)} matching gateway return, bank deduction, and ERP credit memo."
            ))

        # --- 8. Customer Partial Refunds / Adjustments (3 records) ---
        part_refund_configs = [
            (7500, "ORD-PART-8001"),
            (9500, "ORD-PART-8002"),
            (11000, "ORD-PART-8003"),
        ]
        for i, (amt, ord_ref) in enumerate(part_refund_configs):
            dt = self.base_date + timedelta(days=25 + i)
            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.gateway_txs.append(GatewayTransaction(
                id=gtw_id, order_id=ord_ref, gross_amount_cents=-amt,
                fee_cents=0, tax_cents=0, net_amount_cents=-amt,
                payout_batch_id=f"po_partial_{8001 + i}", status="refunded"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt, amount_cents=-amt,
                raw_description=f"MERCHANT PARTIAL CREDIT ADJUSTMENT {ord_ref}",
                reference_code=f"REF-PART-{8001 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=ord_ref, gl_account_code="4010-SALES-RETURNS",
                amount_cents=-amt, customer_vendor_name="PARTIAL RETURN CUSTOMER",
                entry_date=dt, doc_type="CREDIT_MEMO"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.REFUND, risk_priority=RiskPriority.P2_MEDIUM,
                bank_line_id=bnk_id, gateway_tx_id=gtw_id, erp_entry_id=erp_id, invoice_id=None,
                expected_status="REFUND_MATCHED", variance_cents=0,
                explanation=f"Partial refund adjustment of {cents_to_display(amt)} reconciled between gateway, bank debit, and ERP credit memo."
            ))

        # --- 9. Tax Differences (4 records) ---
        tax_configs = [
            (100000, 8250, "ORD-TAX-9001"),
            (200000, 16500, "ORD-TAX-9002"),
            (150000, 12375, "ORD-TAX-9003"),
            (280000, 23100, "ORD-TAX-9004"),
        ]
        for i, (gross_no_tax, tax, ord_ref) in enumerate(tax_configs):
            gross_with_tax = gross_no_tax + tax
            dt = self.base_date + timedelta(days=26 + i)
            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.gateway_txs.append(GatewayTransaction(
                id=gtw_id, order_id=ord_ref, gross_amount_cents=gross_with_tax,
                fee_cents=0, tax_cents=tax, net_amount_cents=gross_no_tax,
                payout_batch_id=f"po_tax_settle_{i}", status="succeeded"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt, amount_cents=gross_no_tax,
                raw_description=f"GATEWAY NET PAYOUT (TAX EXCLUDED) {ord_ref}",
                reference_code=f"REF-TAX-{9001 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=ord_ref, gl_account_code="4000-REVENUE",
                amount_cents=gross_with_tax, customer_vendor_name="TAXABLE CUSTOMER LLC",
                entry_date=dt, doc_type="INVOICE"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.TAX_DIFFERENCE, risk_priority=RiskPriority.P1_HIGH,
                bank_line_id=bnk_id, gateway_tx_id=gtw_id, erp_entry_id=erp_id, invoice_id=None,
                expected_status="TAX_EXPLAINED", variance_cents=tax,
                explanation=f"Discrepancy of {cents_to_display(tax)} explained by 8.25% state sales tax withheld by marketplace facilitator."
            ))

        # --- 10. Timing Differences Across Month-End Cutoff (3 records) ---
        timing_configs = [
            (350000, "ORD-TIMING-10001", date(2026, 8, 31), date(2026, 9, 2)),
            (280000, "ORD-TIMING-10002", date(2026, 8, 31), date(2026, 9, 2)),
            (410000, "ORD-TIMING-10003", date(2026, 8, 31), date(2026, 9, 3)),
        ]
        for i, (amt, ord_ref, dt_order, dt_settle) in enumerate(timing_configs):
            gtw_id = self._next_gtw_id()
            bnk_id = self._next_bnk_id()
            erp_id = self._next_erp_id()
            scen_id = self._next_scen_id("SCEN-ANOM")

            self.gateway_txs.append(GatewayTransaction(
                id=gtw_id, order_id=ord_ref, gross_amount_cents=amt,
                fee_cents=0, tax_cents=0, net_amount_cents=amt,
                payout_batch_id=f"po_cutoff_batch_{i}", status="succeeded"
            ))
            self.bank_lines.append(BankStatementLine(
                id=bnk_id, date=dt_settle, amount_cents=amt,
                raw_description=f"BATCH DEPOSIT CROSS-MONTH SETTLEMENT {ord_ref}",
                reference_code=f"REF-CUTOFF-{1001 + i}", account_id="ACCT-OPERATING-01"
            ))
            self.erp_entries.append(ERPLedgerEntry(
                id=erp_id, invoice_id=ord_ref, gl_account_code="4000-REVENUE",
                amount_cents=amt, customer_vendor_name="END OF MONTH CLIENT",
                entry_date=dt_order, doc_type="INVOICE"
            ))
            self.ground_truth.append(GroundTruthRecord(
                scenario_id=scen_id, scenario_type=ScenarioType.TIMING_DIFFERENCE, risk_priority=RiskPriority.P2_MEDIUM,
                bank_line_id=bnk_id, gateway_tx_id=gtw_id, erp_entry_id=erp_id, invoice_id=None,
                expected_status="TIMING_IN_FLIGHT", variance_cents=0,
                explanation=f"Transaction initiated {dt_order.isoformat()} posted in ERP August close; bank deposit received {dt_settle.isoformat()} (T+2 cross-period settlement)."
            ))

    def export_canonical(self, output_dir: Path):
        """Export canonical dataset fixtures as both CSV and JSON."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. BankStatementLines
        bnk_dicts = [line.model_dump(mode="json") for line in self.bank_lines]
        _write_csv(output_dir / "bank_statement_lines.csv", bnk_dicts)
        _write_json(output_dir / "bank_statement_lines.json", bnk_dicts)

        # 2. GatewayTransactions
        gtw_dicts = [tx.model_dump(mode="json") for tx in self.gateway_txs]
        _write_csv(output_dir / "gateway_transactions.csv", gtw_dicts)
        _write_json(output_dir / "gateway_transactions.json", gtw_dicts)

        # 3. ERPLedgerEntries
        erp_dicts = [entry.model_dump(mode="json") for entry in self.erp_entries]
        _write_csv(output_dir / "erp_ledger_entries.csv", erp_dicts)
        _write_json(output_dir / "erp_ledger_entries.json", erp_dicts)

        # 4. APInvoices
        inv_dicts = [inv.model_dump(mode="json") for inv in self.ap_invoices]
        _write_csv(output_dir / "ap_invoices.csv", inv_dicts)
        _write_json(output_dir / "ap_invoices.json", inv_dicts)

    def export_ground_truth(self, output_dir: Path):
        """Export ground-truth evaluation matrix strictly isolated from canonical fixtures."""
        output_dir.mkdir(parents=True, exist_ok=True)

        gt_dicts = [gt.model_dump(mode="json") for gt in self.ground_truth]
        _write_csv(output_dir / "ground_truth.csv", gt_dicts)
        _write_json(output_dir / "ground_truth.json", gt_dicts)


def _write_csv(path: Path, data: List[Dict[str, Any]]):
    """Write list of dictionaries to CSV."""
    if not data:
        return
    fieldnames = list(data[0].keys())
    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def _write_json(path: Path, data: List[Dict[str, Any]]):
    """Write list of dictionaries to pretty-printed JSON."""
    with open(path, mode="w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def generate_all_synthetic_data(project_root: Optional[Path] = None) -> SyntheticFinanceDataset:
    """Generate and persist the complete synthetic benchmark and ground-truth matrix."""
    if project_root is None:
        # Default to standard project structure
        project_root = Path(__file__).resolve().parent.parent.parent

    canonical_dir = project_root / "data" / "canonical"
    ground_truth_dir = project_root / "data" / "ground_truth"

    dataset = SyntheticFinanceDataset(seed=42)
    dataset.generate_all()

    dataset.export_canonical(canonical_dir)
    dataset.export_ground_truth(ground_truth_dir)

    return dataset


if __name__ == "__main__":
    ds = generate_all_synthetic_data()
    print(f"Generated Phase 0 Benchmark Fixtures:")
    print(f"  - Bank Statement Lines: {len(ds.bank_lines)}")
    print(f"  - Gateway Transactions: {len(ds.gateway_txs)}")
    print(f"  - ERP Ledger Entries:   {len(ds.erp_entries)}")
    print(f"  - AP Invoices:          {len(ds.ap_invoices)}")
    print(f"  - Ground Truth Matrix:  {len(ds.ground_truth)} scenarios")


# Alias for backward and forward compatibility
SyntheticDataGenerator = SyntheticFinanceDataset

