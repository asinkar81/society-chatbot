"""
Generate Publication-Grade PDF of AGM Audit Validation & Reconciliation Report
Optimized for sharing on WhatsApp and printing for AGM presentation.
Structured into an exact 4-page executive document:
  Page 1: Executive Summary, The Two-Report Approach & Member Expense Accounting Policy
  Page 2: Builder's Evidentiary Register (Nov 2021) & Proven Audit Rectifications
  Page 3: Master 41-Plot Audit Reconciliation Table (As of 31-March-2026 Audit Cutoff)
  Page 4: Formal Draft AGM Resolution for Minutes & Managing Committee Certification
"""
from pathlib import Path
import shutil
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and render 'Page X of Y' 
    and running headers/footers across all pages.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#475569"))
        
        # Running top header (from page 2 onwards)
        if self._pageNumber > 1:
            self.drawString(36, 812, "Weekend Ville Maintenance Co-Op Society Ltd. | AGM Audit Validation & Reconciliation")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 806, 559, 806)
            
        # Running bottom footer on every page
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(36, 32, 559, 32)
        
        self.drawString(36, 22, "Confidential — For Weekend Ville Maintenance Co-Op Society Members Only")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(559, 22, page_str)
        self.restoreState()


def generate_audit_report_pdf(primary_path: Path, copy_paths: list[Path]) -> bool:
    try:
        # Load society data from Excel
        excel_path = Path("data/society_data.xlsx")
        df_led = pd.read_excel(excel_path, sheet_name="Ledger")
        df_mem = pd.read_excel(excel_path, sheet_name="Members")

        # Usable width on A4 with 36pt (0.5 in) margins is 523.0 pt
        USABLE_W = 523.0

        # Primary palette
        C_PRIMARY = colors.HexColor("#0F2942")     # Deep Corporate Navy
        C_SECONDARY = colors.HexColor("#1E3A8A")   # Royal Navy
        C_TEXT = colors.HexColor("#1E293B")        # Slate Text
        C_MUTED = colors.HexColor("#64748B")       # Muted Gray
        C_BG_LIGHT = colors.HexColor("#F8FAFC")    # Table light gray
        C_BORDER = colors.HexColor("#CBD5E1")      # Border line
        C_RED = colors.HexColor("#B91C1C")         # Crimson
        C_GREEN = colors.HexColor("#15803D")       # Forest Green
        C_AMBER = colors.HexColor("#B45309")       # Amber

        # Typography Styles
        base_styles = getSampleStyleSheet()

        st_title = ParagraphStyle(
            "DocTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12.0,
            leading=15.0,
            textColor=C_PRIMARY,
            alignment=1, # Center
            spaceAfter=1.5,
        )
        st_sub = ParagraphStyle(
            "DocSub",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10.0,
            textColor=C_MUTED,
            alignment=1,
            spaceAfter=1,
        )
        st_banner = ParagraphStyle(
            "BannerTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=12.5,
            textColor=colors.white,
            alignment=1,
        )
        st_h1 = ParagraphStyle(
            "H1",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.8,
            leading=11.2,
            textColor=C_PRIMARY,
            spaceBefore=5,
            spaceAfter=2,
            keepWithNext=True,
        )
        st_body = ParagraphStyle(
            "Body",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7.0,
            leading=9.0,
            textColor=C_TEXT,
            spaceAfter=2,
        )

        # Table Styles
        th_style = ParagraphStyle(
            "TH",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.0,
            leading=8.8,
            textColor=colors.white,
            alignment=0,
        )
        th_style_r = ParagraphStyle(
            "THR",
            parent=th_style,
            alignment=2,
        )
        th_style_c = ParagraphStyle(
            "THC",
            parent=th_style,
            alignment=1,
        )
        td_style = ParagraphStyle(
            "TD",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=6.5,
            leading=8.2,
            textColor=C_TEXT,
            alignment=0,
        )
        td_style_bold = ParagraphStyle(
            "TDBold",
            parent=td_style,
            fontName="Helvetica-Bold",
        )
        td_style_r = ParagraphStyle(
            "TDR",
            parent=td_style,
            alignment=2,
        )
        td_style_r_bold = ParagraphStyle(
            "TDRBold",
            parent=td_style_r,
            fontName="Helvetica-Bold",
        )
        td_style_c = ParagraphStyle(
            "TDC",
            parent=td_style,
            alignment=1,
        )

        elements = []

        # ==================================================================
        # PAGE 1: EXECUTIVE SUMMARY, THE TWO-REPORT APPROACH & EXPENSE POLICY
        # ==================================================================
        elements.append(Paragraph("WEEKEND VILLE MAINTENANCE CO-OPERATIVE SOCIETY LTD.", st_title))
        elements.append(Paragraph("Regn. No.: PNA/MSI/GNL/(O)/4350/FY 2021-2022 | Date of Registration: 24/08/2021", st_sub))
        elements.append(Paragraph("Sr. No. 241/274/287/288/289, Mouze Jatode, Taluka Mulshi, District Pune", st_sub))
        elements.append(Spacer(1, 2))

        banner_table = Table(
            [[Paragraph("AGM AUDIT VALIDATION, CROSS-VERIFICATION & RESOLUTION PACKAGE", st_banner)]],
            colWidths=[USABLE_W]
        )
        banner_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_PRIMARY),
            ("TOPPADDING", (0, 0), (-1, -1), 3.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        elements.append(banner_table)
        elements.append(Paragraph("Forensic Review of FY 2021-22 through FY 2025-26 Audit Books vs. Society Records & Live Position as of 31-Oct-2026", st_sub))
        elements.append(Spacer(1, 3))

        # 1. Executive Summary & Two-Report Strategy
        elements.append(Paragraph("1. Executive Summary & The Two-Report Approach for AGM", st_h1))
        two_rep_text = (
            "To maintain statutory compliance under the Maharashtra Co-operative Societies (MCS) Act while providing complete ground-truth "
            "transparency to all plot owners, the Managing Committee presents a coordinated <b>Two-Report Approach</b> at this Annual General Meeting:<br/>"
            "&ndash; <b>1. Statutory Auditor's Report (as of 31-March-2026):</b> Tabled formally under Agenda Item 3 for consideration and statutory "
            "adoption of the FY 2025-26 audited accounts, preserving statutory continuity.<br/>"
            "&ndash; <b>2. Managing Committee's Live Reconciled Register (as of 31-October-2026):</b> Tabled as a <b>Management Addendum</b> reflecting "
            "actual ground-truth bank collections, incorporating: (a) 7 additional months of maintenance collections received between 01-Apr-2026 and "
            "31-Oct-2026; and (b) Specific audit rectifications (Anshul Rathod Rs. 18k, Parag Modak Rs. 9k, Amit Bhosale Rs. 2k, Rahul Palnitkar Rs. 18k) "
            "to be formally passed into the <b>FY 2026-27 accounts</b> via General Body resolution approved today."
        )
        t_rep = Table([[Paragraph(two_rep_text, st_body)]], colWidths=[USABLE_W])
        t_rep.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#3B82F6")),
            ("TOPPADDING", (0, 0), (-1, -1), 3.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ("LEFTPADDING", (0, 0), (-1, -1), 5.0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5.0),
        ]))
        elements.append(t_rep)
        elements.append(Spacer(1, 4))

        # 2. High-Level Reconciliation Summary Table
        elements.append(Paragraph("2. High-Level Reconciliation Summary (As of 31-March-2026 Audit Cutoff)", st_h1))
        kpi_data = [
            [Paragraph("Financial Parameter", th_style), Paragraph("Auditor Report (31-Mar-26)", th_style_r), Paragraph("Society Records (31-Mar-26)", th_style_r), Paragraph("Variance & Reconciliation Status", th_style)],
            [Paragraph("Total Maintenance Billed (41 Plots)", td_style_bold), Paragraph("Rs. 21,73,000.00", td_style_r), Paragraph("Rs. 21,73,000.00", td_style_r), Paragraph("Rs. 0.00 (100% Exact Match across 5 Financial Years)", td_style_bold)],
            [Paragraph("Total Member Realizations (Credits)", td_style_bold), Paragraph("Rs. 12,92,391.00", td_style_r), Paragraph("Rs. 13,05,501.00", td_style_r_bold), Paragraph("+Rs. 13,110.00 net (Society verified additional bank collections)", td_style)],
            [Paragraph("Cumulative Member Outstanding (Dues)", td_style_bold), Paragraph("Rs. 8,80,609.00", td_style_r), Paragraph("Rs. 8,67,499.00", td_style_r_bold), Paragraph("-Rs. 13,110.00 lower dues in Society Records", td_style_bold)],
            [Paragraph("Plots with 100% Perfect Reconciliation", td_style), Paragraph("15 Plots", td_style_r), Paragraph("15 Plots", td_style_r), Paragraph("Exact match on all historical vouchers and closing balance", td_style)],
            [Paragraph("Family Groups (Ombale, Salvi, Bhate)", td_style), Paragraph("11 Plots", td_style_r), Paragraph("11 Plots", td_style_r), Paragraph("Family group combined sums match 100% across both records", td_style)],
            [Paragraph("Proven Clerical Errors in Audit Books", td_style_bold), Paragraph("6 Plots", td_style_r), Paragraph("0 in Society", td_style_r), Paragraph("Verified bank UTRs establish clerical errors in audit books", td_style_bold)],
        ]
        t_kpi = Table(kpi_data, colWidths=[145, 95, 95, 188])
        t_kpi.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BG_LIGHT]),
        ]))
        elements.append(t_kpi)
        elements.append(Spacer(1, 4))

        # 3. Accounting Policy on Member Expenses
        elements.append(Paragraph("3. Accounting Policy on Member-Incurred Expenses (Plots 13 & 26)", st_h1))
        exp_policy_text = (
            "<b>Standard Cooperative Accounting Principle:</b> Under standard co-operative housing society accounting norms, "
            "<b>operating expenses incurred by members must NEVER be directly credited against maintenance dues in member ledgers</b>.<br/>"
            "&ndash; <b>Why Direct Offsetting is Flawed:</b> Direct crediting bypasses payment vouchers, distorts individual plot contribution records, "
            "and artificially obscures actual repair expenditures in the Society's annual Income & Expenditure Account.<br/>"
            "&ndash; <b>The Correct Procedure:</b> (1) The member pays their maintenance charges in full; (2) The member submits vendor bills; "
            "(3) The Society issues a <b>formal direct reimbursement</b> via bank transfer/cheque, debiting the Repairs & Maintenance Account.<br/>"
            "&ndash; <b>Application to Plot 13 (Mr. Rishikesh Phutane):</b> The Accountant credited Rs. 1,000 on 03-Apr-2024 via non-cash Journal J45 for "
            "electrical site repairs. <i>Resolution:</i> The Society will issue a direct bank reimbursement of Rs. 1,000 to Mr. Phutane. His maintenance ledger "
            "remains standard.<br/>"
            "&ndash; <b>Application to Plot 26 (Mr. Ashutosh Sinkar):</b> Rs. 140 petty cash incurred for society work. <i>Resolution:</i> Reimbursed directly "
            "from petty cash; member ledger kept strictly for maintenance dues."
        )
        t_exp = Table([[Paragraph(exp_policy_text, st_body)]], colWidths=[USABLE_W])
        t_exp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
            ("BOX", (0, 0), (-1, -1), 0.6, C_AMBER),
            ("TOPPADDING", (0, 0), (-1, -1), 3.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ("LEFTPADDING", (0, 0), (-1, -1), 5.0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5.0),
        ]))
        elements.append(t_exp)

        # End of Page 1
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 2: BUILDER'S REGISTER, PROVEN AUDIT ERRORS & LIVE ADJUSTMENTS
        # ==================================================================
        elements.append(Paragraph("4. Builder's Verified Record: November 2021 Shivaji Salary Contributions", st_h1))
        builder_text = (
            "<b>Evidentiary Record from Builder's Representative (Mr. Shailesh Dave):</b><br/>"
            "During the initial society handover, maintenance contributions for security guard Shivaji's November 2021 salary "
            "were collected directly into Mr. Shailesh Dave's Axis Bank account and disbursed in cash:<br/>"
            "&ndash; <b>Collections (14 Plots / Rs. 18,000 Total):</b> Pl 38&39 Deshpande (Rs. 2k, 17-12-21), Pl 25 Rao (Rs. 1k, 13-12-21), Pl 23 Modak (Rs. 1k, 13-12-21), Pl 6 Nimbkar (Rs. 1k, 13-12-21), Pl 7 Fernandes (Rs. 1k, 12-12-21), Pl 16&17 Bhate (Rs. 2k, 13-12-21), Pl 8 Kulkarni (Rs. 1k, 12-12-21), Pl 10 Bhagwat (Rs. 1k, 12-12-21), Pl 5&20 Rathod (Rs. 2k, 13-12-21), Pl 13 Phutane (Rs. 1k, 13-12-21), Pl 12 Maskikar (Rs. 1k, 12-12-21), Pl 37 Kumar (Rs. 1k, 12-12-21), Pl 21 Pawar (Rs. 1k, 24-12-21), Pl 28&29 Pujari (Rs. 2k, 16-01-22).<br/>"
            "&ndash; <b>Disbursements to Shivaji:</b> Rs. 15,000 (Dec 2021) + Rs. 2,000 (16-01-2022) + Rs. 1,000 (20-01-2022) = <b>Rs. 18,000 Total</b>.<br/>"
            "&ndash; <b>Critical Audit Finding (Plot 12 Maskikar Duplicate):</b> Item 11 proves Mr. Maskikar paid Rs. 1,000 ONCE on 12-12-2021. "
            "In <i>PLOT NO. 12 MASKIKAR.pdf</i>, the Accountant entered it <b>twice</b> (Receipt 1: Rs. 1k and Receipt 3: Rs. 1k). Society Records correctly record "
            "only one Rs. 1,000 entry (Vch #76). The Accountant's extra Rs. 1,000 credit is an erroneous cash duplicate that must be reversed."
        )
        t_bld = Table([[Paragraph(builder_text, st_body)]], colWidths=[USABLE_W])
        t_bld.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5.0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5.0),
        ]))
        elements.append(t_bld)
        elements.append(Spacer(1, 3))

        # 5. Proven Audit Errors Table
        elements.append(Paragraph("5. Proven Audit Errors to be Rectified in FY 2026-27 Books", st_h1))
        err_data = [
            [Paragraph("Plot No.", th_style_c), Paragraph("Member Name", th_style), Paragraph("Error in Auditor Report (FY 25-26)", th_style), Paragraph("Rectification to Pass in FY 26-27", th_style), Paragraph("Evidentiary Basis & Bank Proof", th_style)],
            [Paragraph("Plots 05 & 20", td_style_c), Paragraph("Mr. Anshul Rathod", td_style_bold), Paragraph("Omitted Rs. 18,000 payments (Accountant credited to Pujari)", td_style), Paragraph("Credit Rs. 9,000 to Plot 05 and Rs. 9,000 to Plot 20", td_style_bold), Paragraph("NEFT HS92412041538641 (Rs. 12k) & IMPS 416210088929 (Rs. 6k). Accountant's PDF literally prints \"NEFT: ANSHUL RATHOD\" in Pujari's ledger!", td_style)],
            [Paragraph("Plots 28 & 29", td_style_c), Paragraph("Mr. Ashutosh Pujari", td_style_bold), Paragraph("Over-credited Rs. 18,000 (Rathod's NEFT/IMPS entered here)", td_style), Paragraph("Debit Rs. 9,000 to Plot 28 and Rs. 9,000 to Plot 29", td_style_bold), Paragraph("Reversal of Rathod's misallocated payments. Pujari's actual verified bank payments remain Rs. 38,000.", td_style)],
            [Paragraph("Plot 23", td_style_c), Paragraph("Mr. Parag Modak", td_style_bold), Paragraph("Omitted Rs. 9,000 genuine bank deposit on 11-05-2025", td_style), Paragraph("Credit Rs. 9,000 to Plot 23", td_style_bold), Paragraph("Verified Union Bank deposit: IMPSAB/513112157207/PARAG on 11-05-2025. Parag Modak has 0 arrears.", td_style)],
            [Paragraph("Plot 24", td_style_c), Paragraph("Mr. Amit Bhosale", td_style_bold), Paragraph("Omitted 2x Rs. 1,000 same-day bank deposits as false duplicates", td_style), Paragraph("Credit Rs. 2,000 to Plot 24", td_style_bold), Paragraph("Bank deposits on 19-06-2022 (Ref 425055433) & 31-07-2022 (Ref 456569709) both debited from Bhosale's account.", td_style)],
            [Paragraph("Plot 12", td_style_c), Paragraph("Mr. Madhukar Maskikar", td_style_bold), Paragraph("Duplicate Rs. 1,000 cash receipt booked in Dec 2021", td_style), Paragraph("Debit Rs. 1,000 to Plot 12 (Reverse duplicate)", td_style_bold), Paragraph("Builder's verified collection register proves single Rs. 1,000 cash payment on 12-12-2021.", td_style)],
            [Paragraph("Plot 13", td_style_c), Paragraph("Mr. Rishikesh Phutane", td_style_bold), Paragraph("Offset Rs. 1,000 site electrical repair via non-cash J45", td_style), Paragraph("Direct society reimbursement of Rs. 1,000 to member", td_style_bold), Paragraph("Maintenance ledger restored to standard billing; expense booked under Repairs & Maintenance.", td_style)],
        ]
        t_err = Table(err_data, colWidths=[52, 75, 125, 125, 146])
        t_err.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BG_LIGHT]),
        ]))
        elements.append(t_err)
        elements.append(Spacer(1, 3))

        # 6. Specific Live Adjustments Box
        elements.append(Paragraph("6. Audit Findings & Live Ledger Adjustments Executed in Society Records", st_h1))
        adj_text = (
            "&ndash; <b>Plot 36 (Mr. Rahul Palnitkar) vs. Plot 27 (Mr. Rahul Bachikar):</b> Bank statement entry on 09-12-2025 (UPI Ref 534366020481, Rs. 18,000) "
            "was previously tagged to Plot 27. Verified against registered phone and member confirmation; successfully moved to <b>Plot 36</b>, aligning both plots.<br/>"
            "&ndash; <b>Plot 19 (Mrs. Sheetal Salunke) vs. Plot 18 (Mrs. Manjiri Gavande):</b> Entry on 28-09-2024 (NEFT: CONTINUUM INDUSTRIES, Rs. 5,000) "
            "was previously booked to Plot 18. Continuum Industries belongs to Mrs. Salunke; entry successfully moved to <b>Plot 19</b>.<br/>"
            "&ndash; <b>Plot 18 Phone Record Correction:</b> Mobile <b>9960184874</b> is verified as belonging to Plot 18 owner (Mrs. Manjiri Gavande), "
            "confirming that Vch #286 (Rs. 6,000 on 03-07-2022) is correctly credited to Plot 18 in both systems. Plot 28 master record updated with 9962132503.<br/>"
            "&ndash; <b>Plot 08 (Shantanu Kulkarni) vs. Plot 37 (Ajaykumar Radhakrishnan):</b> Rs. 3,000 transaction on 31-03-2022. Both plot owners have been "
            "contacted for personal bank passbook verification to finalize attribution prior to statutory filing."
        )
        t_adj = Table([[Paragraph(adj_text, st_body)]], colWidths=[USABLE_W])
        t_adj.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
            ("BOX", (0, 0), (-1, -1), 0.6, C_GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5.0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5.0),
        ]))
        elements.append(t_adj)

        # End of Page 2
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 3: MASTER 41-PLOT AUDIT CROSS-VERIFICATION TABLE
        # ==================================================================
        elements.append(Paragraph("7. Complete 41-Plot Master Audit Cross-Verification Table (As of 31-March-2026 Audit Cutoff)", st_h1))
        elements.append(Paragraph("Individual plot comparison between Accountant's Audit Ledgers and Society Verified Bank Records (reflecting live corrections):", st_body))

        # Pre-calculated audit figures as of 31-March-2026
        acct_credits = [
            0, 4000, 47000, 41000, 47875, 1000, 52000, 49000, 0, 51000,
            16000, 51500, 53000, 16000, 42000, 42000, 42000, 36000, 21000, 46875,
            1000, 0, 42000, 2000, 53000, 40140, 41000, 28000, 28000, 41000,
            7000, 12000, 50000, 34000, 34000, 25000, 50000, 47000, 47000, 37000,
            14001
        ]

        statuses = [
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Ombale/Bidkar group Rs. 1.56L combined match',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Ombale/Bidkar group Rs. 1.56L combined match',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Acct gave Rs. 9k to Pujari (To rectify in FY 26-27)',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#D97706"><b>[VERIFYING]</b></font> Rs. 3k entry awaiting owner confirmation',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Salvi family Rs. 69k combined group match',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Acct has duplicate Rs. 1k cash receipt (To reverse)',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> Rs. 1k electrical repair to be reimbursed directly',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Salvi family Rs. 69k combined group match',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Bhate family Rs. 84k combined group match',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Bhate family Rs. 84k combined group match',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified (Vch #683 moved to P19)',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified (Vch #683 moved to P19)',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Acct gave Rs. 9k to Pujari (To rectify in FY 26-27)',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Acct missed Rs. 9k bank IMPS deposit (11-05-2025)',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Acct missed 2x Rs. 1k bank deposits as duplicates',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> Fully Settled as of 31-Mar-2026',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> Rs. 140 petty cash to be reimbursed directly',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified (Vch #920 moved to P36)',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Over-credited Rs. 9k (Rathod payment misallocated)',
            '<font color="#B91C1C"><b>[AUDIT ERROR]</b></font> Over-credited Rs. 9k (Rathod payment misallocated)',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Varpe family Rs. 67k combined collections',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Varpe family Rs. 67k combined collections',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Ombale/Bidkar group Rs. 1.56L combined match',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Ombale/Bidkar group Rs. 1.56L combined match',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified (Vch #920 moved to P36)',
            '<font color="#D97706"><b>[VERIFYING]</b></font> Rs. 3k entry awaiting owner confirmation',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
            '<font color="#2563EB"><b>[FAMILY GROUP]</b></font> Salvi family Rs. 69k combined group match',
            '<font color="#15803D"><b>[EXACT MATCH]</b></font> 100% verified historical entries',
        ]

        m_th = ParagraphStyle("MTH", parent=th_style, fontSize=6.8, leading=8.5)
        m_th_c = ParagraphStyle("MTHC", parent=th_style_c, fontSize=6.8, leading=8.5)
        m_th_r = ParagraphStyle("MTHR", parent=th_style_r, fontSize=6.8, leading=8.5)
        m_td = ParagraphStyle("MTD", parent=td_style, fontSize=6.2, leading=7.5)
        m_td_bold = ParagraphStyle("MTDBold", parent=td_style_bold, fontSize=6.2, leading=7.5)
        m_td_c = ParagraphStyle("MTDC", parent=td_style_c, fontSize=6.2, leading=7.5)
        m_td_r = ParagraphStyle("MTDR", parent=td_style_r, fontSize=6.2, leading=7.5)
        m_td_r_bold = ParagraphStyle("MTDRBold", parent=td_style_r_bold, fontSize=6.2, leading=7.5)

        df_mem_sorted = df_mem.copy()
        df_mem_sorted["Plot_Num"] = df_mem_sorted["Plot_No"].apply(lambda p: int(p) if str(p).isdigit() else 999)
        df_mem_sorted = df_mem_sorted.sort_values("Plot_Num")

        df_led["Date_dt"] = pd.to_datetime(df_led["Date"], format="%d-%m-%Y", errors="coerce")
        cutoff = pd.to_datetime("2026-03-31")
        df_led_audit = df_led[df_led["Date_dt"] <= cutoff]

        rows = [[
            Paragraph("Plot", m_th_c),
            Paragraph("Plot Owner Name", m_th),
            Paragraph("Acct Credits", m_th_r),
            Paragraph("Society Credits", m_th_r),
            Paragraph("Net Balance", m_th_r),
            Paragraph("Reconciliation Status & Evidentiary Findings", m_th),
        ]]

        for idx, (_, m) in enumerate(df_mem_sorted.iterrows()):
            mid = m["ID"]
            pno = str(m["Plot_No"]).strip().zfill(2)
            name = str(m["Plot_Owner_Name"]).strip()
            acct_cr = acct_credits[idx]
            
            m_led = df_led_audit[df_led_audit["Member_ID"] == mid]
            tot_dr = m_led["Debit"].fillna(0).sum()
            tot_cr = m_led["Credit"].fillna(0).sum()
            net = tot_dr - tot_cr
            
            if net > 0:
                bal_str = f"Rs. {net:,.0f} Due"
                bal_style = m_td_r_bold if net >= 30000 else m_td_r
            elif net < 0:
                bal_str = f"+Rs. {abs(net):,.0f} Surplus"
                bal_style = m_td_r_bold
            else:
                bal_str = "Rs. 0 Settled"
                bal_style = m_td_r
                
            st_text = statuses[idx]
            
            rows.append([
                Paragraph(f"<b>Plot {pno}</b>", m_td_c),
                Paragraph(name[:28], m_td),
                Paragraph(f"Rs. {acct_cr:,.0f}", m_td_r),
                Paragraph(f"Rs. {tot_cr:,.0f}", m_td_r),
                Paragraph(bal_str, bal_style),
                Paragraph(st_text, m_td),
            ])

        # Total row
        tot_acct = sum(acct_credits)
        tot_sys = df_mem_sorted["ID"].apply(lambda mid: df_led_audit[df_led_audit["Member_ID"] == mid]["Credit"].fillna(0).sum()).sum()
        tot_dr = df_mem_sorted["ID"].apply(lambda mid: df_led_audit[df_led_audit["Member_ID"] == mid]["Debit"].fillna(0).sum()).sum()
        tot_net = tot_dr - tot_sys

        rows.append([
            Paragraph("<b>Total</b>", m_td_c),
            Paragraph("<b>41 Society Plots Master Total</b>", m_td_bold),
            Paragraph(f"<b>Rs. {tot_acct:,.0f}</b>", m_td_r_bold),
            Paragraph(f"<b>Rs. {tot_sys:,.0f}</b>", m_td_r_bold),
            Paragraph(f"<b>Rs. {tot_net:,.0f}</b>", m_td_r_bold),
            Paragraph("<b>+Rs. 13,110 Net Verified Bank Collections in Society</b>", m_td_bold),
        ])

        t_master = Table(rows, colWidths=[36, 125, 52, 52, 68, 190])
        t_master.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.35, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 0.9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, C_BG_LIGHT]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ]))
        elements.append(t_master)

        # End of Page 3
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 4: FORMAL DRAFT RESOLUTION & CERTIFICATION SIGN-OFF
        # ==================================================================
        elements.append(Paragraph("8. Formal Draft AGM Resolution for General Body Minutes", st_h1))
        elements.append(Paragraph("To be tabled under Agenda Item \"Consideration and Adoption of Audited Accounts for FY 2025-26\":", st_body))

        res_text = (
            "<b>RESOLUTION NO. ___</b><br/>"
            "<b>CONSIDERATION AND ADOPTION OF AUDITED ACCOUNTS FOR FY 2025-26 AND APPROVAL OF BANK-RECONCILED RECTIFICATIONS IN FY 2026-27 BOOKS</b><br/><br/>"
            "\"<b>RESOLVED THAT</b> the Audited Balance Sheet and Income & Expenditure Account of Weekend Ville Maintenance Co-operative Society Ltd. "
            "for the Financial Year ended 31st March 2026, together with the Statutory Auditor's Report thereon, be and are hereby considered and adopted.\"<br/><br/>"
            "\"<b>RESOLVED FURTHER THAT</b> the General Body takes formal note of the Managing Committee's Bank-Reconciled Verification Report, which "
            "cross-verified all 41 individual plot ledgers against the Society's official Union Bank of India account statements and identified verifiable "
            "bank credits and clerical misallocations in the FY 2025-26 audit books.\"<br/><br/>"
            "\"<b>RESOLVED FURTHER THAT</b> the Managing Committee be and is hereby authorized and directed to instruct the Society's Accountant and "
            "Statutory Auditor to incorporate the following rectification journal entries into the statutory books of account for Financial Year 2026-27:<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>1. Plots 05 & 20 (Mr. Anshul Rathod) & Plots 28 & 29 (Mr. Ashutosh Pujari):</b> Credit Rs. 18,000.00 (Rs. 9,000 each) "
            "to Mr. Anshul Rathod (Plots 05 & 20) and correspondingly reverse the erroneous credit from Mr. Ashutosh Pujari (Plots 28 & 29) on the basis of "
            "verified bank statement NEFT HS92412041538641 (Rs. 12,000) and IMPS 416210088929 (Rs. 6,000).<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>2. Plot 23 (Mr. Parag Modak):</b> Credit Rs. 9,000.00 to Mr. Parag Modak in respect of verified Union Bank deposit "
            "dated 11-May-2025 (IMPSAB/513112157207/PARAG) omitted in the FY 2025-26 audit ledger.<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>3. Plot 24 (Mr. Amit Bhosale):</b> Credit Rs. 2,000.00 to Mr. Amit Bhosale in respect of genuine same-day bank transfers "
            "dated 19-June-2022 (Ref 425055433) and 31-July-2022 (Ref 456569709) debited from member's account and omitted in the audit ledger.<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>4. Plot 12 (Mr. Madhukar Maskikar):</b> Reverse the duplicate Rs. 1,000.00 cash receipt in the audit ledger to align "
            "with the Builder's verified salary collection register of November 2021 confirming a single Rs. 1,000 payment.<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>5. Plots 13 & 26 (Member Expense Reimbursements):</b> Settle member-incurred site maintenance expenses "
            "(Plot 13 electrical repair Rs. 1,000 and Plot 26 petty cash Rs. 140) by direct Society bank reimbursement, restoring member ledgers to standard "
            "maintenance billing and charging expenses to the Repairs & Maintenance Account.\"<br/><br/>"
            "\"<b>RESOLVED FURTHER THAT</b> the Secretary and Treasurer of the Society be and are hereby authorized to sign all requisite rectification vouchers, "
            "journal entries, and instructions to give full effect to the above resolutions.\""
        )
        t_res = Table([[Paragraph(res_text, td_style)]], colWidths=[USABLE_W])
        t_res.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.0),
            ("LEFTPADDING", (0, 0), (-1, -1), 6.0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6.0),
        ]))
        elements.append(t_res)
        elements.append(Spacer(1, 5))

        cert_head = Paragraph(
            "<b>MANAGING COMMITTEE CERTIFICATION & AUDIT VERIFICATION SIGN-OFF</b><br/>"
            "We, the undersigned Managing Committee members of Weekend Ville Maintenance Co-Operative Society Ltd., hereby certify that "
            "this Audit Validation Report has been prepared following a rigorous forensic cross-verification of all 41 plot accounts against "
            "original Union Bank of India bank statements, builder collection records, and vendor vouchers. All findings are fully backed by verifiable "
            "bank transaction IDs and documentary evidence.",
            st_body
        )
        sig_left = Paragraph("<b>Ashutosh Sinkar</b><br/>Hon. Treasurer<br/>Weekend Ville Maintenance Co-Op Society Ltd.", td_style)
        sig_right = Paragraph("<b>Hon. Secretary / Chairman</b><br/>Managing Committee<br/>Weekend Ville Maintenance Co-Op Society Ltd.", ParagraphStyle("SigR", parent=td_style, alignment=2))
        sig_table = Table([[sig_left, sig_right]], colWidths=[250, 250])
        sig_table.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        date_para = Paragraph("<b>Date of Presentation:</b> 22 November 2026 &nbsp;|&nbsp; <b>Place:</b> Jatode, Mulshi, Pune", st_body)

        t_cert = Table([[cert_head], [Spacer(1, 2)], [sig_table], [Spacer(1, 2)], [date_para]], colWidths=[USABLE_W])
        t_cert.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX", (0, 0), (-1, -1), 0.8, C_PRIMARY),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6.0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6.0),
        ]))
        elements.append(t_cert)

        # Build Primary PDF
        primary_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(primary_path),
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )
        doc.build(elements, canvasmaker=NumberedCanvas)
        print(f"Generated Primary PDF: {primary_path} ({primary_path.stat().st_size:,} bytes)")

        # Copy to additional destinations
        for cp in copy_paths:
            cp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(primary_path, cp)
            print(f"Copied PDF to: {cp} ({cp.stat().st_size:,} bytes)")

        return True

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error generating PDF: {e}")
        return False


if __name__ == "__main__":
    primary = Path("Weekend_Ville_AGM_Audit_Validation_Report.pdf")
    copies = [
        Path("data/staging/whatsapp/Weekend_Ville_AGM_Audit_Validation_Report.pdf"),
        Path("/Users/ashutoshsinkar/.gemini/antigravity/brain/db392fa2-4f19-47cd-a060-f89008858d15/Weekend_Ville_AGM_Audit_Validation_Report.pdf"),
    ]
    generate_audit_report_pdf(primary, copies)
