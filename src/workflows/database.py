"""
Local SQLite database for loan application validation.

Tables:
  - persons        : KYC records keyed by ID number (PAN/Aadhaar)
  - bank_accounts  : Bank accounts linked to persons
  - bank_statements: Statement summaries per account
"""
import os
import sqlite3
from typing import Optional

# DB file lives at the project root
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "loan_app.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't already exist."""
    conn = _get_connection()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS persons (
            id_number  TEXT PRIMARY KEY,
            id_type    TEXT NOT NULL,
            name       TEXT NOT NULL,
            dob        TEXT NOT NULL,
            mobile     TEXT NOT NULL,
            email      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bank_accounts (
            account_number TEXT PRIMARY KEY,
            id_number      TEXT NOT NULL,
            bank_name      TEXT NOT NULL,
            account_type   TEXT DEFAULT 'savings',
            FOREIGN KEY (id_number) REFERENCES persons(id_number)
        );

        CREATE TABLE IF NOT EXISTS bank_statements (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            account_number   TEXT NOT NULL,
            statement_period TEXT NOT NULL,
            total_credits    REAL,
            total_debits     REAL,
            average_balance  REAL,
            number_of_emi    INTEGER DEFAULT 0,
            existing_loan    REAL DEFAULT 0,
            monthly_income   REAL,
            FOREIGN KEY (account_number) REFERENCES bank_accounts(account_number)
        );
    """)
    conn.commit()
    conn.close()


def get_person_by_id(id_number: str) -> Optional[dict]:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM persons WHERE id_number = ?", (id_number,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_bank_accounts_by_id(id_number: str) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM bank_accounts WHERE id_number = ?", (id_number,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bank_statement_by_account(account_number: str) -> Optional[dict]:
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM bank_statements WHERE account_number = ? ORDER BY id DESC LIMIT 1",
        (account_number,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
