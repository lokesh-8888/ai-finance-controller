"""Bijective atomic state manager preventing double-matching and phantom assignments."""

import threading
from typing import Any, Dict, List, Optional, Set

from src.domain.models import (
    BankStatementLine,
    GatewayTransaction,
    ERPLedgerEntry,
    APInvoice,
)


class ReconciliationStateManager:
    """Maintains strict bijective (1:1 and 1:N) state locking across financial entity pools.

    Guarantees:
    - Atomicity: Set locking is atomic; partial locks are impossible.
    - Bijectivity: A record can only belong to at most one match.
    - Zero Phantom Assignment: Locked entities are excluded from subsequent stages.
    """

    def __init__(
        self,
        bank_lines: Optional[List[BankStatementLine]] = None,
        gateway_txs: Optional[List[GatewayTransaction]] = None,
        erp_entries: Optional[List[ERPLedgerEntry]] = None,
        ap_invoices: Optional[List[APInvoice]] = None,
    ):
        self._lock = threading.Lock()
        self._locked_ids: Set[str] = set()
        self._associations: Dict[str, Set[str]] = {}
        self._lock_reasons: Dict[str, str] = {}

        # Entity registries for fast O(1) lookup
        self.bank_lines: Dict[str, BankStatementLine] = {}
        self.gateway_txs: Dict[str, GatewayTransaction] = {}
        self.erp_entries: Dict[str, ERPLedgerEntry] = {}
        self.ap_invoices: Dict[str, APInvoice] = {}

        if bank_lines:
            for b in bank_lines:
                self.bank_lines[b.id] = b
        if gateway_txs:
            for g in gateway_txs:
                self.gateway_txs[g.id] = g
        if erp_entries:
            for e in erp_entries:
                self.erp_entries[e.id] = e
        if ap_invoices:
            for a in ap_invoices:
                self.ap_invoices[a.id] = a

    def is_locked(self, record_id: str) -> bool:
        """Fast O(1) check whether an entity ID is already locked."""
        with self._lock:
            return record_id in self._locked_ids

    def lock_pair(self, id_a: str, id_b: str, rule: str = "EXACT_1_TO_1") -> bool:
        """Atomically locks a pair of entity records.

        Returns False if either entity is already locked (preventing double-counting).
        """
        with self._lock:
            if id_a in self._locked_ids or id_b in self._locked_ids:
                return False

            self._locked_ids.add(id_a)
            self._locked_ids.add(id_b)

            self._associations.setdefault(id_a, set()).add(id_b)
            self._associations.setdefault(id_b, set()).add(id_a)

            self._lock_reasons[id_a] = rule
            self._lock_reasons[id_b] = rule
            return True

    def lock_group(self, anchor_id: str, member_ids: List[str], rule: str = "BATCH_1_TO_MANY") -> bool:
        """Atomically locks an anchor entity with multiple member entities (1:N or M:N).

        Returns False if anchor or any member is already locked.
        """
        with self._lock:
            all_ids = [anchor_id] + member_ids
            for eid in all_ids:
                if eid in self._locked_ids:
                    return False

            for eid in all_ids:
                self._locked_ids.add(eid)
                self._lock_reasons[eid] = rule

            for mid in member_ids:
                self._associations.setdefault(anchor_id, set()).add(mid)
                self._associations.setdefault(mid, set()).add(anchor_id)

            return True

    def get_unmatched_pool(self) -> Dict[str, List[Any]]:
        """Returns the residual pool of currently unlocked records across all 4 sources."""
        with self._lock:
            return {
                "bank_lines": [b for b in self.bank_lines.values() if b.id not in self._locked_ids],
                "gateway_txs": [g for g in self.gateway_txs.values() if g.id not in self._locked_ids],
                "erp_entries": [e for e in self.erp_entries.values() if e.id not in self._locked_ids],
                "ap_invoices": [a for a in self.ap_invoices.values() if a.id not in self._locked_ids],
            }

    def get_entity(self, entity_id: str) -> Optional[Any]:
        """Retrieve an entity from any pool by its ID."""
        if entity_id in self.bank_lines:
            return self.bank_lines[entity_id]
        if entity_id in self.gateway_txs:
            return self.gateway_txs[entity_id]
        if entity_id in self.erp_entries:
            return self.erp_entries[entity_id]
        if entity_id in self.ap_invoices:
            return self.ap_invoices[entity_id]
        return None

    def get_locked_count(self) -> int:
        """Returns the total number of uniquely locked entity IDs."""
        with self._lock:
            return len(self._locked_ids)
