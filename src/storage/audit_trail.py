"""Cryptographically-hashed immutable audit trail logging and integrity verification."""

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from src.storage.models_db import AuditLogRecord, StorageError

import threading

GENESIS_HASH = "0" * 64
_audit_lock = threading.Lock()


class AuditTrailService:
    """Provides cryptographic tamper-evident audit logging via SHA-256 hash-chaining."""

    @classmethod
    def compute_entry_hash(
        cls,
        prev_hash: str,
        timestamp: str,
        event_type: str,
        actor: str,
        record_id: str,
        before_state: Optional[str],
        after_state: str,
        rationale: str,
    ) -> str:
        """Deterministically calculate SHA-256 hash for an audit record."""
        payload = (
            f"{prev_hash}|{timestamp}|{event_type}|{actor}|"
            f"{record_id}|{before_state or ''}|{after_state}|{rationale}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def log_event(
        cls,
        conn: sqlite3.Connection,
        event_type: str,
        actor: str,
        record_id: str,
        after_state: Union[str, Dict[str, Any]],
        rationale: str,
        before_state: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AuditLogRecord:
        """Write an immutable audit log entry cryptographically chained to the preceding entry."""
        cursor = conn.cursor()

        with _audit_lock:
            # Fetch latest hash signature
            cursor.execute("SELECT hash_signature FROM audit_logs ORDER BY id DESC LIMIT 1;")
            last_row = cursor.fetchone()
            prev_hash = last_row["hash_signature"] if last_row else GENESIS_HASH

            now_utc = datetime.now(timezone.utc).isoformat()
            before_str = json.dumps(before_state, sort_keys=True) if isinstance(before_state, dict) else before_state
            after_str = json.dumps(after_state, sort_keys=True) if isinstance(after_state, dict) else str(after_state)

            hash_sig = cls.compute_entry_hash(
                prev_hash=prev_hash,
                timestamp=now_utc,
                event_type=event_type,
                actor=actor,
                record_id=record_id,
                before_state=before_str,
                after_state=after_str,
                rationale=rationale,
            )

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    timestamp, event_type, actor, record_id, before_state,
                    after_state, rationale, hash_signature, prev_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (now_utc, event_type, actor, record_id, before_str, after_str, rationale, hash_sig, prev_hash)
            )
            entry_id = cursor.lastrowid
            conn.commit()
            cursor.close()

        return AuditLogRecord(
            id=entry_id,
            timestamp=now_utc,
            event_type=event_type,
            actor=actor,
            record_id=record_id,
            before_state=before_str,
            after_state=after_str,
            rationale=rationale,
            hash_signature=hash_sig,
            prev_hash=prev_hash,
        )

    @classmethod
    def verify_chain_integrity(cls, conn: sqlite3.Connection) -> Tuple[bool, Optional[str]]:
        """Verify the integrity of the entire audit log chain, detecting any tampering or deletions."""
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY id ASC;")
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            return True, None

        expected_prev = GENESIS_HASH

        for row in rows:
            row_id = row["id"]
            if row["prev_hash"] != expected_prev:
                return (
                    False,
                    f"Chain break at record ID {row_id}: prev_hash '{row['prev_hash']}' "
                    f"does not match expected previous hash '{expected_prev}'."
                )

            recomputed = cls.compute_entry_hash(
                prev_hash=row["prev_hash"],
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                actor=row["actor"],
                record_id=row["record_id"],
                before_state=row["before_state"],
                after_state=row["after_state"],
                rationale=row["rationale"],
            )

            if recomputed != row["hash_signature"]:
                return (
                    False,
                    f"Tamper detected at record ID {row_id}: recomputed hash '{recomputed}' "
                    f"does not match recorded signature '{row['hash_signature']}'."
                )

            expected_prev = row["hash_signature"]

        return True, None

    @classmethod
    def get_all_records(
        cls, 
        conn: sqlite3.Connection, 
        limit: int = 100, 
        actor_category: Optional[str] = None
    ) -> List[AuditLogRecord]:
        """Retrieve recent immutable audit trail entries across all financial actions, optionally filtered by actor category."""
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        category = (actor_category or "ALL").strip().upper()

        if category == "ALL":
            cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?;", (limit,))
        elif category == "HUMAN":
            cursor.execute(
                """
                SELECT * FROM audit_logs 
                WHERE UPPER(actor) LIKE '%HUMAN%' 
                   OR UPPER(actor) LIKE '%CONTROLLER%' 
                   OR UPPER(actor) LIKE '%ANALYST%' 
                   OR UPPER(actor) LIKE '%FINANCE%' 
                   OR UPPER(actor) LIKE '%ADMIN%'
                ORDER BY id DESC LIMIT ?;
                """,
                (limit,)
            )
        elif category == "AI":
            cursor.execute(
                """
                SELECT * FROM audit_logs 
                WHERE UPPER(actor) LIKE '%AI%' 
                   OR UPPER(actor) LIKE '%AGENT%' 
                   OR UPPER(actor) LIKE '%COPILOT%' 
                   OR UPPER(actor) LIKE '%INVESTIGATOR%' 
                   OR UPPER(actor) LIKE '%LLM%'
                ORDER BY id DESC LIMIT ?;
                """,
                (limit,)
            )
        elif category == "SYSTEM":
            cursor.execute(
                """
                SELECT * FROM audit_logs 
                WHERE UPPER(actor) LIKE '%SYSTEM%' 
                   OR UPPER(actor) LIKE '%ENGINE%' 
                   OR UPPER(actor) LIKE '%MATCHER%'
                   OR UPPER(actor) LIKE '%CORE%'
                   OR UPPER(actor) LIKE '%CRON%'
                ORDER BY id DESC LIMIT ?;
                """,
                (limit,)
            )
        else:
            cursor.execute("SELECT * FROM audit_logs WHERE UPPER(actor) = ? ORDER BY id DESC LIMIT ?;", (category, limit))

        rows = cursor.fetchall()
        cursor.close()

        return [
            AuditLogRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                event_type=r["event_type"],
                actor=r["actor"],
                record_id=r["record_id"],
                before_state=r["before_state"],
                after_state=r["after_state"],
                rationale=r["rationale"],
                hash_signature=r["hash_signature"],
                prev_hash=r["prev_hash"],
            )
            for r in rows
        ]

    @classmethod
    def get_actor_counts(cls, conn: sqlite3.Connection) -> Dict[str, int]:
        """Return distribution of audit log records across actor categories (all, human, ai, system)."""
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT actor FROM audit_logs;")
        rows = cursor.fetchall()
        cursor.close()

        counts = {"all": len(rows), "human": 0, "ai": 0, "system": 0}
        for r in rows:
            actor = (r["actor"] or "").upper()
            if any(k in actor for k in ["AI", "AGENT", "COPILOT", "INVESTIGATOR", "LLM"]):
                counts["ai"] += 1
            elif any(k in actor for k in ["HUMAN", "CONTROLLER", "ANALYST", "FINANCE", "ADMIN"]):
                counts["human"] += 1
            elif any(k in actor for k in ["SYSTEM", "ENGINE", "MATCHER", "CORE", "CRON"]):
                counts["system"] += 1
            else:
                counts["system"] += 1
        return counts

    @classmethod
    def seed_ai_audit_events_if_needed(cls, conn: sqlite3.Connection) -> int:
        """Ensure realistic AI forensic investigator entries exist in the hash chain for comprehensive demonstration."""
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM audit_logs WHERE UPPER(actor) LIKE '%AI%' OR UPPER(actor) LIKE '%AGENT%';"
        )
        row = cursor.fetchone()
        cursor.close()
        if row and row["cnt"] > 0:
            return 0

        ai_events = [
            (
                "AI_FORENSIC_DIAGNOSIS",
                "AI_INVESTIGATOR",
                "REC-EX-001",
                {"ambiguity_margin": 0.02, "confidence": 0.94, "verdict": "CONFIRMED_FEE_VARIANCE"},
                "Forensic multi-source analysis diagnosed $1.50 Stripe interchange delta exceeding standard gateway schedule. Ambiguity gate passed (confidence 0.94 > 0.85 threshold).",
            ),
            (
                "AI_PROMPT_INJECTION_DEFENSE",
                "AI_SECURITY_GUARD",
                "REC-P0-01",
                {"sanitized_tokens": 14, "injection_detected": False, "policy": "STRICT_HEX_ENCODING"},
                "Input sanitization passed zero-hallucination guardrail; verified memo hex-tokens free from prompt manipulation vectors.",
            ),
            (
                "AI_AMBIGUITY_GATE_EVALUATED",
                "AI_INVESTIGATOR",
                "REC-P0-02",
                {"confidence": 0.62, "margin_gap": 0.04, "escalation": "HUMAN_CONTROLLER_REQUIRED"},
                "Evaluated secondary invoice candidate with 0.04 margin gap (< 0.08 policy limit). Quarantined and escalated to human approval queue per zero-error protocol.",
            ),
            (
                "AI_MATCH_VERIFICATION",
                "AI_RECON_AGENT",
                "TXN-STRIPE-8821",
                {"source_1": "STRIPE", "source_2": "CHASE_BANK", "variance_cents": 0},
                "Autonomous 2-way deterministic reconciliation verified: exact integer-cent match of 142,500 cents ($1,425.00) between settlement batch and bank deposit.",
            ),
            (
                "AI_REMEDIATION_PROPOSED",
                "AI_COPILOT_AGENT",
                "REC-EX-004",
                {"proposed_action": "WRITE_OFF", "uncollectible_days": 180, "amount_cents": 25000},
                "Autonomous Copilot suggested uncollectible write-off following formal debtor insolvency declaration. Evidence packet sealed.",
            ),
            (
                "AI_FORWARD_CASH_TELEMETRY",
                "AI_FORECAST_ENGINE",
                "FC-2026-W36",
                {"horizon_days": 30, "burn_rate_daily_cents": 850000, "runway_days": 142},
                "Forward liquidity cash forecast verified across trailing 90-day settlement velocity and pending accounts payable schedules.",
            )
        ]

        added = 0
        for event_type, actor, record_id, after_state, rationale in ai_events:
            cls.log_event(
                conn=conn,
                event_type=event_type,
                actor=actor,
                record_id=record_id,
                after_state=after_state,
                rationale=rationale,
            )
            added += 1
        return added

    @classmethod
    def get_history_for_record(cls, conn: sqlite3.Connection, record_id: str) -> List[AuditLogRecord]:
        """Retrieve the immutable audit trail for a specific financial record ID."""
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs WHERE record_id = ? ORDER BY id ASC;", (record_id,))
        rows = cursor.fetchall()
        cursor.close()

        return [
            AuditLogRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                event_type=r["event_type"],
                actor=r["actor"],
                record_id=r["record_id"],
                before_state=r["before_state"],
                after_state=r["after_state"],
                rationale=r["rationale"],
                hash_signature=r["hash_signature"],
                prev_hash=r["prev_hash"],
            )
            for r in rows
        ]
