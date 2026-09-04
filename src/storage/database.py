"""SQLite WAL connection manager, schema initialization, and transactional session handling."""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import threading
from typing import Generator, Optional, Union


class DatabaseManager:
    """Manages SQLite connections with Write-Ahead Logging (WAL) and atomic transactions."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            db_path = base_dir / "data" / "finance_controller.db"
        elif str(db_path) != ":memory:":
            db_path = Path(db_path)

        self.db_path = db_path
        self._is_memory = str(db_path) == ":memory:"

        if not self._is_memory:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self._local = threading.local()
        self._memory_conn: Optional[sqlite3.Connection] = None

        if self._is_memory:
            # Persistent memory connection for the lifetime of this manager instance
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._configure_connection(self._memory_conn)

        self.initialize_schema()

    def _configure_connection(self, conn: sqlite3.Connection):
        """Configure SQLite pragmas for high performance, WAL concurrency, and integrity."""
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if not self._is_memory:
            try:
                cursor.execute("PRAGMA journal_mode = WAL;")
            except sqlite3.DatabaseError:
                cursor.execute("PRAGMA journal_mode = DELETE;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()

    def _get_raw_connection(self) -> sqlite3.Connection:
        """Retrieve thread-local connection or memory connection with automatic corruption recovery."""
        if self._is_memory and self._memory_conn is not None:
            return self._memory_conn

        if not hasattr(self._local, "conn") or self._local.conn is None:
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
                self._configure_connection(conn)
            except sqlite3.DatabaseError:
                # If database disk image is malformed due to cross-process/OS collision,
                # unlink the corrupted files and reconnect cleanly
                if not self._is_memory and self.db_path:
                    for ext in ["", "-shm", "-wal"]:
                        p = Path(str(self.db_path) + ext)
                        if p.exists():
                            try:
                                p.unlink()
                            except Exception:
                                pass
                conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
                self._configure_connection(conn)
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional SQLite connection with auto-commit and rollback on error."""
        conn = self._get_raw_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def initialize_schema(self):
        """Idempotently construct all required application tables and indices."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Operational Exceptions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exceptions (
                    exception_id TEXT PRIMARY KEY,
                    scenario_type TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 2. Immutable Cryptographic Audit Log Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    before_state TEXT,
                    after_state TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    hash_signature TEXT NOT NULL,
                    prev_hash TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_record_id ON audit_logs(record_id);")

            # 3. Compensating Double-Entry Journal Entries Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL,
                    exception_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    debit_account TEXT,
                    credit_account TEXT,
                    debit_amount_cents INTEGER NOT NULL,
                    credit_amount_cents INTEGER NOT NULL,
                    memo TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_je_entry_id ON journal_entries(entry_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_je_exception_id ON journal_entries(exception_id);")

            # 4. Remediation Decision History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediation_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remediation_id TEXT UNIQUE NOT NULL,
                    exception_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    notes TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rem_exception_id ON remediation_records(exception_id);")
            cursor.close()

    def close(self):
        """Close managed database connections."""
        if self._memory_conn:
            self._memory_conn.close()
            self._memory_conn = None
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
