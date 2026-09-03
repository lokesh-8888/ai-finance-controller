"""Real-time multi-tier treasury cash position calculator operating with integer-cents math."""

import datetime as dt
from typing import List, Optional, Set

from src.domain.models import (
    APInvoice,
    BankStatementLine,
    ERPLedgerEntry,
    GatewayTransaction,
)
from src.forecasting.schemas import CashPosition
from src.reconciliation.results import ReconciliationMatch


class CashPositionCalculator:
    """Calculates ground-truth corporate liquidity across commercial banks, gateways, and AP/AR."""

    @classmethod
    def compute_position(
        cls,
        as_of_date: dt.date,
        opening_cash_cents: int = 0,
        bank_lines: Optional[List[BankStatementLine]] = None,
        gateway_txs: Optional[List[GatewayTransaction]] = None,
        ap_invoices: Optional[List[APInvoice]] = None,
        erp_entries: Optional[List[ERPLedgerEntry]] = None,
        reconciliation_matches: Optional[List[ReconciliationMatch]] = None,
    ) -> CashPosition:
        """Compute the multi-tier corporate liquidity snapshot as of a target calendar date."""
        bank_lines = bank_lines or []
        gateway_txs = gateway_txs or []
        ap_invoices = ap_invoices or []
        erp_entries = erp_entries or []
        matches = reconciliation_matches or []

        # Track IDs of entities matched / cleared in reconciliation
        reconciled_invoice_ids: Set[str] = set()
        reconciled_gateway_ids: Set[str] = set()
        reconciled_bank_ids: Set[str] = set()

        for m in matches:
            reconciled_invoice_ids.update(m.invoice_ids)
            reconciled_gateway_ids.update(m.gateway_tx_ids)
            reconciled_bank_ids.update(m.bank_line_ids)

        # 1. Settled Bank Cash: Opening Cash + sum of cleared bank movements up to as_of_date
        cleared_bank_movement = sum(
            b.amount_cents for b in bank_lines
            if b.date <= as_of_date
        )
        settled_cash = opening_cash_cents + cleared_bank_movement

        # 2. In-Flight Gateway Receivables: Succeeded payments awaiting T+2 settlement
        in_flight_gateway = 0
        for g in gateway_txs:
            if g.status == "succeeded":
                g_created = getattr(g, "created_date", None)
                g_settled = getattr(g, "settled_date", None)
                if g_created is not None:
                    if g_created <= as_of_date:
                        is_settled_in_bank = (
                            g_settled is not None
                            and g_settled <= as_of_date
                            and g.id in reconciled_gateway_ids
                        )
                        if not is_settled_in_bank:
                            in_flight_gateway += g.net_amount_cents
                else:
                    if g.id not in reconciled_gateway_ids:
                        in_flight_gateway += g.net_amount_cents

        # 3. Committed AP Obligations: Outstanding vendor invoices not yet disbursed in bank
        committed_ap = 0
        for inv in ap_invoices:
            # If not yet reconciled or disbursed on or before as_of_date
            if inv.id not in reconciled_invoice_ids:
                committed_ap += inv.amount_cents

        # 4. Unsettled AR Exposure: Invoiced customer revenue in ERP awaiting payment
        unsettled_ar = 0
        for e in erp_entries:
            if e.amount_cents > 0 and e.entry_date <= as_of_date:
                # Open customer receivables not yet cleared
                if not any(e.id in m.erp_entry_ids for m in matches):
                    unsettled_ar += e.amount_cents

        # 5. Adjusted Net Cash = Settled Cash + In-Flight Gateway - Committed AP
        adjusted_net_cash = settled_cash + in_flight_gateway - committed_ap

        return CashPosition(
            as_of_date=as_of_date,
            settled_cash_cents=settled_cash,
            in_flight_gateway_cents=in_flight_gateway,
            unsettled_ar_cents=unsettled_ar,
            committed_ap_cents=committed_ap,
            adjusted_net_cash_cents=adjusted_net_cash,
        )
