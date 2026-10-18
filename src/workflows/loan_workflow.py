"""
Loan Processing Workflow — Sequential automated pipeline.

Zones:
  ENTRY → OCR ID, validate ID, verify person, check accounts
  CORE  → OCR bank statement, extract financials, validate statement, risk score
  EXIT  → Approval decision, PDF report generation
"""
import json
import os
from datetime import date
from typing import Any, Dict, Optional

from mistralai.client import Mistral
from pydantic import BaseModel

import mistralai.workflows as workflows
from mistralai.workflows.core.task import Task

from workflows.database import (
    get_bank_accounts_by_id,
    get_bank_statement_by_account,
    get_person_by_id,
)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Activity Definitions
# ---------------------------------------------------------------------------

@workflows.activity()
async def extract_ocr_data(document_input: str, doc_type: str) -> str:
    """Extract text from a document (ID card or bank statement) via Mistral OCR."""
    async with Task(type=f"agent-progress|OCR|Core", state={}) as task:
        await task.update_state({"status": "running", "input": f"Extracting text from {doc_type} document..."})

        client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

        # Determine if the input is a URL or a file ID
        if document_input.startswith("http://") or document_input.startswith("https://"):
            document = {"type": "document_url", "document_url": document_input}
        else:
            document = {"type": "file_id", "file_id": document_input}

        ocr_response = await client.ocr.process_async(
            model="mistral-ocr-latest",
            document=document,
        )

        # Combine all page texts
        full_text = "\n\n".join(
            page.markdown for page in ocr_response.pages
        )

        await task.update_state({"status": "completed", "output": f"Extracted {len(full_text)} characters from {doc_type}"})
        return full_text


@workflows.activity()
async def validate_id_number(id_text: str, expected_id: str) -> bool:
    """Check if the expected ID number appears in the OCR-extracted text."""
    async with Task(type="agent-progress|IDValidator|Entry", state={}) as task:
        await task.update_state({"status": "running", "input": f"Validating ID number {expected_id} against extracted text..."})

        client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

        prompt = f"""You are a document validation assistant.
Given the following text extracted from an identity document, determine whether the ID number "{expected_id}" is present in the text.

--- EXTRACTED TEXT ---
{id_text}
--- END ---

Respond with exactly YES or NO. Nothing else."""

        response = await client.chat.complete_async(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response.choices[0].message.content.strip().upper()
        is_valid = "YES" in answer

        status_msg = "ID number FOUND in document" if is_valid else "ID number NOT FOUND in document"
        await task.update_state({"status": "completed", "output": status_msg})
        return is_valid


@workflows.activity()
async def validate_person_details(
    id_number: str,
    id_type: str,
    name: str,
    dob: str,
    mobile: str,
    email: str,
) -> dict:
    """Cross-check person details against the database."""
    async with Task(type="agent-progress|DBVerifier|Entry", state={}) as task:
        await task.update_state({"status": "running", "input": "Verifying person details against database..."})

        db_record = get_person_by_id(id_number)

        if not db_record:
            result = {"found": False, "mismatched_fields": [], "db_record": None}
            await task.update_state({"status": "completed", "output": "Person NOT found in database"})
            return result

        # Cross-check fields
        mismatched = []
        checks = {
            "name": (name.lower(), db_record["name"].lower()),
            "dob": (str(dob), str(db_record["dob"])),
            "mobile": (mobile, db_record["mobile"]),
            "email": (email.lower(), db_record["email"].lower()),
            "id_type": (id_type.lower(), db_record["id_type"].lower()),
        }

        for field, (provided, stored) in checks.items():
            if provided != stored:
                mismatched.append(field)

        result = {
            "found": True,
            "mismatched_fields": mismatched,
            "db_record": dict(db_record),
        }

        status_msg = f"Person found. Mismatches: {mismatched if mismatched else 'None'}"
        await task.update_state({"status": "completed", "output": status_msg})
        return result


@workflows.activity()
async def validate_account_linked(id_number: str) -> dict:
    """Check if the person has linked bank accounts in the database."""
    async with Task(type="agent-progress|AccountLinker|Entry", state={}) as task:
        await task.update_state({"status": "running", "input": f"Checking linked bank accounts for {id_number}..."})

        accounts = get_bank_accounts_by_id(id_number)

        result = {
            "linked": len(accounts) > 0,
            "accounts": accounts,
        }

        status_msg = f"Found {len(accounts)} linked account(s)" if accounts else "No linked accounts found"
        await task.update_state({"status": "completed", "output": status_msg})
        return result


@workflows.activity()
async def extract_bank_details(bank_text: str, expected_name: str, id_number: str) -> dict:
    """Extract structured financial details from bank statement text using LLM."""
    async with Task(type="agent-progress|FinancialExtractor|Core", state={}) as task:
        await task.update_state({"status": "running", "input": "Extracting financial details from bank statement..."})

        client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

        prompt = f"""You are a financial document analysis expert.
Extract the following information from this bank statement text and return it as a JSON object.

Account holder expected name: {expected_name}

Required JSON fields:
- "name": account holder name as shown in statement
- "account_number": bank account number
- "monthly_income": estimated monthly income (number)
- "average_balance": average monthly balance (number)
- "total_credits": total credits over the statement period (number)
- "total_debits": total debits over the statement period (number)
- "number_of_emi": number of EMI payments detected (integer)
- "existing_loan": estimated existing loan balance (number)
- "salary_frequency": "monthly", "bi-weekly", or "irregular"
- "risk_flags": list of any concerning patterns (bounced checks, irregular large withdrawals, etc.)

--- BANK STATEMENT TEXT ---
{bank_text}
--- END ---

Return ONLY the JSON object, no markdown formatting."""

        response = await client.chat.complete_async(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        extracted = json.loads(response.choices[0].message.content)

        # Write extracted data to output file
        os.makedirs("output", exist_ok=True)
        output_path = os.path.join("output", f"{id_number}.json")
        with open(output_path, "w") as f:
            json.dump(extracted, f, indent=2)

        await task.update_state({"status": "completed", "output": f"Extracted financial details, saved to {output_path}"})
        return extracted


@workflows.activity()
async def validate_bank_statement(account_number: str, extracted: dict) -> dict:
    """Validate extracted bank details against database records with 10% tolerance."""
    async with Task(type="agent-progress|StatementValidator|Core", state={}) as task:
        await task.update_state({"status": "running", "input": f"Validating bank statement for account {account_number}..."})

        db_statement = get_bank_statement_by_account(account_number)

        if not db_statement:
            result = {"found": False, "discrepancies": [], "db_statement": None}
            await task.update_state({"status": "completed", "output": "No database statement found for comparison"})
            return result

        # 10% tolerance check on numeric fields
        discrepancies = []
        numeric_fields = ["total_credits", "total_debits", "average_balance", "monthly_income"]

        for field in numeric_fields:
            extracted_val = extracted.get(field)
            db_val = db_statement.get(field)

            if extracted_val is not None and db_val is not None:
                try:
                    extracted_num = float(extracted_val)
                    db_num = float(db_val)
                    if db_num > 0:
                        diff_pct = abs(extracted_num - db_num) / db_num * 100
                        if diff_pct > 10:
                            discrepancies.append({
                                "field": field,
                                "extracted": extracted_num,
                                "database": db_num,
                                "difference_pct": round(diff_pct, 2),
                            })
                except (ValueError, TypeError):
                    discrepancies.append({"field": field, "error": "Could not compare values"})

        result = {
            "found": True,
            "discrepancies": discrepancies,
            "db_statement": dict(db_statement),
        }

        status_msg = f"Validation complete. Discrepancies: {len(discrepancies)}"
        await task.update_state({"status": "completed", "output": status_msg})
        return result


@workflows.activity()
async def calculate_risk_score(data: dict, id_number: str) -> dict:
    """Calculate a comprehensive risk score (0-100) using LLM analysis."""
    async with Task(type="agent-progress|RiskAgent|Core", state={}) as task:
        await task.update_state({"status": "running", "input": "Calculating risk score..."})

        client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

        prompt = f"""You are a loan risk assessment expert.
Given the following financial data, calculate a comprehensive risk score.

Financial Data:
{json.dumps(data, indent=2)}

Calculate and return a JSON object with ALL the original data fields PLUS these additional fields:
- "dti_ratio": Debt-to-Income ratio (total EMI / monthly income)
- "foir": Fixed Obligations to Income Ratio
- "average_balance_ratio": average balance relative to monthly income
- "income_stability_score": score from 0-100 based on salary frequency and consistency
- "final_score": overall risk score from 0-100 (higher = better/less risky)

Consider these factors for the final_score:
- Low DTI ratio is good (below 40% ideal)
- Regular salary frequency is good
- Higher average balance ratio is good
- Fewer risk flags is better
- More EMIs may indicate higher obligations
- Bounced checks or irregular patterns reduce score

Return ONLY the JSON object, no markdown formatting."""

        response = await client.chat.complete_async(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        risk_data = json.loads(response.choices[0].message.content)

        # Update the output JSON file
        os.makedirs("output", exist_ok=True)
        output_path = os.path.join("output", f"{id_number}.json")
        with open(output_path, "w") as f:
            json.dump(risk_data, f, indent=2)

        final_score = risk_data.get("final_score", 0)
        await task.update_state({"status": "completed", "output": f"Risk score calculated: {final_score}/100"})
        return risk_data


@workflows.activity()
async def make_approval_decision(data: dict, id_number: str, loan_amount: float) -> dict:
    """Make loan approval decision based on risk score."""
    async with Task(type="agent-progress|Approver|Exit", state={}) as task:
        await task.update_state({"status": "running", "input": "Making approval decision..."})

        final_score = data.get("final_score", 0)
        monthly_income = data.get("monthly_income", 0)

        try:
            monthly_income = float(monthly_income)
        except (ValueError, TypeError):
            monthly_income = 0

        try:
            final_score = float(final_score)
        except (ValueError, TypeError):
            final_score = 0

        # Decision logic based on score thresholds
        if final_score >= 80:
            decision = "Approve"
            eligible_loan = monthly_income * 20
            reason = f"Excellent risk profile (score: {final_score}). Strong financial indicators."
        elif final_score >= 50:
            decision = "Conditional Approval"
            eligible_loan = monthly_income * 20 * 0.70
            reason = f"Moderate risk profile (score: {final_score}). Additional conditions may apply."
        else:
            decision = "Reject"
            eligible_loan = monthly_income * 20 * 0.40
            reason = f"High risk profile (score: {final_score}). Does not meet minimum criteria."

        approved_amount = min(eligible_loan, loan_amount)

        result = {
            **data,
            "approval_decision": decision,
            "approval_reason": reason,
            "eligible_loan": eligible_loan,
            "approved_amount": approved_amount,
            "requested_loan_amount": loan_amount,
        }

        await task.update_state({"status": "completed", "output": f"Decision: {decision} | Approved: ${approved_amount:,.2f}"})
        return result


@workflows.activity()
async def generate_pdf_report(data: dict, original_form: dict, id_number: str) -> str:
    """Generate a comprehensive PDF loan report."""
    async with Task(type="agent-progress|ReportGenerator|Exit", state={}) as task:
        await task.update_state({"status": "running", "input": "Generating PDF report..."})

        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as pdf_canvas

        # --- PII Redaction ---
        redacted_id = f"{id_number[:4]}****{id_number[-1]}" if id_number else "N/A"
        redacted_name = f"{original_form.get('applicant_name', '')[0]}****" if original_form.get('applicant_name') else "N/A"
        redacted_account = f"****{data.get('account_number', '')[-4:]}" if data.get('account_number') else "N/A"
        # --- End PII Redaction ---

        os.makedirs("output", exist_ok=True)
        output_path = os.path.join("output", f"{id_number}.pdf")

        c = pdf_canvas.Canvas(output_path, pagesize=letter)
        width, height = letter
        y = height - 50

        def draw_section(title, items):
            nonlocal y
            if y < 100:
                c.showPage()
                y = height - 50
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, y, title)
            y -= 25
            c.setFont("Helvetica", 10)
            for key, value in items:
                if y < 50:
                    c.showPage()
                    y = height - 50
                    c.setFont("Helvetica", 10)
                c.drawString(70, y, f"{key}: {value}")
                y -= 18
                
        # --- Numeric Sanitization ---
        def sanitize_currency(value):
            if isinstance(value, str):
                value = value.replace(",", "")
            try:
                return float(value) if value else 0.0
            except (ValueError, TypeError):
                raise ValueError(f"Invalid numeric value: {value}")
        # --- End Numeric Sanitization ---
            y -= 10

        # Title
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, y, "LOAN APPLICATION REPORT")
        y -= 15
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Generated: {date.today().isoformat()}")
        y -= 30

        # Section 1: Personal Details
        draw_section("Personal Details", [
            ("Name", original_form.get("name", "N/A")),
            ("Date of Birth", str(original_form.get("dob", "N/A"))),
            ("Mobile", original_form.get("mobile", "N/A")),
            ("Email", original_form.get("email", "N/A")),
            ("Employment Type", original_form.get("employment_type", "N/A")),
            ("Monthly Income", f"${original_form.get('monthly_income', 0):,.2f}"),
        ])

        # Section 2: Identity Details
        draw_section("Identity Details", [
            ("ID Type", original_form.get("id_type", "N/A").upper()),
            ("ID Number", redacted_id),
            ("Applicant Name", redacted_name),
        ])

        # Section 3: Loan Details
        draw_section("Loan Details", [
            ("Loan Type", original_form.get("loan_type", "N/A").title()),
            ("Requested Amount", f"${original_form.get('loan_amount', 0):,.2f}"),
            ("Tenure", f"{original_form.get('loan_tenure', 0)} years"),
            ("Purpose", original_form.get("loan_purpose", "N/A")),
        ])

        # Section 4: Extracted Details & Ratios
        draw_section("Extracted Details & Ratios", [
            ("Total Credits", f"${sanitize_currency(data.get('total_credits', 0)):,.2f}" if data.get('total_credits') is not None else "N/A"),
            ("Total Debits", f"${sanitize_currency(data.get('total_debits', 0)):,.2f}" if data.get('total_debits') is not None else "N/A"),
            ("Average Balance", f"${sanitize_currency(data.get('average_balance', 0)):,.2f}" if data.get('average_balance') is not None else "N/A"),
            ("DTI Ratio", str(data.get("dti_ratio", "N/A"))),
            ("FOIR", str(data.get("foir", "N/A"))),
            ("Income Stability Score", str(data.get("income_stability_score", "N/A"))),
            ("Risk Score", f"{data.get('final_score', 'N/A')}/100"),
            ("Risk Flags", str(data.get("risk_flags", []))),
            ("Account Number", redacted_account),
        ])

        # Section 5: Approval Details
        draw_section("Approval Details", [
            ("Decision", data.get("approval_decision", "N/A")),
            ("Reason", data.get("approval_reason", "N/A")),
            ("Eligible Loan Amount", f"${data.get('eligible_loan', 0):,.2f}"),
            ("Approved Amount", f"${data.get('approved_amount', 0):,.2f}"),
            ("Requested Amount", f"${data.get('requested_loan_amount', 0):,.2f}"),
        ])

        c.save()

        await task.update_state({"status": "completed", "output": f"Report saved to {output_path}"})
        return output_path


# ---------------------------------------------------------------------------
# Workflow Orchestration
# ---------------------------------------------------------------------------

@workflows.workflow.define(
    name="loan-processing-workflow",
    workflow_display_name="Loan Processing Workflow",
    workflow_description="Sequential automated loan processing pipeline.",
)
class LoanProcessingWorkflow:

    @workflows.workflow.entrypoint
    async def run(self, input_data: dict) -> dict:
        """Main entrypoint — sequential ENTRY → CORE → EXIT pipeline."""

        user_input = WorkflowInput(**input_data)
        form_dict = user_input.model_dump(mode="json")

        # ===================================================================
        # ENTRY ZONE
        # ===================================================================

        # 1. OCR the ID document
        id_text = await extract_ocr_data(user_input.id_document, "identity")

        # 2. Validate ID number in the extracted text
        id_valid = await validate_id_number(id_text, user_input.id_number)
        if not id_valid:
            return {
                "success": False,
                "reason": "ID Mismatch — the provided ID number was not found in the uploaded document.",
            }

        # 3. Validate person details against DB
        person_result = await validate_person_details(
            user_input.id_number,
            user_input.id_type,
            user_input.name,
            str(user_input.dob),
            user_input.mobile,
            user_input.email,
        )

        # 4. Check linked bank accounts
        account_result = await validate_account_linked(user_input.id_number)

        linked_account = None
        if account_result.get("linked") and account_result.get("accounts"):
            linked_account = account_result["accounts"][0]

        # ===================================================================
        # CORE ZONE
        # ===================================================================

        # 5. OCR the bank statement
        bank_text = await extract_ocr_data(user_input.bank_statement, "bank_statement")

        # 6. Extract financial details from bank statement
        bank_details = await extract_bank_details(bank_text, user_input.name, user_input.id_number)

        # 7. Validate bank statement against DB
        account_number = (
            linked_account["account_number"]
            if linked_account
            else bank_details.get("account_number", "")
        )
        stmt_result = await validate_bank_statement(account_number, bank_details)

        # Inject validation notes into bank_details
        if stmt_result.get("found"):
            bank_details["db_validation_notes"] = {
                "discrepancies": stmt_result.get("discrepancies", []),
                "db_statement_period": stmt_result.get("db_statement", {}).get("statement_period"),
            }
            if stmt_result.get("discrepancies"):
                bank_details.setdefault("risk_flags", [])
                if isinstance(bank_details["risk_flags"], list):
                    bank_details["risk_flags"].append(
                        f"{len(stmt_result['discrepancies'])} discrepancies found vs database records"
                    )

        # 8. Calculate risk score
        risk_data = await calculate_risk_score(bank_details, user_input.id_number)

        # ===================================================================
        # EXIT ZONE
        # ===================================================================

        # 9. Make approval decision
        final_result = await make_approval_decision(risk_data, user_input.id_number, user_input.loan_amount)

        # 10. Generate PDF report
        report_path = await generate_pdf_report(final_result, form_dict, user_input.id_number)

        final_result["report_path"] = report_path
        final_result["success"] = True
        final_result["person_validation"] = person_result
        final_result["account_validation"] = account_result

        return final_result
