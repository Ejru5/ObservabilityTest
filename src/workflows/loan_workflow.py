from datetime import date
import os

async def generate_pdf_report(data: dict, original_form: dict, id_number: str) -> str:
    """Generate a comprehensive PDF loan report."""

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as pdf_canvas

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
        ("ID Number", original_form.get("id_number", "N/A")),
    ])

    # Section 3: Loan Details
    draw_section("Loan Details", [
        ("Loan Type", original_form.get("loan_type", "N/A").title()),
        ("Requested Amount", f"${original_form.get('loan_amount', 0):,.2f}"),
        ("Tenure", f"{original_form.get('loan_tenure', 0)} years"),
        ("Purpose", original_form.get("loan_purpose", "N/A")),
    ])

    # Section 4: Extracted Details & Ratios
    def format_currency(value):
        if value is None:
            return 0.0
        if isinstance(value, str):
            try:
                return float(value.replace(',', ''))
            except ValueError:
                return 0.0
        return float(value)

    draw_section("Extracted Details & Ratios", [
        ("Total Credits", f"${format_currency(data.get('total_credits')):,.2f}" if data.get('total_credits') is not None else "N/A"),
        ("Total Debits", f"${format_currency(data.get('total_debits')):,.2f}" if data.get('total_debits') is not None else "N/A"),
        ("Average Balance", f"${format_currency(data.get('average_balance')):,.2f}" if data.get('average_balance') is not None else "N/A"),
        ("DTI Ratio", str(data.get("dti_ratio", "N/A"))),
        ("FOIR", str(data.get("foir", "N/A"))),
        ("Income Stability Score", str(data.get("income_stability_score", "N/A"))),
        ("Risk Score", f"{data.get('final_score', 'N/A')}/100"),
        ("Risk Flags", str(data.get("risk_flags", []))),
    ])

    # Section 5: Approval Details
    draw_section("Approval Details", [
        ("Decision", data.get("approval_decision", "N/A")),
        ("Reason", data.get("approval_reason", "N/A")),
    ])

    c.save()
    return output_path