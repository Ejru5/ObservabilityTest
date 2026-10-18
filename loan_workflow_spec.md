# Loan Process Workflow — Project Specification

> Give this file to the LLM to recreate the **workflow layer only** (no backend API, no React UI).

---

## 1. Technology Stack

| Layer | Technology |
|---|---|
| Workflow runtime | `mistralai-workflows[mistralai] >=3.0.0,<4` |
| Durable execution | Temporal (managed by the SDK) |
| LLM / OCR | Mistral AI (`mistral-large-latest`, `mistral-ocr-latest`) |
| DB | SQLite (`loan_app.db`) via Python `sqlite3` |
| PDF generation | `reportlab` |
| Env management | `python-dotenv` |
| Package manager | `uv` (use `uv sync` / `uv run`) |
| Python | `>=3.12` |

---

## 2. Project Layout

```
my-loan-workflow/
├── pyproject.toml
├── .env
├── seed_db.py                  # Run once to populate the DB
├── generate_bank_statement.py  # Utility: create a sample PDF bank statement
├── loan_app.db                 # SQLite DB (auto-created by seed_db.py)
├── output/                     # Reports written here at runtime
└── src/
    ├── dev_worker.py           # File-watch auto-restart dev runner
    ├── discover.py             # Auto-discovers & registers all workflows
    └── workflows/
        ├── __init__.py
        ├── database.py         # SQLite helpers
        └── loan_workflow.py    # THE workflow
```

---

## 3. `pyproject.toml`

```toml
[project]
name = "loan-workflow"
version = "0.1.0"
description = "Loan Processing Workflow with Mistral AI"
requires-python = ">=3.12"
dependencies = [
    "mistralai>=1.0.0",
    "mistralai-workflows[mistralai]>=3.0.0,<4",
    "pydantic",
    "python-dotenv",
    "reportlab",
]

[dependency-groups]
dev = [
    "watchdog>=4.0",
    "ruff>=0.11",
]
```

---

## 4. `.env`

```env
MISTRAL_API_KEY=your_mistral_api_key_here
```

---

## 5. Database Layer

### 5.1 `src/workflows/database.py`

```python
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
```

---

### 5.2 `seed_db.py` (run once)

```python
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
```

---

## 6. Sample Bank Statement Generator

### `generate_bank_statement.py`

Generates a realistic multi-page PDF bank statement for testing. Uses `reportlab`.

Key parameters for the default test user (**John Doe**, account `1234567890`):

| Field | Value |
|---|---|
| Monthly salary | $8,500 |
| EMI deduction | $1,200 /month |
| Total credits (6 mo) | $52,500 |
| Total debits (6 mo) | $28,200 |
| Average balance | $15,340.50 |
| Existing loan | $45,000 |
| Risk flag | 1 bounced check (month 4) |

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import random
from datetime import datetime, timedelta


def generate_statement(filename, name, account_number, start_month):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("<b>GLOBAL STANDARD BANK</b>", styles['Heading1']))
    elements.append(Paragraph("<b>ACCOUNT STATEMENT</b>", styles['Heading2']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"<b>Account Holder:</b> {name}", styles['Normal']))
    elements.append(Paragraph(f"<b>Account Number:</b> {account_number}", styles['Normal']))
    elements.append(Paragraph(f"<b>Statement Period:</b> Past 6 Months", styles['Normal']))
    elements.append(Spacer(1, 20))

    monthly_salary = 8500.00
    emi_deduction  = 1200.00
    total_credits  = (monthly_salary * 6) + 1500.00
    total_debits   = (emi_deduction * 6) + (3500.00 * 6)

    elements.append(Paragraph(f"<b>Total Credits:</b> ${total_credits:,.2f}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Debits:</b> ${total_debits:,.2f}", styles['Normal']))
    elements.append(Paragraph(f"<b>Average Monthly Balance:</b> $15,340.50", styles['Normal']))
    elements.append(Paragraph(f"<b>Total EMIs Paid:</b> 6", styles['Normal']))
    elements.append(Paragraph(f"<b>Existing Loan Balance (Est):</b> $45,000.00", styles['Normal']))
    elements.append(Spacer(1, 20))

    data = [['Date', 'Description', 'Reference', 'Debit ($)', 'Credit ($)', 'Balance ($)']]
    current_balance = 10000.00
    base_date = datetime.now() - timedelta(days=180)

    for month in range(6):
        month_txns = []
        salary_date = base_date + timedelta(days=month*30 + 5)
        month_txns.append((salary_date, "TECH CORP SALARY", f"TXN-{random.randint(10000,99999)}", 0.0, monthly_salary))
        emi_date = base_date + timedelta(days=month*30 + 10)
        month_txns.append((emi_date, "AUTO LOAN EMI", f"REF-{random.randint(10000,99999)}", emi_deduction, 0.0))
        categories = ["GROCERY MART","GAS STATION","ONLINE STORE","COFFEE SHOP","UTILITIES","PHARMACY"]
        for _ in range(random.randint(65, 80)):
            d = base_date + timedelta(days=month*30 + random.randint(1,28))
            exp = round(random.uniform(5.0, 85.0), 2)
            month_txns.append((d, random.choice(categories), f"POS-{random.randint(100000,999999)}", exp, 0.0))
        if month == 3:
            bounce_date = base_date + timedelta(days=month*30 + 18)
            month_txns.append((bounce_date, "ACH RETURN FEE - INSUFFICIENT FUNDS", f"FEE-{random.randint(10000,99999)}", 35.00, 0.0))
        month_txns.sort(key=lambda x: x[0])
        for dt, desc, ref, debit, credit in month_txns:
            if credit > 0:
                current_balance += credit
                data.append([dt.strftime("%Y-%m-%d"), desc, ref, "", f"{credit:,.2f}", f"{current_balance:,.2f}"])
            elif debit > 0:
                current_balance -= debit
                data.append([dt.strftime("%Y-%m-%d"), desc, ref, f"{debit:,.2f}", "", f"{current_balance:,.2f}"])

    t = Table(data, colWidths=[70,180,80,70,70,70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("<b>Notes:</b> 1 check bounce reported in the last 6 months. High credit utilization on linked credit card.", styles['Normal']))
    doc.build(elements)
    print(f"Statement generated: {filename}")


if __name__ == "__main__":
    generate_statement("test_bank_statement.pdf", "John Doe", "1234567890", 1)
```

---

## 7. Workflow Infrastructure

### 7.1 `src/discover.py` — Auto-discover & start worker

```python
"""Auto-discover all workflow classes in src/workflows/ and start a worker."""
import asyncio, importlib, inspect, pkgutil, sys
from dotenv import load_dotenv

load_dotenv(override=True)

import mistralai.workflows as workflows
from mistralai.workflows.core.definition.workflow_definition import get_workflow_definition


def discover_workflows() -> list[type]:
    discovered = []
    package = importlib.import_module("workflows")
    for _, modname, ispkg in pkgutil.iter_modules(package.__path__, prefix="workflows."):
        if ispkg:
            continue
        module = importlib.import_module(modname)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, "__workflows_workflow_def"):
                discovered.append(obj)
    return discovered


async def main() -> None:
    discovered = discover_workflows()
    if not discovered:
        print("No workflows found in src/workflows/")
        sys.exit(1)
    names = [get_workflow_definition(wf).name for wf in discovered]
    print(f"Discovered {len(discovered)} workflow(s): {', '.join(names)}")
    await workflows.run_worker(discovered)


if __name__ == "__main__":
    asyncio.run(main())
```

---

### 7.2 `src/dev_worker.py` — File-watch auto-restart runner

```python
"""Watch src/ for .py changes and auto-restart the workflow worker."""
import os, signal, subprocess, sys, time
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

WATCH_DIR = os.path.dirname(__file__)
DEBOUNCE_SECONDS = 1.0


class _RestartHandler(FileSystemEventHandler):
    def __init__(self):
        self._last_trigger = 0.0
        self._needs_restart = False

    def on_any_event(self, event):
        if not event.src_path.endswith(".py"):
            return
        now = time.monotonic()
        if now - self._last_trigger < DEBOUNCE_SECONDS:
            return
        self._last_trigger = now
        self._needs_restart = True

    def consume_restart(self) -> bool:
        if self._needs_restart:
            self._needs_restart = False
            return True
        return False


def _start_worker() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "discover.py")])


def _stop_worker(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main() -> None:
    handler = _RestartHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_DIR, recursive=True)
    observer.start()
    proc = _start_worker()
    print(f"[dev] Worker started (pid {proc.pid}). Watching {WATCH_DIR}...")
    try:
        while True:
            time.sleep(0.3)
            if handler.consume_restart():
                print("[dev] Change detected, restarting worker...")
                _stop_worker(proc)
                proc = _start_worker()
            if proc.poll() is not None:
                print(f"[dev] Worker exited (code {proc.returncode}). Waiting for changes...")
                while not handler.consume_restart():
                    time.sleep(0.3)
                proc = _start_worker()
    except KeyboardInterrupt:
        print("\n[dev] Shutting down...")
        _stop_worker(proc)
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
```

---

### 7.3 `Makefile`

```makefile
.PHONY: start-worker seed-db

## Install dependencies
installdeps:
	uv sync

## Seed the SQLite database (run once)
seed-db:
	uv run python seed_db.py

## Start worker with file-watch auto-reload
start-worker:
	uv run python src/dev_worker.py
```

---

## 8. The Loan Workflow — `src/workflows/loan_workflow.py`

### 8.1 Data Models

```python
from pydantic import BaseModel
from datetime import date
from typing import Any, Dict, Optional

class WorkflowInput(BaseModel):
    name: str
    dob: date
    mobile: str
    email: str
    id_type: str          # "pan" or "aadhaar"
    id_number: str
    id_document: str      # URL or Mistral File ID
    loan_amount: float
    loan_type: str        # "personal","home","auto","business","education"
    loan_tenure: float    # years
    loan_purpose: str
    employment_type: str  # "salaried" or "self_employed"
    monthly_income: float
    bank_statement: str   # URL or Mistral File ID


class LoanContextState(BaseModel):
    """Accumulates results flowing through the pipeline."""
    user_input: WorkflowInput
    ocr_results: Dict[str, str] = {}
    validation_results: Dict[str, Any] = {}
    bank_details: Dict[str, Any] = {}
    risk_data: Dict[str, Any] = {}
    final_decision: Dict[str, Any] = {}
    report_path: Optional[str] = None
```

---

### 8.2 Activity Definitions

Each activity is decorated with `@workflows.activity()` and uses `Task` for real-time progress updates.

#### Activity: `extract_ocr_data`
- **Zone:** Entry & Core
- **Input:** `document_input: str` (URL or file ID), `doc_type: str`
- **Output:** `str` — full markdown text extracted from the document
- **Calls:** `client.ocr.process_async(model="mistral-ocr-latest", document=...)`
- **Task type tag:** `"agent-progress|OCR|Core"`

#### Activity: `validate_id_number`
- **Zone:** Entry
- **Input:** `id_text: str`, `expected_id: str`
- **Output:** `bool` — True if the ID number appears in the OCR text
- **Calls:** `client.chat.complete_async(model="mistral-large-latest", ...)` with prompt asking YES/NO
- **Task type tag:** `"agent-progress|IDValidator|Entry"`

#### Activity: `validate_person_details`
- **Zone:** Entry
- **Input:** `id_number, id_type, name, dob, mobile, email`
- **Output:** `dict` — `{found: bool, mismatched_fields: list, db_record: dict|None}`
- **DB call:** `get_person_by_id(id_number)` — cross-checks all 5 fields with 10% tolerance
- **Task type tag:** `"agent-progress|DBVerifier|Entry"`

#### Activity: `validate_account_linked`
- **Zone:** Entry
- **Input:** `id_number: str`
- **Output:** `dict` — `{linked: bool, accounts: list[dict]}`
- **DB call:** `get_bank_accounts_by_id(id_number)`
- **Task type tag:** `"agent-progress|AccountLinker|Entry"`

#### Activity: `extract_bank_details`
- **Zone:** Core
- **Input:** `bank_text: str`, `expected_name: str`, `id_number: str`
- **Output:** `dict` with keys: `name, account_number, monthly_income, average_balance, total_credits, total_debits, number_of_emi, existing_loan, salary_frequency, risk_flags`
- **Calls:** `client.chat.complete_async(response_format={"type":"json_object"})` — JSON extraction
- **Side-effect:** writes `output/{id_number}.json`
- **Task type tag:** `"agent-progress|FinancialExtractor|Core"`

#### Activity: `validate_bank_statement`
- **Zone:** Core
- **Input:** `account_number: str`, `extracted: dict`
- **Output:** `dict` — `{found: bool, discrepancies: list, db_statement: dict|None}`
- **DB call:** `get_bank_statement_by_account(account_number)`
- **Logic:** 10% numeric tolerance check on `total_credits, total_debits, average_balance, monthly_income`
- **Task type tag:** `"agent-progress|StatementValidator|Core"`

#### Activity: `calculate_risk_score`
- **Zone:** Core
- **Input:** `data: dict`, `id_number: str`
- **Output:** `dict` — original data + `{dti_ratio, foir, average_balance_ratio, income_stability_score, final_score (0-100)}`
- **Calls:** `client.chat.complete_async(response_format={"type":"json_object"})`
- **Side-effect:** updates `output/{id_number}.json`
- **Task type tag:** `"agent-progress|RiskAgent|Core"`

#### Activity: `make_approval_decision`
- **Zone:** Exit
- **Input:** `data: dict`, `id_number: str`, `loan_amount: float`
- **Output:** `dict` with `approval_decision, approval_reason, eligible_loan, approved_amount, requested_loan_amount`
- **Logic:**

| `final_score` | Decision | Eligible loan multiplier |
|---|---|---|
| >= 80 | **Approve** | income × 20 |
| 50–79 | **Conditional Approval** | income × 20 × 0.70 |
| < 50 | **Reject** | income × 20 × 0.40 |

- `approved_amount = min(eligible_loan, requested loan_amount)`
- **Task type tag:** `"agent-progress|Approver|Exit"`

#### Activity: `generate_pdf_report`
- **Zone:** Exit
- **Input:** `data: dict`, `original_form: dict`, `id_number: str`
- **Output:** `str` — path to the generated PDF (`output/{id_number}.pdf`)
- **Uses:** `reportlab.pdfgen.canvas`
- **Sections in PDF:** Personal Detail, Identity Detail, Loan Detail, Extracted Details & Ratios, Approval Detail
- **Task type tag:** `"agent-progress|ReportGenerator|Exit"`

---

### 8.3 Workflow Orchestration

```
@workflows.workflow.define(
    name="loan-processing-workflow",
    workflow_display_name="Loan Processing Workflow",
    workflow_description="Sequential automated loan processing pipeline."
)
class LoanProcessingWorkflow:
```

**Pipeline (sequential zones):**

```
ENTRY ZONE
  1. extract_ocr_data(id_document)          → id_text
  2. validate_id_number(id_text, id_number)
        └── if False → return {success:False, reason:"ID Mismatch"}
  3. validate_person_details(...)           → person_result
  4. validate_account_linked(id_number)     → account_result
        └── linked_account = accounts[0]

CORE ZONE
  5. extract_ocr_data(bank_statement)       → bank_text
  6. extract_bank_details(bank_text, ...)   → bank_details
  7. validate_bank_statement(account_number, bank_details) → stmt_result
        └── inject db_validation_notes + flags into bank_details
  8. calculate_risk_score(bank_details, id_number) → risk_data

EXIT ZONE
  9. make_approval_decision(risk_data, id_number, loan_amount) → final_result
 10. generate_pdf_report(final_result, form_dict, id_number)   → report_path

RETURN final_result dict
```

---

### 8.4 `Task` Progress Observability Pattern

Every activity wraps its logic in `Task` context manager for real-time UI streaming:

```python
from mistralai.workflows.core.task import Task

@workflows.activity()
async def some_activity(arg: str) -> dict:
    async with Task(type="agent-progress|AgentName|Zone", state={}) as task:
        await task.update_state({"status": "running", "input": "Doing X..."})
        # ... do work ...
        await task.update_state({"status": "completed", "output": "Done"})
        return result
```

**Zone values:** `Entry`, `Core`, `Exit`

**Task type format:** `"agent-progress|<AgentName>|<Zone>"`

---

## 9. `src/workflows/__init__.py`

```python
# Empty — marks the directory as a Python package
```

---

## 10. Run Commands

```bash
# 1. Install dependencies
uv sync

# 2. Set your API key
echo "MISTRAL_API_KEY=sk-..." > .env

# 3. Seed the SQLite database (first time only)
uv run python seed_db.py

# 4. Generate a sample bank statement PDF (optional, for testing)
uv run python generate_bank_statement.py

# 5. Start the workflow worker (with file-watch auto-reload)
uv run python src/dev_worker.py
# OR
make start-worker
```

---

## 11. Test Input Payload

Use this JSON to trigger the workflow from the Mistral platform or via API:

```json
{
  "name": "John Doe",
  "dob": "1990-05-15",
  "mobile": "9876543210",
  "email": "john.doe@email.com",
  "id_type": "pan",
  "id_number": "ABCDE1234F",
  "id_document": "https://your-public-url/id_document.pdf",
  "loan_amount": 150000,
  "loan_type": "personal",
  "loan_tenure": 3,
  "loan_purpose": "Home renovation",
  "employment_type": "salaried",
  "monthly_income": 8500,
  "bank_statement": "https://your-public-url/bank_statement.pdf"
}
```

> **Note:** `id_document` and `bank_statement` can be either a public HTTPS URL **or** a Mistral File ID (obtained via `client.files.upload(...)`).

---

## 12. Key Design Rules

1. **No `Mistral` client at module level** — always instantiate inside activities using `os.getenv("MISTRAL_API_KEY")`.
2. **All DB calls go inside activities**, not the workflow entrypoint (Temporal sandbox restriction).
3. **`output/` directory** is created with `os.makedirs("output", exist_ok=True)` inside each activity that writes files.
4. **`discover.py` auto-discovers** all classes with `__workflows_workflow_def` attribute — no manual registration needed.
5. **Each activity is independent** — it receives only primitive types or dicts as arguments (no shared objects across activity boundaries).
6. **`Task` state keys:** always include `status` (`"running"` | `"completed"`) and either `input` or `output` string for UI display.
