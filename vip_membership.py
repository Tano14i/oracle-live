import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS vip_members (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    plan_code TEXT,
    plan_name TEXT,
    status TEXT NOT NULL,
    expires_at TEXT,
    joined_at TEXT,
    last_payment_at TEXT,
    last_invoice_payload TEXT,
    last_charge_id TEXT,
    invite_link TEXT,
    access_revoked_at TEXT,
    renewal_reminder_sent_at TEXT
);

CREATE TABLE IF NOT EXISTS vip_invoices (
    payload TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    plan_code TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    paid_at TEXT,
    charge_id TEXT
);
"""


class VipMembershipStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            self._ensure_column(conn, "vip_members", "renewal_reminder_sent_at", "TEXT")
            conn.commit()

    def create_invoice(self, payload: str, user_id: int, plan_code: str, plan_name: str, amount: int, currency: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vip_invoices (payload, user_id, plan_code, plan_name, amount, currency, status, created_at, paid_at, charge_id)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)
                """,
                (payload, user_id, plan_code, plan_name, amount, currency, now),
            )
            conn.commit()

    def get_invoice(self, payload: str):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM vip_invoices WHERE payload = ?", (payload,)).fetchone()
            return dict(row) if row else None

    def mark_invoice_paid(self, payload: str, charge_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE vip_invoices SET status = 'paid', paid_at = ?, charge_id = ? WHERE payload = ?",
                (now, charge_id, payload),
            )
            conn.commit()

    def activate_membership(
        self,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        plan_code: str,
        plan_name: str,
        expires_at: str,
        payload: str,
        charge_id: str,
        invite_link: Optional[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO vip_members (
                    user_id, username, first_name, plan_code, plan_name, status, expires_at,
                    joined_at, last_payment_at, last_invoice_payload, last_charge_id, invite_link,
                    access_revoked_at, renewal_reminder_sent_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    plan_code = excluded.plan_code,
                    plan_name = excluded.plan_name,
                    status = 'active',
                    expires_at = excluded.expires_at,
                    last_payment_at = excluded.last_payment_at,
                    last_invoice_payload = excluded.last_invoice_payload,
                    last_charge_id = excluded.last_charge_id,
                    invite_link = excluded.invite_link,
                    access_revoked_at = NULL,
                    renewal_reminder_sent_at = NULL
                """,
                (user_id, username, first_name, plan_code, plan_name, expires_at, now, now, payload, charge_id, invite_link),
            )
            conn.commit()

    def get_member(self, user_id: int):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM vip_members WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_expired_active_members(self):
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM vip_members WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_members_expiring_within(self, days: int):
        now = datetime.now(timezone.utc)
        upper = (now + timedelta(days=days)).isoformat()
        lower = now.isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM vip_members
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at > ?
                  AND expires_at <= ?
                  AND renewal_reminder_sent_at IS NULL
                """,
                (lower, upper),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_reminder_sent(self, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE vip_members SET renewal_reminder_sent_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            conn.commit()

    def mark_revoked(self, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE vip_members SET status = 'expired', access_revoked_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            conn.commit()

    def get_active_member_count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vip_members WHERE status = 'active'").fetchone()
            return int(row["count"]) if row else 0

    def get_paid_invoices_total(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM vip_invoices WHERE status = 'paid'").fetchone()
            return int(row["total"]) if row else 0

    def get_paid_invoices_count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vip_invoices WHERE status = 'paid'").fetchone()
            return int(row["count"]) if row else 0

    def get_total_member_count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vip_members").fetchone()
            return int(row["count"]) if row else 0

    def get_expired_member_count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vip_members WHERE status = 'expired'").fetchone()
            return int(row["count"]) if row else 0

    def get_pending_invoices_count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM vip_invoices WHERE status = 'pending'").fetchone()
            return int(row["count"]) if row else 0

    def get_recent_members(self, limit: int = 5):
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM vip_members
                ORDER BY COALESCE(last_payment_at, joined_at, expires_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]


