"""
PDF generation utilities
"""
from pathlib import Path
from typing import Dict, Any
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from datetime import datetime


def excel_to_pdf(excel_path: Path, pdf_path: Path) -> bool:
    """
    Convert Excel file to PDF using reportlab
    This is a simple conversion - preserves basic formatting
    """
    try:
        # For now, create a simple PDF from Excel data
        # In production, use more advanced libraries like python-pptx or similar
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # Load Excel
        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active

        # Create PDF
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        elements = []

        # Add title
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=14,
            textColor=colors.black,
            spaceAfter=30,
            alignment=1,  # Center
        )

        # Extract data from Excel and add to PDF
        # This is a simple implementation
        for row in ws.iter_rows(max_row=ws.max_row, max_col=ws.max_column, values_only=True):
            if row and any(row):
                text = " | ".join(str(cell) if cell else "" for cell in row)
                elements.append(Paragraph(text, styles["Normal"]))

        elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
        return True

    except Exception as e:
        print(f"Error converting to PDF: {e}")
        return False


def create_simple_invoice_pdf(pdf_path: Path, invoice_data: Dict[str, Any]) -> bool:
    """
    Create a simple invoice PDF from invoice data
    """
    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # Society header
        header_bold = ParagraphStyle(
            "HeaderBold",
            parent=styles["Normal"],
            fontSize=14,
            leading=18,
            textColor=colors.black,
            alignment=1,
            spaceAfter=4,
        )
        header_normal = ParagraphStyle(
            "HeaderNormal",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.black,
            alignment=1,
            spaceAfter=2,
        )
        elements.append(Paragraph("Weekend Ville Maintenance Co-Op. Society Ltd 24-25", header_bold))
        elements.append(Paragraph("Sr. No. 241/274/287/288/289, Mauje Jatede", header_normal))
        elements.append(Paragraph("Tal.- Mulshi, Dist.-Pune", header_normal))
        elements.append(Paragraph("Society Reg No : PNA/MSI/GNL/(O)/4350/FY 2021-2022 DATE : 24/08/2021", header_normal))
        elements.append(Spacer(1, 0.15 * inch))

        # Horizontal line
        hr_style = ParagraphStyle("HR", parent=styles["Normal"], fontSize=2, spaceAfter=6, alignment=1)
        elements.append(Paragraph("_" * 90, hr_style))

        # Invoice title
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=16,
            textColor=colors.black,
            spaceAfter=12,
            alignment=1,
        )
        elements.append(Paragraph("INVOICE", title_style))

        # Invoice details
        normal_style = styles["Normal"]
        elements.append(Paragraph(f"Invoice No: {invoice_data.get('invoice_no', 'N/A')}", normal_style))
        elements.append(Paragraph(f"Date: {invoice_data.get('invoice_date', 'N/A')}", normal_style))
        elements.append(Paragraph(f"Due Date: {invoice_data.get('due_date', 'N/A')}", normal_style))
        elements.append(Spacer(1, 0.2 * inch))

        # Member details
        elements.append(Paragraph(f"Plot Owner: {invoice_data.get('plot_owner_name', 'N/A')}", normal_style))
        elements.append(Paragraph(f"Plot No: {invoice_data.get('plot_no', 'N/A')}", normal_style))
        elements.append(Spacer(1, 0.2 * inch))

        # Duration
        bill_period = invoice_data.get('bill_period', 'N/A')
        from_date = invoice_data.get('from_date', '')
        to_date = invoice_data.get('to_date', '')
        num_months = invoice_data.get('number_of_months', '')
        duration_str = f"Duration: {bill_period} ({num_months} months)"
        if from_date and to_date:
            duration_str = f"Duration: {from_date} to {to_date} ({num_months} months)"
        elements.append(Paragraph(duration_str, normal_style))
        elements.append(Spacer(1, 0.1 * inch))

        # Thin separator
        sep_style = ParagraphStyle("Sep", parent=styles["Normal"], fontSize=1, spaceAfter=6, alignment=1)
        elements.append(Paragraph("_" * 90, sep_style))

        # Line items table
        data = [["Description", "Amount (₹)"]]
        line_items = invoice_data.get("line_items", {})
        total = 0
        for desc, amount in line_items.items():
            data.append([desc, f"{amount:,.2f}"])
            total += amount

        data.append(["TOTAL", f"{total:,.2f}"])

        table = Table(data, colWidths=[4.5 * inch, 1.5 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(table)
        elements.append(Spacer(1, 0.2 * inch))

        # Amount in words
        amount_words = invoice_data.get("amount_in_words", f"₹{total:,.2f}")
        elements.append(Paragraph(f"Amount: {amount_words}", normal_style))
        elements.append(Spacer(1, 0.15 * inch))

        # Payment summary
        outstanding = invoice_data.get("outstanding_balance", total)
        elements.append(Paragraph(f"Outstanding Balance: ₹ {outstanding:,.2f}", normal_style))

        # Payment History table
        payment_history = invoice_data.get("payment_history", [])
        if payment_history:
            elements.append(Spacer(1, 0.2 * inch))
            section_style = ParagraphStyle(
                "SectionTitle", parent=styles["Normal"], fontSize=10, leading=14,
                textColor=colors.black, spaceAfter=6, fontName="Helvetica-Bold",
            )
            elements.append(Paragraph("Payment History", section_style))
            ph_data = [["Date", "Particulars", "Amount (₹)"]]
            ph_total = 0
            for ph in payment_history:
                ph_data.append([
                    str(ph.get("date", "")),
                    str(ph.get("particulars", ""))[:30],
                    f"{ph.get('amount', 0):,.2f}",
                ])
                ph_total += ph.get("amount", 0)
            ph_data.append(["", "Total", f"{ph_total:,.2f}"])
            ph_table = Table(ph_data, colWidths=[1.2 * inch, 3.3 * inch, 1.5 * inch])
            ph_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(ph_table)

        # Previous Invoices table
        previous_invoices = invoice_data.get("previous_invoices", [])
        if previous_invoices:
            elements.append(Spacer(1, 0.2 * inch))
            section_style = ParagraphStyle(
                "SectionTitle", parent=styles["Normal"], fontSize=10, leading=14,
                textColor=colors.black, spaceAfter=6, fontName="Helvetica-Bold",
            )
            elements.append(Paragraph("Previous Invoices", section_style))
            inv_data = [["Date", "Invoice No", "Amount (₹)"]]
            inv_total = 0
            for inv in previous_invoices:
                inv_data.append([
                    str(inv.get("date", "")),
                    str(inv.get("description", ""))[:30],
                    f"{inv.get('amount', 0):,.2f}",
                ])
                inv_total += inv.get("amount", 0)
            inv_data.append(["", "Total Demanded", f"{inv_total:,.2f}"])
            inv_table = Table(inv_data, colWidths=[1.2 * inch, 3.3 * inch, 1.5 * inch])
            inv_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(inv_table)

        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("_" * 90, hr_style))
        elements.append(Spacer(1, 0.15 * inch))

        # Payment details footer
        footer_bold = ParagraphStyle(
            "FooterBold", parent=styles["Normal"], fontSize=10, leading=14,
            textColor=colors.black, spaceAfter=4,
        )
        footer_normal = ParagraphStyle(
            "FooterNormal", parent=styles["Normal"], fontSize=9, leading=13,
            textColor=colors.black, spaceAfter=2,
        )

        elements.append(Paragraph("<b>Payment Details:</b>", footer_bold))
        elements.append(Paragraph(
            "1. Cheque/DD: Drawn in favour of <b>\"Weekend Ville Maintenance Co Operative Society Ltd\"</b>. "
            "Write your Name, Building No, Flat No and Contact Number on the back of the cheque/DD.",
            footer_normal,
        ))
        elements.append(Paragraph(
            "2. NEFT/RTGS Transfer: You may transfer the money directly to the below mentioned account. "
            "Kindly mention your building no & flat no in the remarks column while doing transfer. "
            "Please send a copy of successful online payment details (screen shot) to the mentioned email-id. "
            "Mention your name, Building No, Flat No, Contact Number, Transaction ID and transaction date in email.",
            footer_normal,
        ))
        elements.append(Spacer(1, 0.15 * inch))

        # Bank account details as a table
        bank_data = [
            ["Beneficiary Name", "Weekend Ville Maintenance Co Operative Society Ltd"],
            ["Beneficiary Bank", "UNION BANK OF INDIA"],
            ["Branch Address", "MUTHA"],
            ["Account No", "474902010030343"],
            ["Account Type", "Savings Account"],
            ["IFSC Code", "UBIN0547492"],
            ["MICR", "411026116"],
            ["Email ID", "weekendville.jatede@gmail.com"],
        ]
        bank_table = Table(bank_data, colWidths=[2 * inch, 4 * inch])
        bank_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(bank_table)

        elements.append(Spacer(1, 0.2 * inch))

        # Rider / notes
        rider_style = ParagraphStyle(
            "Rider", parent=styles["Normal"], fontSize=8.5, leading=12,
            textColor=colors.black, spaceAfter=3,
        )
        rider_bold = ParagraphStyle(
            "RiderBold", parent=rider_style, fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("<b>Please note:</b>", rider_bold))
        elements.append(Paragraph(
            "1. Taxes if applicable will be charged retrospectively. Cheque bouncing charges as applicable. "
            "Interest (as applicable) will be charged if payment is made after due date invoice date.",
            rider_style,
        ))
        elements.append(Paragraph(
            "2. In case payment for previous quarter has been made and it is not reflecting in your bill, "
            "kindly provide with your previous payment details to society office.",
            rider_style,
        ))

        # Build PDF
        doc.build(elements)
        return True

    except Exception as e:
        print(f"Error creating invoice PDF: {e}")
        return False


def create_simple_receipt_pdf(pdf_path: Path, receipt_data: Dict[str, Any]) -> bool:
    """
    Create a simple receipt PDF from receipt data
    """
    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # Society header (same as invoice)
        header_bold = ParagraphStyle(
            "HeaderBold",
            parent=styles["Normal"],
            fontSize=14,
            leading=18,
            textColor=colors.black,
            alignment=1,
            spaceAfter=4,
        )
        header_normal = ParagraphStyle(
            "HeaderNormal",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.black,
            alignment=1,
            spaceAfter=2,
        )
        elements.append(Paragraph("Weekend Ville Maintenance Co-Op. Society Ltd 24-25", header_bold))
        elements.append(Paragraph("Sr. No. 241/274/287/288/289, Mauje Jatede", header_normal))
        elements.append(Paragraph("Tal.- Mulshi, Dist.-Pune", header_normal))
        elements.append(Paragraph("Society Reg No : PNA/MSI/GNL/(O)/4350/FY 2021-2022 DATE : 24/08/2021", header_normal))
        elements.append(Spacer(1, 0.15 * inch))

        # Horizontal line
        hr_style = ParagraphStyle("HR", parent=styles["Normal"], fontSize=2, spaceAfter=6, alignment=1)
        elements.append(Paragraph("_" * 90, hr_style))

        # Title
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=16,
            textColor=colors.black,
            spaceAfter=12,
            alignment=1,
        )
        elements.append(Paragraph("RECEIPT", title_style))

        normal_style = styles["Normal"]

        # Receipt details
        elements.append(Paragraph(f"Receipt No: {receipt_data.get('receipt_id', 'N/A')}", normal_style))
        elements.append(Paragraph(f"Date: {receipt_data.get('date', 'N/A')}", normal_style))
        elements.append(Spacer(1, 0.3 * inch))

        # Member details
        elements.append(Paragraph(f"Member: {receipt_data.get('member_name', 'N/A')}", normal_style))
        elements.append(Paragraph(f"Plot No: {receipt_data.get('plot_no', 'N/A')}", normal_style))
        elements.append(Spacer(1, 0.3 * inch))

        # Payment details
        amount = receipt_data.get("amount", 0)
        elements.append(Paragraph(f"Amount Received: ₹ {amount:,.2f}", normal_style))
        elements.append(Paragraph(f"Transaction ID: {receipt_data.get('transaction_id', 'N/A')}", normal_style))
        txn_type = receipt_data.get("transaction_type", "")
        if txn_type:
            elements.append(Paragraph(f"Transaction Type: {txn_type}", normal_style))
        payment_details = receipt_data.get("payment_details", "")
        if payment_details:
            elements.append(Paragraph(f"Payment Details: {payment_details}", normal_style))
        elements.append(Spacer(1, 0.3 * inch))

        # Outstanding balance
        outstanding = receipt_data.get("outstanding_balance", 0)
        elements.append(Paragraph(f"Outstanding Balance: ₹ {outstanding:,.2f}", normal_style))

        elements.append(Spacer(1, 0.5 * inch))

        # Footer note
        note_style = ParagraphStyle(
            "Note",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.gray,
            alignment=1,
            spaceBefore=12,
        )
        elements.append(Paragraph(
            "Please note: This is auto generated by system and subject to "
            "actual realization of payment in the account.",
            note_style,
        ))

        # Build PDF
        doc.build(elements)
        return True

    except Exception as e:
        print(f"Error creating receipt PDF: {e}")
        return False
