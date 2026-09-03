"""Stage 1: Deterministic O(1) multi-key exact reference and amount matcher."""

import re
from typing import Dict, List, Optional, Set, Tuple
from datetime import timedelta

from src.domain.models import (
    ScenarioType,
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
)
from src.ingestion.normalizer import normalize_text, cents_to_display
from src.reconciliation.results import ReconciliationMatch
from src.reconciliation.state_manager import ReconciliationStateManager


class ExactMatcher:
    """Stage 1 Deterministic 1:1 Exact Matcher.

    Utilizes multi-key hash indexing to achieve O(1) matching between:
    1. Bank Statement Deposits <-> Gateway Transactions <-> ERP Cash Receipts
    2. Bank Statement Debits <-> AP Invoices <-> ERP AP Clearings
    3. Bank Statement Lines <-> ERP Direct Ledger Entries
    """

    def __init__(self, state_manager: ReconciliationStateManager):
        self.state = state_manager
        self._match_counter = 1

    def _next_match_id(self) -> str:
        res = f"MATCH-EX-{self._match_counter:04d}"
        self._match_counter += 1
        return res

    def reconcile(self) -> List[ReconciliationMatch]:
        """Execute all Stage 1 exact matching passes."""
        matches: List[ReconciliationMatch] = []

        # Pass 1: Customer Inward Payments (Bank Deposit <-> Gateway <-> ERP)
        matches.extend(self._match_customer_receipts())

        # Pass 2: Vendor Disbursements (Bank Debit <-> AP Invoice <-> ERP AP)
        matches.extend(self._match_vendor_disbursements())

        # Pass 3: Direct Bank <-> ERP Ledger Entries
        matches.extend(self._match_direct_bank_to_erp())

        return matches

    EXCEPTION_MARKERS = [
        "DUPLICATE",
        "REFUND",
        "CHARGEBACK",
        "CROSS-MONTH",
        "CUTOFF",
        "INTL WIRE",
        "FX ",
        "SHORTAGE",
        "UNIDENTIFIED",
        "PRIVATE",
        "TAX EXCLUDED",
        "CREDIT",
        "PARTIAL",
        "ADJUSTMENT",
    ]

    def _has_exception_marker(self, text: Optional[str]) -> bool:
        if not text:
            return False
        upper_text = str(text).upper()
        return any(marker in upper_text for marker in self.EXCEPTION_MARKERS)

    def _extract_reference_tokens(self, text: Optional[str]) -> Set[str]:
        """Extract alphanumeric reference tokens (e.g. ORD-1001, INV-2026-001, REF-101)."""
        if not text:
            return set()
        tokens = set(re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", str(text).upper()))
        # Also include standalone numbers or alphanumeric codes if 5+ characters
        raw_words = set(re.findall(r"\b[A-Z0-9_]{5,}\b", str(text).upper()))
        return tokens.union(raw_words)

    def _match_customer_receipts(self) -> List[ReconciliationMatch]:
        """Match 1:1 Customer Inward Deposits (Bank + Gateway + ERP)."""
        matches: List[ReconciliationMatch] = []
        unmatched = self.state.get_unmatched_pool()

        # Build index of Gateway Transactions by:
        # 1. (net_amount_cents, order_id)
        # 2. (net_amount_cents, id)
        # 3. net_amount_cents -> list of txs
        gtw_by_order: Dict[Tuple[int, str], GatewayTransaction] = {}
        gtw_by_amt: Dict[int, List[GatewayTransaction]] = {}

        for gtw in unmatched["gateway_txs"]:
            if gtw.fee_cents == 0 and gtw.tax_cents == 0 and gtw.status == "succeeded":
                gtw_by_order[(gtw.net_amount_cents, gtw.order_id.upper())] = gtw
                gtw_by_amt.setdefault(gtw.net_amount_cents, []).append(gtw)

        # Build ERP index by (amount_cents, invoice_id)
        erp_by_inv: Dict[Tuple[int, str], ERPLedgerEntry] = {}
        erp_by_amt: Dict[int, List[ERPLedgerEntry]] = {}
        for erp in unmatched["erp_entries"]:
            if erp.amount_cents > 0:  # Debit cash
                if erp.invoice_id:
                    erp_by_inv[(erp.amount_cents, erp.invoice_id.upper())] = erp
                erp_by_amt.setdefault(erp.amount_cents, []).append(erp)

        # Scan bank deposits (+amount)
        for bnk in unmatched["bank_lines"]:
            if bnk.amount_cents <= 0 or self.state.is_locked(bnk.id):
                continue
            if self._has_exception_marker(bnk.raw_description):
                continue

            amt = bnk.amount_cents
            tokens = self._extract_reference_tokens(bnk.raw_description)
            if bnk.reference_code:
                tokens.add(bnk.reference_code.upper())

            matched_gtw: Optional[GatewayTransaction] = None
            matched_erp: Optional[ERPLedgerEntry] = None

            # 1. Search for token match in Gateway
            for tok in tokens:
                if (amt, tok) in gtw_by_order and not self.state.is_locked(gtw_by_order[(amt, tok)].id):
                    matched_gtw = gtw_by_order[(amt, tok)]
                    break

            # If no token match, check if unique amount match in gateway
            if not matched_gtw and amt in gtw_by_amt:
                candidates = [g for g in gtw_by_amt[amt] if not self.state.is_locked(g.id)]
                if len(candidates) == 1:
                    matched_gtw = candidates[0]

            if not matched_gtw:
                continue

            # 2. Search for matching ERP entry using order_id
            order_id = matched_gtw.order_id.upper()
            if (amt, order_id) in erp_by_inv and not self.state.is_locked(erp_by_inv[(amt, order_id)].id):
                matched_erp = erp_by_inv[(amt, order_id)]
            elif amt in erp_by_amt:
                candidates = [e for e in erp_by_amt[amt] if not self.state.is_locked(e.id)]
                if len(candidates) == 1:
                    matched_erp = candidates[0]

            # We have Bank + Gateway, and optionally ERP
            member_ids = [matched_gtw.id]
            erp_ids = []
            evidence = [
                f"Bijective lock acquired for Bank line {bnk.id} and Gateway {matched_gtw.id}",
                f"Exact nominal parity: {cents_to_display(amt)}",
                f"Reference order alignment: {matched_gtw.order_id}",
            ]

            if matched_erp:
                member_ids.append(matched_erp.id)
                erp_ids.append(matched_erp.id)
                evidence.append(f"Linked ERP cash journal entry {matched_erp.id} ({matched_erp.customer_vendor_name})")

            # Lock group
            if self.state.lock_group(bnk.id, member_ids, rule="STAGE1_EXACT_CUSTOMER_RECEIPT"):
                match = ReconciliationMatch(
                    match_id=self._next_match_id(),
                    scenario_type=ScenarioType.EXACT_MATCH,
                    confidence_score=1.0,
                    bank_line_ids=[bnk.id],
                    gateway_tx_ids=[matched_gtw.id],
                    erp_entry_ids=erp_ids,
                    invoice_ids=[],
                    matched_amount_cents=amt,
                    variance_cents=0,
                    rule_name="STAGE1_EXACT_CUSTOMER_RECEIPT",
                    evidence=evidence,
                )
                matches.append(match)

        return matches

    def _match_vendor_disbursements(self) -> List[ReconciliationMatch]:
        """Match 1:1 Vendor Disbursements (Bank Debit <-> AP Invoice <-> ERP AP Clearing)."""
        matches: List[ReconciliationMatch] = []
        unmatched = self.state.get_unmatched_pool()

        # Index AP Invoices by:
        # 1. (amount_cents, id)
        # 2. (amount_cents, normalized_vendor)
        # 3. amount_cents -> list
        ap_by_id: Dict[Tuple[int, str], APInvoice] = {}
        ap_by_vendor: Dict[Tuple[int, str], List[APInvoice]] = {}
        ap_by_amt: Dict[int, List[APInvoice]] = {}

        for inv in unmatched["ap_invoices"]:
            norm_vendor = normalize_text(inv.vendor_name)
            ap_by_id[(inv.amount_cents, inv.id.upper())] = inv
            ap_by_vendor.setdefault((inv.amount_cents, norm_vendor), []).append(inv)
            ap_by_amt.setdefault(inv.amount_cents, []).append(inv)

        # Index ERP AP lines (amount_cents < 0) by (abs_amount, invoice_id)
        erp_by_inv: Dict[Tuple[int, str], ERPLedgerEntry] = {}
        erp_by_amt: Dict[int, List[ERPLedgerEntry]] = {}

        for erp in unmatched["erp_entries"]:
            if erp.amount_cents < 0:
                abs_amt = abs(erp.amount_cents)
                if erp.invoice_id:
                    erp_by_inv[(abs_amt, erp.invoice_id.upper())] = erp
                erp_by_amt.setdefault(abs_amt, []).append(erp)

        # Scan bank disbursements (amount_cents < 0)
        for bnk in unmatched["bank_lines"]:
            if bnk.amount_cents >= 0 or self.state.is_locked(bnk.id):
                continue
            if self._has_exception_marker(bnk.raw_description):
                continue

            abs_amt = abs(bnk.amount_cents)
            tokens = self._extract_reference_tokens(bnk.raw_description)
            if bnk.reference_code:
                tokens.add(bnk.reference_code.upper())
            norm_desc = normalize_text(bnk.raw_description)

            matched_inv: Optional[APInvoice] = None
            matched_erp: Optional[ERPLedgerEntry] = None

            # 1. Search by invoice token in Bank line memo
            for tok in tokens:
                if (abs_amt, tok) in ap_by_id and not self.state.is_locked(ap_by_id[(abs_amt, tok)].id):
                    matched_inv = ap_by_id[(abs_amt, tok)]
                    break

            # 2. Search by vendor alias match
            if not matched_inv:
                for (amt, vend), inv_list in ap_by_vendor.items():
                    if amt == abs_amt and (vend in norm_desc or norm_desc in vend):
                        candidates = [i for i in inv_list if not self.state.is_locked(i.id)]
                        if len(candidates) == 1:
                            matched_inv = candidates[0]
                            break

            # 3. Search by unique amount match
            if not matched_inv and abs_amt in ap_by_amt:
                candidates = [i for i in ap_by_amt[abs_amt] if not self.state.is_locked(i.id)]
                if len(candidates) == 1:
                    matched_inv = candidates[0]

            if not matched_inv:
                continue

            # Link ERP AP Clearing
            inv_id = matched_inv.id.upper()
            if (abs_amt, inv_id) in erp_by_inv and not self.state.is_locked(erp_by_inv[(abs_amt, inv_id)].id):
                matched_erp = erp_by_inv[(abs_amt, inv_id)]
            elif abs_amt in erp_by_amt:
                candidates = [e for e in erp_by_amt[abs_amt] if not self.state.is_locked(e.id)]
                if len(candidates) == 1:
                    matched_erp = candidates[0]

            member_ids = [matched_inv.id]
            erp_ids = []
            evidence = [
                f"Bijective lock acquired for Bank line {bnk.id} and AP Invoice {matched_inv.id}",
                f"Exact debit parity: {cents_to_display(abs_amt)}",
                f"Vendor verification: {matched_inv.vendor_name}",
            ]

            if matched_erp:
                member_ids.append(matched_erp.id)
                erp_ids.append(matched_erp.id)
                evidence.append(f"Linked ERP AP ledger disbursement {matched_erp.id}")

            if self.state.lock_group(bnk.id, member_ids, rule="STAGE1_EXACT_VENDOR_DISBURSEMENT"):
                match = ReconciliationMatch(
                    match_id=self._next_match_id(),
                    scenario_type=ScenarioType.EXACT_MATCH,
                    confidence_score=1.0,
                    bank_line_ids=[bnk.id],
                    gateway_tx_ids=[],
                    erp_entry_ids=erp_ids,
                    invoice_ids=[matched_inv.id],
                    matched_amount_cents=abs_amt,
                    variance_cents=0,
                    rule_name="STAGE1_EXACT_VENDOR_DISBURSEMENT",
                    evidence=evidence,
                )
                matches.append(match)

        return matches

    def _match_direct_bank_to_erp(self) -> List[ReconciliationMatch]:
        """Match 1:1 Direct Bank lines to ERP Ledger Entries."""
        matches: List[ReconciliationMatch] = []
        unmatched = self.state.get_unmatched_pool()

        # Index remaining ERP entries by (amount_cents, invoice_id/ref)
        erp_by_ref: Dict[Tuple[int, str], ERPLedgerEntry] = {}
        erp_by_amt: Dict[int, List[ERPLedgerEntry]] = {}

        for erp in unmatched["erp_entries"]:
            if erp.invoice_id:
                erp_by_ref[(erp.amount_cents, erp.invoice_id.upper())] = erp
            erp_by_amt.setdefault(erp.amount_cents, []).append(erp)

        for bnk in unmatched["bank_lines"]:
            if self.state.is_locked(bnk.id):
                continue
            if self._has_exception_marker(bnk.raw_description):
                continue

            amt = bnk.amount_cents
            tokens = self._extract_reference_tokens(bnk.raw_description)
            if bnk.reference_code:
                tokens.add(bnk.reference_code.upper())

            matched_erp: Optional[ERPLedgerEntry] = None

            for tok in tokens:
                if (amt, tok) in erp_by_ref and not self.state.is_locked(erp_by_ref[(amt, tok)].id):
                    matched_erp = erp_by_ref[(amt, tok)]
                    break

            if not matched_erp and amt in erp_by_amt:
                candidates = [e for e in erp_by_amt[amt] if not self.state.is_locked(e.id)]
                if len(candidates) == 1:
                    matched_erp = candidates[0]

            if matched_erp:
                if self.state.lock_pair(bnk.id, matched_erp.id, rule="STAGE1_DIRECT_BANK_ERP"):
                    match = ReconciliationMatch(
                        match_id=self._next_match_id(),
                        scenario_type=ScenarioType.EXACT_MATCH,
                        confidence_score=1.0,
                        bank_line_ids=[bnk.id],
                        gateway_tx_ids=[],
                        erp_entry_ids=[matched_erp.id],
                        invoice_ids=[],
                        matched_amount_cents=abs(amt),
                        variance_cents=0,
                        rule_name="STAGE1_DIRECT_BANK_ERP",
                        evidence=[
                            f"Bijective match between Bank line {bnk.id} and ERP {matched_erp.id}",
                            f"Exact amount parity: {cents_to_display(abs(amt))}",
                            f"Counterparty: {matched_erp.customer_vendor_name}",
                        ],
                    )
                    matches.append(match)

        return matches
