"""
Generate a realistic multi-page PDF bank statement for testing.
Run: python generate_bank_statement.py
"""
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
