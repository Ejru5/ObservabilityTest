"""
Seed loan_app.db with sample test data.
Run: python seed_db.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from workflows.database import init_db, _get_connection


def seed():
    init_db()
    conn = _get_connection()
    cur = conn.cursor()

    # --- Persons ---
    persons = [
        ("ABCDE1234F",   "pan",    "John Doe",      "1990-05-15", "9876543210", "john.doe@email.com"),
        ("123456789012", "aadhaar","Jane Smith",     "1988-11-20", "9123456780", "jane.smith@email.com"),
        ("XYZAB5678G",   "pan",    "Robert Kumar",   "1995-03-10", "9988776655", "robert.kumar@email.com"),
    ]
    cur.executemany(
        "INSERT OR REPLACE INTO persons (id_number,id_type,name,dob,mobile,email) VALUES (?,?,?,?,?,?)",
        persons,
    )

    # --- Bank Accounts ---
    accounts = [
        ("1234567890", "ABCDE1234F",   "Global Standard Bank", "savings"),
        ("9876543210", "123456789012", "National Trust Bank",  "savings"),
        ("5566778899", "XYZAB5678G",   "City Union Bank",      "current"),
    ]
    cur.executemany(
        "INSERT OR REPLACE INTO bank_accounts (account_number,id_number,bank_name,account_type) VALUES (?,?,?,?)",
        accounts,
    )

    # --- Bank Statements ---
    # John Doe: monthly_salary=8500, emi=1200
    #   total_credits = (8500*6)+1500 = 52500
    #   total_debits  = (1200*6)+(3500*6) = 28200
    statements = [
        ("1234567890", "2025-H2", 52500.00, 28200.00, 15340.50, 6, 45000.00,  8500.00),
        ("9876543210", "2025-H2", 60000.00, 32000.00, 18500.00, 4, 30000.00, 10000.00),
        ("5566778899", "2025-H2", 90000.00, 55000.00, 22000.00, 8, 60000.00, 15000.00),
    ]
    cur.executemany(
        """INSERT OR REPLACE INTO bank_statements
           (account_number,statement_period,total_credits,total_debits,
            average_balance,number_of_emi,existing_loan,monthly_income)
           VALUES (?,?,?,?,?,?,?,?)""",
        statements,
    )

    conn.commit()
    conn.close()
    print("[OK] Seeded: 3 persons, 3 accounts, 3 statements")


if __name__ == "__main__":
    seed()
