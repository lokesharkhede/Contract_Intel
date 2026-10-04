"""
memory.py — persistent storage for reviewed contracts.

This is the "persistent memory" piece of the stack. It's deliberately simple:
one SQLite database, two tables. It exists so that:
  1. A reviewed contract's clause data survives after the Streamlit session ends.
  2. You can chat with a past contract later without re-parsing the PDF.
  3. You can build a "review history" view across every contract processed.
"""

import sqlite3
import json
from datetime import datetime, timezone
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_name TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            overall_status TEXT,
            num_flags_high INTEGER,
            num_flags_medium INTEGER,
            num_flags_low INTEGER,
            summary TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clause_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER NOT NULL,
            clause_type TEXT,
            label TEXT,
            status TEXT,
            risk TEXT,
            issue TEXT,
            extracted_value TEXT,
            matched_text TEXT,
            FOREIGN KEY (contract_id) REFERENCES contracts(id)
        )
    """)
    conn.commit()
    conn.close()


def save_review(contract_name: str, clause_results: list[dict], summary: str) -> int:
    conn = get_connection()
    cur = conn.cursor()

    risk_counts = {"high": 0, "medium": 0, "low": 0}
    for c in clause_results:
        if c["status"] == "flagged" and c.get("risk") in risk_counts:
            risk_counts[c["risk"]] += 1

    overall_status = "flagged" if sum(risk_counts.values()) > 0 else "clean"

    cur.execute("""
        INSERT INTO contracts (contract_name, reviewed_at, overall_status,
                                num_flags_high, num_flags_medium, num_flags_low, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (contract_name, datetime.now(timezone.utc).isoformat(), overall_status,
          risk_counts["high"], risk_counts["medium"], risk_counts["low"], summary))
    contract_id = cur.lastrowid

    for c in clause_results:
        cur.execute("""
            INSERT INTO clause_results (contract_id, clause_type, label, status, risk,
                                         issue, extracted_value, matched_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (contract_id, c["clause_type"], c["label"], c["status"], c.get("risk"),
              c.get("issue"), str(c.get("extracted_value", "")), c.get("matched_text")))

    conn.commit()
    conn.close()
    return contract_id


def list_reviewed_contracts() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM contracts ORDER BY reviewed_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_clause_results(contract_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM clause_results WHERE contract_id = ?", (contract_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contract(contract_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
