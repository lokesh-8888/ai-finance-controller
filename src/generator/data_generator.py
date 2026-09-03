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

    def generate_all(self) -> "SyntheticFinanceDataset":
        """Generate all 60 benchmark scenarios across 5 specialized cohorts."""
        self._generate_exact_matches(count=30)
        self._generate_net_of_fee_stripe_batches(count=10)
        self._generate_split_bundled_batches(count=5)
        self._generate_fx_and_alias_variants(count=5)
        self._generate_honest_anomalies(count=10)
        return self

    def _generate_exact_matches(self, count: int = 30):
        """Generate 30 Exact Matches (1:1 clean parity).

        - 15 Customer Inward Receipts (Gateway -> Bank Deposit -> ERP Cash Receipt)
        - 15 Vendor Outward Disbursements (AP Invoice -> Bank Debit -> ERP AP Payment)
        """
        customers = [
            "Acme Corp", "Globex Global", "Initech LLC", "Umbrella Enterprises",
            "Hooli Cloud", "Stark Industries", "Wayne Logistics", "Cyberdyne Systems",
            "Soylent Corp", "Massive Dynamic", "Pied Piper", "Dunder Mifflin",
            "Wonka Confections", "Bluth Development", "Aperture Science"
        ]

        vendors = [
            "Datadog Inc", "Snowflake Inc", "Figma Design", "Slack Technologies",
            "GitHub Inc", "Atlassian Corp", "Twilio API", "Zoom Video",
            "Notion Labs", "Fastly CDN", "Vercel Inc", "Cloudflare DNS",
            "Docker Inc", "MongoDB Atlas", "PagerDuty Operations"
        ]

        # 1. 15 Customer Receipts
        for i in range(15):
            cust = customers[i % len(customers)]
            amount_cents = self.random.randint(15000, 450000)  # $150.00 to $4,500.00
            tx_date = self.base_date + timedelta(days=self.random.randint(1, 15))
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

        # 2. 15 Vendor Disbursements
        for i in range(15):
            vend = vendors[i % len(vendors)]
            amount_cents = self.random.randint(25000, 680000)  # $250.00 to $6,800.00
            inv_date = self.base_date + timedelta(days=self.random.randint(1, 10))
            pay_date = inv_date + timedelta(days=5)

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
                amount_cents=-amount_cents,  # Outward disbursement is negative on bank statement
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

    def _generate_net_of_fee_stripe_batches(self, count: int = 10):
        """Generate 10 Net-of-fee Stripe batches.

        Stripe standard card fee: 2.9% + $0.30 (30 cents).
        Gross revenue is recorded in ERP; net deposit hits Bank.
        Difference is precisely accounted for by gateway fee schedule.
        """
        for i in range(count):
            gross_cents = self.random.randint(8000, 320000)  # $80.00 to $3,200.00
            # 2.9% + 30 cents
            fee_cents = int(round(gross_cents * 0.029)) + 30
            net_cents = gross_cents - fee_cents

            order_date = self.base_date + timedelta(days=self.random.randint(5, 20))
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

            # ERP books full gross revenue at order time
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

    def _generate_split_bundled_batches(self, count: int = 5):
        """Generate 5 Split/bundled batch wire deposits (1 Bank line to N Gateway transactions)."""
        for i in range(count):
            batch_id = f"po_bundle_batch_{6000 + i}"
            settle_date = self.base_date + timedelta(days=self.random.randint(10, 25))
            num_txs = self.random.randint(2, 4)

            bundled_gtw_ids = []
            bundled_erp_ids = []
            total_net_cents = 0
            total_gross_cents = 0
            total_fee_cents = 0

            for j in range(num_txs):
                gross = self.random.randint(12000, 85000)  # $120.00 to $850.00
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

    def _generate_fx_and_alias_variants(self, count: int = 5):
        """Generate 5 FX Currency & Vendor Alias Variants.

        - 2 Multi-currency conversions (EUR/GBP -> USD)
        - 3 Vendor alias variations (e.g. AWS Cloud Dublin vs Amazon Web Services)
        """
        # Case 1: AWS Dublin EUR invoice -> USD bank disbursement
        inv_id_1 = self._next_inv_id()
        bnk_id_1 = self._next_bnk_id()
        erp_id_1 = self._next_erp_id()
        scen_id_1 = self._next_scen_id("SCEN-FX")

        eur_cents = 120000  # 1,200.00 EUR
        fx_rate_1 = 1.0850
        usd_cents_1 = int(round(eur_cents * fx_rate_1))  # 130200 = $1,302.00 USD
        dt_1 = self.base_date + timedelta(days=12)

        self.ap_invoices.append(APInvoice(
            id=inv_id_1,
            vendor_name="AWS Cloud Dublin",
            amount_cents=eur_cents,
            due_date=dt_1,
            currency="EUR",
            fx_rate=fx_rate_1,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_id_1,
            date=dt_1,
            amount_cents=-usd_cents_1,
            raw_description="INTL WIRE OUT EUR AWS EMEA SARL FX 1.0850",
            reference_code="FX-EUR-101",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_id_1,
            invoice_id=inv_id_1,
            gl_account_code="6010-CLOUD-INFRA",
            amount_cents=-usd_cents_1,
            customer_vendor_name="AMAZON WEB SERVICES",
            entry_date=dt_1,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_id_1,
            scenario_type=ScenarioType.TIMING_DIFFERENCE,
            risk_priority=RiskPriority.P2_MEDIUM,
            bank_line_id=bnk_id_1,
            gateway_tx_id=None,
            erp_entry_id=erp_id_1,
            invoice_id=inv_id_1,
            expected_status="FX_RESOLVED",
            variance_cents=0,
            explanation="EUR 1,200.00 invoice from 'AWS Cloud Dublin' converted to USD $1,302.00 at FX rate 1.0850, matched to canonical 'AMAZON WEB SERVICES'."
        ))

        # Case 2: Datadog GBP invoice -> USD settlement
        inv_id_2 = self._next_inv_id()
        bnk_id_2 = self._next_bnk_id()
        erp_id_2 = self._next_erp_id()
        scen_id_2 = self._next_scen_id("SCEN-FX")

        gbp_cents = 85000  # 850.00 GBP
        fx_rate_2 = 1.2800
        usd_cents_2 = int(round(gbp_cents * fx_rate_2))  # 108800 = $1,088.00 USD
        dt_2 = self.base_date + timedelta(days=14)

        self.ap_invoices.append(APInvoice(
            id=inv_id_2,
            vendor_name="DATADOG US",
            amount_cents=gbp_cents,
            due_date=dt_2,
            currency="GBP",
            fx_rate=fx_rate_2,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_id_2,
            date=dt_2,
            amount_cents=-usd_cents_2,
            raw_description="WIRE TRANSFER LONDON UK DATADOG INC GBP 850 FX 1.28",
            reference_code="FX-GBP-202",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_id_2,
            invoice_id=inv_id_2,
            gl_account_code="6020-SOFTWARE-SAAS",
            amount_cents=-usd_cents_2,
            customer_vendor_name="DATADOG",
            entry_date=dt_2,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_id_2,
            scenario_type=ScenarioType.TIMING_DIFFERENCE,
            risk_priority=RiskPriority.P2_MEDIUM,
            bank_line_id=bnk_id_2,
            gateway_tx_id=None,
            erp_entry_id=erp_id_2,
            invoice_id=inv_id_2,
            expected_status="FX_RESOLVED",
            variance_cents=0,
            explanation="GBP 850.00 invoice converted at 1.2800 to USD $1,088.00, vendor alias 'DATADOG US' matched to 'DATADOG'."
        ))

        # Case 3: Vendor Alias - Microsoft Azure
        inv_id_3 = self._next_inv_id()
        bnk_id_3 = self._next_bnk_id()
        erp_id_3 = self._next_erp_id()
        scen_id_3 = self._next_scen_id("SCEN-ALIAS")
        amt_3 = 450000  # $4,500.00
        dt_3 = self.base_date + timedelta(days=16)

        self.ap_invoices.append(APInvoice(
            id=inv_id_3,
            vendor_name="MSFT AZURE",
            amount_cents=amt_3,
            due_date=dt_3,
            currency="USD",
            fx_rate=1.0,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_id_3,
            date=dt_3,
            amount_cents=-amt_3,
            raw_description="ACH DEBIT MICROSOFT CORP CLOUD SERVICES",
            reference_code="ACH-MSFT-303",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_id_3,
            invoice_id=inv_id_3,
            gl_account_code="6010-CLOUD-INFRA",
            amount_cents=-amt_3,
            customer_vendor_name="MICROSOFT AZURE",
            entry_date=dt_3,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_id_3,
            scenario_type=ScenarioType.EXACT_MATCH,
            risk_priority=RiskPriority.P4_NORMAL,
            bank_line_id=bnk_id_3,
            gateway_tx_id=None,
            erp_entry_id=erp_id_3,
            invoice_id=inv_id_3,
            expected_status="MATCHED",
            variance_cents=0,
            explanation="Vendor alias 'MSFT AZURE' and bank descriptor 'MICROSOFT CORP' normalized and resolved to 'MICROSOFT AZURE'."
        ))

        # Case 4: Vendor Alias - Google Cloud Platform
        inv_id_4 = self._next_inv_id()
        bnk_id_4 = self._next_bnk_id()
        erp_id_4 = self._next_erp_id()
        scen_id_4 = self._next_scen_id("SCEN-ALIAS")
        amt_4 = 320000  # $3,200.00
        dt_4 = self.base_date + timedelta(days=18)

        self.ap_invoices.append(APInvoice(
            id=inv_id_4,
            vendor_name="GOOGLE IRELAND",
            amount_cents=amt_4,
            due_date=dt_4,
            currency="USD",
            fx_rate=1.0,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_id_4,
            date=dt_4,
            amount_cents=-amt_4,
            raw_description="DIRECT DEBIT GOOG CLOUD SERVICES REQ-404",
            reference_code="DD-GOOG-404",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_id_4,
            invoice_id=inv_id_4,
            gl_account_code="6010-CLOUD-INFRA",
            amount_cents=-amt_4,
            customer_vendor_name="GOOGLE CLOUD PLATFORM",
            entry_date=dt_4,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_id_4,
            scenario_type=ScenarioType.EXACT_MATCH,
            risk_priority=RiskPriority.P4_NORMAL,
            bank_line_id=bnk_id_4,
            gateway_tx_id=None,
            erp_entry_id=erp_id_4,
            invoice_id=inv_id_4,
            expected_status="MATCHED",
            variance_cents=0,
            explanation="Vendor alias 'GOOGLE IRELAND' and descriptor 'GOOG CLOUD' mapped to canonical 'GOOGLE CLOUD PLATFORM'."
        ))

        # Case 5: Vendor Alias - Snowflake Computing
        inv_id_5 = self._next_inv_id()
        bnk_id_5 = self._next_bnk_id()
        erp_id_5 = self._next_erp_id()
        scen_id_5 = self._next_scen_id("SCEN-ALIAS")
        amt_5 = 580000  # $5,800.00
        dt_5 = self.base_date + timedelta(days=20)

        self.ap_invoices.append(APInvoice(
            id=inv_id_5,
            vendor_name="SNOWFLAKE COMPUTING",
            amount_cents=amt_5,
            due_date=dt_5,
            currency="USD",
            fx_rate=1.0,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_id_5,
            date=dt_5,
            amount_cents=-amt_5,
            raw_description="ACH DISBURSEMENT SNOWFLAKE INC WAREHOUSE",
            reference_code="ACH-SNOW-505",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_id_5,
            invoice_id=inv_id_5,
            gl_account_code="6020-SOFTWARE-SAAS",
            amount_cents=-amt_5,
            customer_vendor_name="SNOWFLAKE",
            entry_date=dt_5,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_id_5,
            scenario_type=ScenarioType.EXACT_MATCH,
            risk_priority=RiskPriority.P4_NORMAL,
            bank_line_id=bnk_id_5,
            gateway_tx_id=None,
            erp_entry_id=erp_id_5,
            invoice_id=inv_id_5,
            expected_status="MATCHED",
            variance_cents=0,
            explanation="Vendor alias 'SNOWFLAKE COMPUTING' and statement 'SNOWFLAKE INC' resolved to canonical 'SNOWFLAKE'."
        ))

    def _generate_honest_anomalies(self, count: int = 10):
        """Generate 10 Quarantined honest anomalies covering edge cases and remaining taxonomy enums.

        1. Duplicate bank statement line (P1_HIGH)
        2. Duplicate ERP invoice entry (P1_HIGH)
        3. Missing settlement: Gateway charge succeeded but no bank deposit (P1_HIGH)
        4. Missing settlement: AP invoice marked paid but bank withdrawal never occurred (P1_HIGH)
        5. Unexplained mismatch: Discrepancy of $124.50 with no mathematical formula (P0_CRITICAL)
        6. Unexplained mismatch / unbooked bank wire: Inward bank deposit of $15,000 with no ERP record (P0_CRITICAL)
        7. Customer refund chargeback: Gateway -$150.00, Bank -$150.00, ERP credit memo (P2_MEDIUM)
        8. Customer refund offset: Partial return of $75.00 against an existing order (P2_MEDIUM)
        9. Tax difference: 8.25% sales tax collected on checkout but omitted from ERP revenue line (P1_HIGH)
        10. Timing difference: Transaction on month-end 2026-08-31 settling across reporting cutoff on 2026-09-02 (P2_MEDIUM)
        """
        # Anomaly 1: Duplicate Bank Statement Line (P1_HIGH)
        amt_dup1 = 175000  # $1,750.00
        dt_dup1 = self.base_date + timedelta(days=22)
        inv_dup1 = self._next_inv_id()
        bnk_dup1_a = self._next_bnk_id()
        bnk_dup1_b = self._next_bnk_id()  # duplicate
        erp_dup1 = self._next_erp_id()
        scen_dup1 = self._next_scen_id("SCEN-ANOM")

        self.ap_invoices.append(APInvoice(
            id=inv_dup1,
            vendor_name="Figma Design",
            amount_cents=amt_dup1,
            due_date=dt_dup1,
            currency="USD",
            fx_rate=1.0,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_dup1_a,
            date=dt_dup1,
            amount_cents=-amt_dup1,
            raw_description=f"ACH DEBIT FIGMA DESIGN {inv_dup1}",
            reference_code="REF-DUP-1",
            account_id="ACCT-OPERATING-01"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_dup1_b,
            date=dt_dup1,
            amount_cents=-amt_dup1,
            raw_description=f"ACH DEBIT FIGMA DESIGN {inv_dup1} (DUPLICATE POSTING)",
            reference_code="REF-DUP-1",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_dup1,
            invoice_id=inv_dup1,
            gl_account_code="2010-AP",
            amount_cents=-amt_dup1,
            customer_vendor_name="FIGMA DESIGN",
            entry_date=dt_dup1,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_dup1,
            scenario_type=ScenarioType.DUPLICATE,
            risk_priority=RiskPriority.P1_HIGH,
            bank_line_id=f"{bnk_dup1_a},{bnk_dup1_b}",
            gateway_tx_id=None,
            erp_entry_id=erp_dup1,
            invoice_id=inv_dup1,
            expected_status="DUPLICATE_QUARANTINED",
            variance_cents=amt_dup1,
            explanation=f"Bank posted duplicate disbursement {bnk_dup1_b} of {cents_to_display(amt_dup1)} for invoice {inv_dup1}."
        ))

        # Anomaly 2: Duplicate ERP Ledger Entry (P1_HIGH)
        amt_dup2 = 98000  # $980.00
        dt_dup2 = self.base_date + timedelta(days=23)
        inv_dup2 = self._next_inv_id()
        bnk_dup2 = self._next_bnk_id()
        erp_dup2_a = self._next_erp_id()
        erp_dup2_b = self._next_erp_id()  # duplicate booking
        scen_dup2 = self._next_scen_id("SCEN-ANOM")

        self.ap_invoices.append(APInvoice(
            id=inv_dup2,
            vendor_name="Slack Technologies",
            amount_cents=amt_dup2,
            due_date=dt_dup2,
            currency="USD",
            fx_rate=1.0,
            status="PAID"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_dup2,
            date=dt_dup2,
            amount_cents=-amt_dup2,
            raw_description=f"ACH OUTWARD PMT {inv_dup2} SLACK",
            reference_code="ACH-SLACK-2",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_dup2_a,
            invoice_id=inv_dup2,
            gl_account_code="2010-AP",
            amount_cents=-amt_dup2,
            customer_vendor_name="SLACK TECHNOLOGIES",
            entry_date=dt_dup2,
            doc_type="PAYMENT"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_dup2_b,
            invoice_id=inv_dup2,
            gl_account_code="2010-AP",
            amount_cents=-amt_dup2,
            customer_vendor_name="SLACK TECHNOLOGIES",
            entry_date=dt_dup2,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_dup2,
            scenario_type=ScenarioType.DUPLICATE,
            risk_priority=RiskPriority.P1_HIGH,
            bank_line_id=bnk_dup2,
            gateway_tx_id=None,
            erp_entry_id=f"{erp_dup2_a},{erp_dup2_b}",
            invoice_id=inv_dup2,
            expected_status="DUPLICATE_QUARANTINED",
            variance_cents=amt_dup2,
            explanation=f"ERP contains duplicate ledger entry {erp_dup2_b} for single bank disbursement of {cents_to_display(amt_dup2)}."
        ))

        # Anomaly 3: Missing Settlement (Gateway Succeeded, No Bank Line) (P1_HIGH)
        amt_miss1 = 145000  # $1,450.00
        dt_miss1 = self.base_date + timedelta(days=5)
        ord_miss1 = "ORD-MISS-3001"
        gtw_miss1 = self._next_gtw_id()
        erp_miss1 = self._next_erp_id()
        scen_miss1 = self._next_scen_id("SCEN-ANOM")

        self.gateway_txs.append(GatewayTransaction(
            id=gtw_miss1,
            order_id=ord_miss1,
            gross_amount_cents=amt_miss1,
            fee_cents=4235,
            tax_cents=0,
            net_amount_cents=amt_miss1 - 4235,
            payout_batch_id="po_orphaned_unsettled",
            status="succeeded"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_miss1,
            invoice_id=ord_miss1,
            gl_account_code="4000-REVENUE",
            amount_cents=amt_miss1,
            customer_vendor_name="ORPHAN CUSTOMER",
            entry_date=dt_miss1,
            doc_type="INVOICE"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_miss1,
            scenario_type=ScenarioType.MISSING_SETTLEMENT,
            risk_priority=RiskPriority.P1_HIGH,
            bank_line_id=None,
            gateway_tx_id=gtw_miss1,
            erp_entry_id=erp_miss1,
            invoice_id=None,
            expected_status="SETTLEMENT_MISSING",
            variance_cents=amt_miss1 - 4235,
            explanation=f"Gateway captured {cents_to_display(amt_miss1)} on {dt_miss1} but payout never credited to operating bank account."
        ))

        # Anomaly 4: Missing Settlement (AP Invoice Approved/Open, No Bank Outflow) (P1_HIGH)
        amt_miss2 = 210000  # $2,100.00
        dt_miss2 = self.base_date + timedelta(days=8)
        inv_miss2 = self._next_inv_id()
        erp_miss2 = self._next_erp_id()
        scen_miss2 = self._next_scen_id("SCEN-ANOM")

        self.ap_invoices.append(APInvoice(
            id=inv_miss2,
            vendor_name="Vercel Inc",
            amount_cents=amt_miss2,
            due_date=dt_miss2,
            currency="USD",
            fx_rate=1.0,
            status="OPEN"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_miss2,
            invoice_id=inv_miss2,
            gl_account_code="2010-AP",
            amount_cents=amt_miss2,
            customer_vendor_name="VERCEL INC",
            entry_date=dt_miss2,
            doc_type="INVOICE"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_miss2,
            scenario_type=ScenarioType.MISSING_SETTLEMENT,
            risk_priority=RiskPriority.P1_HIGH,
            bank_line_id=None,
            gateway_tx_id=None,
            erp_entry_id=erp_miss2,
            invoice_id=inv_miss2,
            expected_status="UNPAID_INVOICE",
            variance_cents=amt_miss2,
            explanation=f"AP Invoice {inv_miss2} for {cents_to_display(amt_miss2)} booked in ERP but pending bank wire settlement."
        ))

        # Anomaly 5: Unexplained Mismatch ($124.50 arbitrary drift) (P0_CRITICAL)
        amt_exp = 300000  # $3,000.00 expected
        amt_act = 287550  # $2,875.50 actual deposit ($124.50 missing)
        diff_cents = amt_exp - amt_act  # 12450 cents
        dt_unexp = self.base_date + timedelta(days=24)
        ord_unexp = "ORD-UNEXP-5001"
        gtw_unexp = self._next_gtw_id()
        bnk_unexp = self._next_bnk_id()
        erp_unexp = self._next_erp_id()
        scen_unexp = self._next_scen_id("SCEN-ANOM")

        self.gateway_txs.append(GatewayTransaction(
            id=gtw_unexp,
            order_id=ord_unexp,
            gross_amount_cents=amt_exp,
            fee_cents=0,
            tax_cents=0,
            net_amount_cents=amt_exp,
            payout_batch_id="po_corrupt_settle",
            status="succeeded"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_unexp,
            date=dt_unexp,
            amount_cents=amt_act,
            raw_description=f"INWARD DEPOSIT SETTLEMENT {ord_unexp} SHORTAGE",
            reference_code="REF-SHORT-5001",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_unexp,
            invoice_id=ord_unexp,
            gl_account_code="1010-CASH",
            amount_cents=amt_exp,
            customer_vendor_name="Acme Corp",
            entry_date=dt_unexp,
            doc_type="PAYMENT"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_unexp,
            scenario_type=ScenarioType.UNEXPLAINED_MISMATCH,
            risk_priority=RiskPriority.P0_CRITICAL,
            bank_line_id=bnk_unexp,
            gateway_tx_id=gtw_unexp,
            erp_entry_id=erp_unexp,
            invoice_id=None,
            expected_status="UNEXPLAINED_VARIANCE",
            variance_cents=diff_cents,
            explanation=f"Critical unexplained variance of {cents_to_display(diff_cents)} between bank deposit ({cents_to_display(amt_act)}) and ERP/Gateway ({cents_to_display(amt_exp)})."
        ))

        # Anomaly 6: Unbooked Bank Wire / Orphan Deposit (P0_CRITICAL)
        amt_orphan = 1500000  # $15,000.00
        dt_orphan = self.base_date + timedelta(days=25)
        bnk_orphan = self._next_bnk_id()
        scen_orphan = self._next_scen_id("SCEN-ANOM")

        self.bank_lines.append(BankStatementLine(
            id=bnk_orphan,
            date=dt_orphan,
            amount_cents=amt_orphan,
            raw_description="WIRE INWARD REF 883921 PRIVATE UNIDENTIFIED",
            reference_code="WIRE-UNKNOWN-883921",
            account_id="ACCT-OPERATING-01"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_orphan,
            scenario_type=ScenarioType.UNEXPLAINED_MISMATCH,
            risk_priority=RiskPriority.P0_CRITICAL,
            bank_line_id=bnk_orphan,
            gateway_tx_id=None,
            erp_entry_id=None,
            invoice_id=None,
            expected_status="UNBOOKED_DEPOSIT",
            variance_cents=amt_orphan,
            explanation=f"Unidentified bank wire of {cents_to_display(amt_orphan)} received with no matching ERP journal entry or customer billing record."
        ))

        # Anomaly 7: Customer Refund (P2_MEDIUM)
        amt_ref = 15000  # $150.00
        dt_ref = self.base_date + timedelta(days=26)
        ord_ref = "ORD-REF-7001"
        gtw_ref = self._next_gtw_id()
        bnk_ref = self._next_bnk_id()
        erp_ref = self._next_erp_id()
        scen_ref = self._next_scen_id("SCEN-ANOM")

        self.gateway_txs.append(GatewayTransaction(
            id=gtw_ref,
            order_id=ord_ref,
            gross_amount_cents=-amt_ref,
            fee_cents=0,
            tax_cents=0,
            net_amount_cents=-amt_ref,
            payout_batch_id="po_refund_batch_7001",
            status="refunded"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_ref,
            date=dt_ref,
            amount_cents=-amt_ref,
            raw_description=f"STRIPE CUSTOMER REFUND CHARGEBACK {ord_ref}",
            reference_code="REF-CHG-7001",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_ref,
            invoice_id=ord_ref,
            gl_account_code="4010-SALES-RETURNS",
            amount_cents=-amt_ref,
            customer_vendor_name="RETURN CUSTOMER",
            entry_date=dt_ref,
            doc_type="CREDIT_MEMO"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_ref,
            scenario_type=ScenarioType.REFUND,
            risk_priority=RiskPriority.P2_MEDIUM,
            bank_line_id=bnk_ref,
            gateway_tx_id=gtw_ref,
            erp_entry_id=erp_ref,
            invoice_id=None,
            expected_status="REFUND_MATCHED",
            variance_cents=0,
            explanation=f"Processed customer refund of {cents_to_display(amt_ref)} matching gateway return, bank deduction, and ERP credit memo."
        ))

        # Anomaly 8: Customer Partial Refund / Adjustment (P2_MEDIUM)
        amt_part_ref = 7500  # $75.00
        dt_part = self.base_date + timedelta(days=27)
        ord_part = "ORD-PART-8001"
        gtw_part = self._next_gtw_id()
        bnk_part = self._next_bnk_id()
        erp_part = self._next_erp_id()
        scen_part = self._next_scen_id("SCEN-ANOM")

        self.gateway_txs.append(GatewayTransaction(
            id=gtw_part,
            order_id=ord_part,
            gross_amount_cents=-amt_part_ref,
            fee_cents=0,
            tax_cents=0,
            net_amount_cents=-amt_part_ref,
            payout_batch_id="po_partial_8001",
            status="refunded"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_part,
            date=dt_part,
            amount_cents=-amt_part_ref,
            raw_description=f"MERCHANT PARTIAL CREDIT ADJUSTMENT {ord_part}",
            reference_code="REF-PART-8001",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_part,
            invoice_id=ord_part,
            gl_account_code="4010-SALES-RETURNS",
            amount_cents=-amt_part_ref,
            customer_vendor_name="PARTIAL RETURN CUSTOMER",
            entry_date=dt_part,
            doc_type="CREDIT_MEMO"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_part,
            scenario_type=ScenarioType.REFUND,
            risk_priority=RiskPriority.P2_MEDIUM,
            bank_line_id=bnk_part,
            gateway_tx_id=gtw_part,
            erp_entry_id=erp_part,
            invoice_id=None,
            expected_status="REFUND_MATCHED",
            variance_cents=0,
            explanation=f"Partial refund adjustment of {cents_to_display(amt_part_ref)} reconciled between gateway, bank debit, and ERP credit memo."
        ))

        # Anomaly 9: Tax Difference (P1_HIGH)
        gross_no_tax = 100000  # $1,000.00
        tax_cents = 8250  # 8.25% sales tax = $82.50
        gross_with_tax = gross_no_tax + tax_cents  # $1,082.50
        dt_tax = self.base_date + timedelta(days=28)
        ord_tax = "ORD-TAX-9001"
        gtw_tax = self._next_gtw_id()
        bnk_tax = self._next_bnk_id()
        erp_tax = self._next_erp_id()
        scen_tax = self._next_scen_id("SCEN-ANOM")

        self.gateway_txs.append(GatewayTransaction(
            id=gtw_tax,
            order_id=ord_tax,
            gross_amount_cents=gross_with_tax,
            fee_cents=0,
            tax_cents=tax_cents,
            net_amount_cents=gross_no_tax,
            payout_batch_id="po_tax_settle",
            status="succeeded"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_tax,
            date=dt_tax,
            amount_cents=gross_no_tax,
            raw_description=f"GATEWAY NET PAYOUT (TAX EXCLUDED) {ord_tax}",
            reference_code="REF-TAX-9001",
            account_id="ACCT-OPERATING-01"
        ))
        # ERP booked full amount including sales tax
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_tax,
            invoice_id=ord_tax,
            gl_account_code="4000-REVENUE",
            amount_cents=gross_with_tax,
            customer_vendor_name="TAXABLE CUSTOMER LLC",
            entry_date=dt_tax,
            doc_type="INVOICE"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_tax,
            scenario_type=ScenarioType.TAX_DIFFERENCE,
            risk_priority=RiskPriority.P1_HIGH,
            bank_line_id=bnk_tax,
            gateway_tx_id=gtw_tax,
            erp_entry_id=erp_tax,
            invoice_id=None,
            expected_status="TAX_EXPLAINED",
            variance_cents=tax_cents,
            explanation=f"Discrepancy of {cents_to_display(tax_cents)} explained by 8.25% state sales tax withheld by marketplace facilitator."
        ))

        # Anomaly 10: Timing Difference across Month-End Cutoff (P2_MEDIUM)
        amt_time = 350000  # $3,500.00
        dt_order_time = date(2026, 8, 31)  # Last day of August
        dt_settle_time = date(2026, 9, 2)   # Settled in September (across cutoff)
        ord_time = "ORD-TIMING-10001"
        gtw_time = self._next_gtw_id()
        bnk_time = self._next_bnk_id()
        erp_time = self._next_erp_id()
        scen_time = self._next_scen_id("SCEN-ANOM")

        self.gateway_txs.append(GatewayTransaction(
            id=gtw_time,
            order_id=ord_time,
            gross_amount_cents=amt_time,
            fee_cents=0,
            tax_cents=0,
            net_amount_cents=amt_time,
            payout_batch_id="po_cutoff_batch",
            status="succeeded"
        ))
        self.bank_lines.append(BankStatementLine(
            id=bnk_time,
            date=dt_settle_time,
            amount_cents=amt_time,
            raw_description=f"BATCH DEPOSIT CROSS-MONTH SETTLEMENT {ord_time}",
            reference_code="REF-CUTOFF-1001",
            account_id="ACCT-OPERATING-01"
        ))
        self.erp_entries.append(ERPLedgerEntry(
            id=erp_time,
            invoice_id=ord_time,
            gl_account_code="4000-REVENUE",
            amount_cents=amt_time,
            customer_vendor_name="END OF MONTH CLIENT",
            entry_date=dt_order_time,
            doc_type="INVOICE"
        ))
        self.ground_truth.append(GroundTruthRecord(
            scenario_id=scen_time,
            scenario_type=ScenarioType.TIMING_DIFFERENCE,
            risk_priority=RiskPriority.P2_MEDIUM,
            bank_line_id=bnk_time,
            gateway_tx_id=gtw_time,
            erp_entry_id=erp_time,
            invoice_id=None,
            expected_status="TIMING_IN_FLIGHT",
            variance_cents=0,
            explanation=f"Transaction initiated 2026-08-31 posted in ERP August close; bank deposit received 2026-09-02 (T+2 cross-period settlement)."
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

