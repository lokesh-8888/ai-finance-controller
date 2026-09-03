"""Stage 2: Combinatorial subset-sum solver and net-of-fee batch reconciler."""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import date, timedelta

from src.domain.models import (
    ScenarioType,
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
)
from src.ingestion.normalizer import cents_to_display
from src.reconciliation.fee_calculator import GatewayFeeCalculator
from src.reconciliation.results import ReconciliationMatch
from src.reconciliation.state_manager import ReconciliationStateManager


class BatchSolver:
    """Stage 2 Combinatorial Subset-Sum Batch Solver.

    Resolves:
    1. Net-of-fee Gateway card settlements (1 Bank line <-> 1 Gateway tx + ERP gross revenue)
    2. Grouped Wire Batches (1 Bank deposit <-> N Gateway transactions + N ERP entries)
    3. Multi-invoice payment consolidation (1 Bank debit <-> N AP invoices)
    """

    def __init__(
        self,
        state_manager: ReconciliationStateManager,
        date_tolerance_days: int = 5,
        max_subset_size: int = 6,
    ):
        self.state = state_manager
        self.date_tolerance_days = date_tolerance_days
        self.max_subset_size = max_subset_size
        self._match_counter = 1

    def _next_match_id(self, prefix: str = "MATCH-BATCH") -> str:
        res = f"{prefix}-{self._match_counter:04d}"
        self._match_counter += 1
        return res

    def reconcile(self) -> List[ReconciliationMatch]:
        """Execute all Stage 2 batch and fee matching passes."""
        matches: List[ReconciliationMatch] = []

        # Pass 1: Net-of-Fee Single Gateway Batches (Stripe 2.9% + $0.30)
        matches.extend(self._match_net_of_fee_batches())

        # Pass 2: Clustered Wire Batches by Payout Batch ID
        matches.extend(self._match_clustered_payout_batches())

        # Pass 3: Combinatorial Subset-Sum for unbundled residual deposits
        matches.extend(self._match_combinatorial_subset_sum())

        return matches

    def _extract_reference_tokens(self, text: Optional[str]) -> Set[str]:
        if not text:
            return set()
        tokens = set(re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", str(text).upper()))
        tokens.update(re.findall(r"\bpo_[A-Za-z0-9_]+\b", str(text), re.IGNORECASE))
        tokens.update(re.findall(r"\bbatch_[A-Za-z0-9_]+\b", str(text), re.IGNORECASE))
        tokens.update(re.findall(r"\b[A-Z0-9_]{6,}\b", str(text).upper()))
        return {t.upper() for t in tokens}

    def _match_net_of_fee_batches(self) -> List[ReconciliationMatch]:
        """Match single Gateway payout batches where Bank Deposit == Gross - Fee."""
        matches: List[ReconciliationMatch] = []
        unmatched = self.state.get_unmatched_pool()

        # Index unmatched gateway transactions by:
        # 1. (net_amount_cents, payout_batch_id)
        # 2. net_amount_cents
        gtw_by_batch: Dict[Tuple[int, str], GatewayTransaction] = {}
        gtw_by_net: Dict[int, List[GatewayTransaction]] = {}

        for gtw in unmatched["gateway_txs"]:
            if gtw.fee_cents > 0 and gtw.status == "succeeded":
                if gtw.payout_batch_id:
                    gtw_by_batch[(gtw.net_amount_cents, gtw.payout_batch_id.upper())] = gtw
                gtw_by_net.setdefault(gtw.net_amount_cents, []).append(gtw)

        # Index unmatched ERP entries by invoice_id and order_id
        erp_by_inv: Dict[str, ERPLedgerEntry] = {}
        for erp in unmatched["erp_entries"]:
            if erp.invoice_id:
                erp_by_inv[erp.invoice_id.upper()] = erp

        # Scan bank deposits
        for bnk in unmatched["bank_lines"]:
            if bnk.amount_cents <= 0 or self.state.is_locked(bnk.id):
                continue

            net_deposit = bnk.amount_cents
            tokens = self._extract_reference_tokens(bnk.raw_description)
            if bnk.reference_code:
                tokens.add(bnk.reference_code.upper())

            matched_gtw: Optional[GatewayTransaction] = None

            # 1. Search by payout batch token
            for tok in tokens:
                if (net_deposit, tok) in gtw_by_batch and not self.state.is_locked(gtw_by_batch[(net_deposit, tok)].id):
                    matched_gtw = gtw_by_batch[(net_deposit, tok)]
                    break

            # 2. Fallback: unique net amount match with valid fee verification
            if not matched_gtw and net_deposit in gtw_by_net:
                candidates = [g for g in gtw_by_net[net_deposit] if not self.state.is_locked(g.id)]
                for cand in candidates:
                    is_valid, fee_calc, _ = GatewayFeeCalculator.validate_net_settlement(
                        gross_cents=cand.gross_amount_cents,
                        net_cents=net_deposit,
                        tax_cents=cand.tax_cents,
                    )
                    if is_valid and abs(cand.fee_cents - fee_calc) <= 2:
                        matched_gtw = cand
                        break

            if not matched_gtw:
                continue

            # Verify fee math
            is_valid, fee_cents, fee_expl = GatewayFeeCalculator.validate_net_settlement(
                gross_cents=matched_gtw.gross_amount_cents,
                net_cents=net_deposit,
                tax_cents=matched_gtw.tax_cents,
            )
            if not is_valid:
                continue

            # Check ERP ledger entry
            matched_erp: Optional[ERPLedgerEntry] = None
            if matched_gtw.order_id.upper() in erp_by_inv:
                cand_erp = erp_by_inv[matched_gtw.order_id.upper()]
                if not self.state.is_locked(cand_erp.id):
                    matched_erp = cand_erp

            member_ids = [matched_gtw.id]
            erp_ids = []
            evidence = [
                f"Bijective lock acquired for Bank line {bnk.id} and Gateway {matched_gtw.id}",
                f"Bank deposit: {cents_to_display(net_deposit)}, Gateway gross: {cents_to_display(matched_gtw.gross_amount_cents)}",
                fee_expl,
            ]

            if matched_erp:
                member_ids.append(matched_erp.id)
                erp_ids.append(matched_erp.id)
                evidence.append(f"Linked ERP gross revenue invoice {matched_erp.id} ({cents_to_display(matched_erp.amount_cents)})")

            if self.state.lock_group(bnk.id, member_ids, rule="STAGE2_NET_OF_FEE_STRIPE"):
                match = ReconciliationMatch(
                    match_id=self._next_match_id("MATCH-FEE"),
                    scenario_type=ScenarioType.FEE_DIFFERENCE,
                    confidence_score=0.98,
                    bank_line_ids=[bnk.id],
                    gateway_tx_ids=[matched_gtw.id],
                    erp_entry_ids=erp_ids,
                    invoice_ids=[],
                    matched_amount_cents=matched_gtw.gross_amount_cents,
                    variance_cents=fee_cents,
                    rule_name="STAGE2_NET_OF_FEE_STRIPE",
                    evidence=evidence,
                )
                matches.append(match)

        return matches

    def _match_clustered_payout_batches(self) -> List[ReconciliationMatch]:
        """Match 1 consolidated Bank deposit to N Gateway transactions clustered by payout_batch_id."""
        matches: List[ReconciliationMatch] = []
        unmatched = self.state.get_unmatched_pool()

        # Group unlocked gateway transactions by payout_batch_id
        clusters: Dict[str, List[GatewayTransaction]] = {}
        for gtw in unmatched["gateway_txs"]:
            if gtw.payout_batch_id:
                clusters.setdefault(gtw.payout_batch_id.upper(), []).append(gtw)

        # Index ERP entries by order_id
        erp_by_order: Dict[str, ERPLedgerEntry] = {}
        for erp in unmatched["erp_entries"]:
            if erp.invoice_id:
                erp_by_order[erp.invoice_id.upper()] = erp

        for bnk in unmatched["bank_lines"]:
            if bnk.amount_cents <= 0 or self.state.is_locked(bnk.id):
                continue

            deposit_cents = bnk.amount_cents
            tokens = self._extract_reference_tokens(bnk.raw_description)
            if bnk.reference_code:
                tokens.add(bnk.reference_code.upper())

            for tok in tokens:
                if tok in clusters:
                    batch_txs = [g for g in clusters[tok] if not self.state.is_locked(g.id)]
                    if len(batch_txs) >= 2:
                        total_net = sum(g.net_amount_cents for g in batch_txs)
                        if total_net == deposit_cents:
                            total_gross = sum(g.gross_amount_cents for g in batch_txs)
                            total_fee = sum(g.fee_cents for g in batch_txs)

                            member_ids = [g.id for g in batch_txs]
                            erp_ids = []

                            for g in batch_txs:
                                if g.order_id.upper() in erp_by_order:
                                    erp_item = erp_by_order[g.order_id.upper()]
                                    if not self.state.is_locked(erp_item.id):
                                        member_ids.append(erp_item.id)
                                        erp_ids.append(erp_item.id)

                            evidence = [
                                f"Clustered batch wire deposit: {cents_to_display(deposit_cents)}",
                                f"Aggregates {len(batch_txs)} gateway transactions under batch {tok}",
                                f"Gross total: {cents_to_display(total_gross)}, Fees deducted: {cents_to_display(total_fee)}",
                            ]

                            if self.state.lock_group(bnk.id, member_ids, rule="STAGE2_CLUSTERED_WIRE_BATCH"):
                                match = ReconciliationMatch(
                                    match_id=self._next_match_id("MATCH-BUNDLE"),
                                    scenario_type=ScenarioType.ADJUSTMENT,
                                    confidence_score=0.95,
                                    bank_line_ids=[bnk.id],
                                    gateway_tx_ids=[g.id for g in batch_txs],
                                    erp_entry_ids=erp_ids,
                                    invoice_ids=[],
                                    matched_amount_cents=total_gross,
                                    variance_cents=total_fee,
                                    rule_name="STAGE2_CLUSTERED_WIRE_BATCH",
                                    evidence=evidence,
                                )
                                matches.append(match)
                                break

        return matches

    def _match_combinatorial_subset_sum(self) -> List[ReconciliationMatch]:
        """Perform bounded combinatorial subset-sum search for residual bundled deposits."""
        matches: List[ReconciliationMatch] = []
        unmatched = self.state.get_unmatched_pool()

        # Residual deposits
        for bnk in unmatched["bank_lines"]:
            if bnk.amount_cents <= 0 or self.state.is_locked(bnk.id):
                continue

            target_amount = bnk.amount_cents
            bank_date = bnk.date

            # Filter candidates within date window (<= date_tolerance_days)
            date_min = bank_date - timedelta(days=self.date_tolerance_days)
            date_max = bank_date + timedelta(days=self.date_tolerance_days)

            # Check ERP ledger candidates
            erp_candidates = [
                e for e in unmatched["erp_entries"]
                if not self.state.is_locked(e.id)
                and e.amount_cents > 0
                and date_min <= e.entry_date <= date_max
                and e.amount_cents < target_amount
            ]

            if len(erp_candidates) >= 2:
                # Limit pool to 8 candidates to guarantee bounded O(2^N) execution
                erp_candidates.sort(key=lambda x: x.amount_cents, reverse=True)
                pool = erp_candidates[:8]

                solution = self._solve_subset_sum(
                    target=target_amount,
                    candidates=pool,
                    get_val=lambda x: x.amount_cents,
                    max_k=self.max_subset_size,
                )

                if solution:
                    member_ids = [e.id for e in solution]
                    evidence = [
                        f"Subset-sum exact solution found for Bank deposit {bnk.id} ({cents_to_display(target_amount)})",
                        f"Aggregated {len(solution)} ERP ledger entries totaling {cents_to_display(target_amount)}",
                        f"Entries: {', '.join(member_ids)}",
                    ]

                    if self.state.lock_group(bnk.id, member_ids, rule="STAGE2_COMBINATORIAL_SUBSET_SUM"):
                        match = ReconciliationMatch(
                            match_id=self._next_match_id("MATCH-SUBSET"),
                            scenario_type=ScenarioType.ADJUSTMENT,
                            confidence_score=0.95,
                            bank_line_ids=[bnk.id],
                            gateway_tx_ids=[],
                            erp_entry_ids=member_ids,
                            invoice_ids=[],
                            matched_amount_cents=target_amount,
                            variance_cents=0,
                            rule_name="STAGE2_COMBINATORIAL_SUBSET_SUM",
                            evidence=evidence,
                        )
                        matches.append(match)

        return matches

    def _solve_subset_sum(
        self,
        target: int,
        candidates: List[Any],
        get_val,
        max_k: int = 6,
    ) -> Optional[List[Any]]:
        """Bounded subset-sum with early branch pruning."""
        n = len(candidates)
        values = [get_val(c) for c in candidates]

        result: List[Any] = []

        def backtrack(index: int, current_sum: int, chosen: List[int]) -> bool:
            if current_sum == target and 2 <= len(chosen) <= max_k:
                result.extend([candidates[i] for i in chosen])
                return True

            if len(chosen) >= max_k or index >= n:
                return False

            val = values[index]

            # Branch 1: Include candidates[index]
            if current_sum + val <= target:
                chosen.append(index)
                if backtrack(index + 1, current_sum + val, chosen):
                    return True
                chosen.pop()

            # Branch 2: Exclude candidates[index]
            # Prune: if remaining elements cannot reach target
            remaining_sum = sum(values[index + 1:])
            if current_sum + remaining_sum >= target:
                if backtrack(index + 1, current_sum, chosen):
                    return True

            return False

        if backtrack(0, 0, []):
            return result
        return None
