"""
Generate Professional PDF of Treasurer's Financial Report, Expense Analysis & Budget
Optimized for sharing on WhatsApp and printing for AGM presentation.
Structured into an exact 5-page executive presentation:
  Page 1: Liquid Financial Position & Five-Year Audited Spend Analysis
  Page 2: Defaulter Severity Analysis & Section 154B-29 Legal Recovery Framework
  Page 3: Master 41-Plot Ledger Audit & Reconciliation Sheet (Plots 1-41 + Total)
  Page 4: Proposed OPEX Routine Budget & Prioritized 3-Tier CAPEX Plan
  Page 5: Funding Recommendations, Defaulter Offset Strategy & Formal AGM Resolutions
"""
from pathlib import Path
import shutil
import pandas as pd
from datetime import datetime

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
            self.drawString(36, 812, "Weekend Ville Maintenance Co-Op Society Ltd. | Treasurer's Financial Report & Budget")
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


def generate_budget_pdf(primary_path: Path, copy_paths: list[Path]) -> bool:
    try:
        # Load society data from Excel
        excel_path = Path("data/society_data.xlsx")
        df_led = pd.read_excel(excel_path, sheet_name="Ledger")
        df_mem = pd.read_excel(excel_path, sheet_name="Members")
        df_exp = pd.read_excel(excel_path, sheet_name="Expenses")

        # Usable width on A4 with 36pt (0.5 in) margins is 523.27 pt
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
            fontSize=12.5,
            leading=15.5,
            textColor=C_PRIMARY,
            alignment=1, # Center
            spaceAfter=1.5,
        )
        st_sub = ParagraphStyle(
            "DocSub",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10.5,
            textColor=C_MUTED,
            alignment=1,
            spaceAfter=1,
        )
        st_banner = ParagraphStyle(
            "BannerTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.0,
            leading=13.0,
            textColor=colors.white,
            alignment=1,
        )
        st_h1 = ParagraphStyle(
            "H1",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=12.0,
            textColor=C_PRIMARY,
            spaceBefore=6,
            spaceAfter=2.5,
            keepWithNext=True,
        )
        st_body = ParagraphStyle(
            "Body",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9.5,
            textColor=C_TEXT,
            spaceAfter=2,
        )
        st_callout = ParagraphStyle(
            "Callout",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=7.0,
            leading=9.2,
            textColor=C_TEXT,
        )

        # Table Styles
        th_style = ParagraphStyle(
            "TH",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=9.2,
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
            fontSize=6.8,
            leading=8.6,
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
        td_red = ParagraphStyle(
            "TDRed",
            parent=td_style_bold,
            textColor=C_RED,
        )
        td_green = ParagraphStyle(
            "TDGreen",
            parent=td_style_bold,
            textColor=C_GREEN,
        )
        td_slate = ParagraphStyle(
            "TDSlate",
            parent=td_style_bold,
            textColor=C_MUTED,
        )

        # Specialized ultra-compact styles for Master 41-Plot Table
        m_th = ParagraphStyle("MTH", parent=th_style, fontSize=7.0, leading=8.5)
        m_th_c = ParagraphStyle("MTHC", parent=th_style_c, fontSize=7.0, leading=8.5)
        m_th_r = ParagraphStyle("MTHR", parent=th_style_r, fontSize=7.0, leading=8.5)
        m_td = ParagraphStyle("MTD", parent=td_style, fontSize=6.5, leading=7.8)
        m_td_bold = ParagraphStyle("MTDBold", parent=td_style_bold, fontSize=6.5, leading=7.8)
        m_td_c = ParagraphStyle("MTDC", parent=td_style_c, fontSize=6.5, leading=7.8)
        m_td_r = ParagraphStyle("MTDR", parent=td_style_r, fontSize=6.5, leading=7.8)
        m_td_r_bold = ParagraphStyle("MTDRBold", parent=td_style_r_bold, fontSize=6.5, leading=7.8)

        elements = []

        # ==================================================================
        # PAGE 1: FINANCIAL STANDING & FIVE-YEAR AUDITED EXPENSES
        # ==================================================================
        elements.append(Paragraph("WEEKEND VILLE MAINTENANCE CO-OPERATIVE SOCIETY LTD.", st_title))
        elements.append(Paragraph("Regn. No.: PNA/MSI/GNL/(O)/4350/FY 2021-2022 | Date of Registration: 24/08/2021", st_sub))
        elements.append(Paragraph("Sr. No. 241/274/287/288/289, Mouze Jatode, Taluka Mulshi, District Pune", st_sub))
        elements.append(Spacer(1, 2))

        banner_table = Table(
            [[Paragraph("TREASURER'S FINANCIAL REPORT, EXPENSE ANALYSIS & FY 2027-28 BUDGET", st_banner)]],
            colWidths=[USABLE_W]
        )
        banner_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_PRIMARY),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        elements.append(banner_table)
        elements.append(Paragraph("Reporting Period: FY 2021-22 through FY 2026-27 (As of 31 October 2026) | Prepared by: Society Treasurer", st_sub))
        elements.append(Spacer(1, 3))

        # 1. Executive Summary Table
        elements.append(Paragraph("1. Executive Summary & Liquid Financial Position (As of 31 Oct 2026)", st_h1))
        exec_data = [
            [Paragraph("Financial Parameter", th_style), Paragraph("Amount (Rs.)", th_style_r), Paragraph("Status & Key Operational Remarks", th_style)],
            [Paragraph("Union Bank of India Savings A/c", td_style_bold), Paragraph("Rs. 1,67,710.67", td_style_r_bold), Paragraph("Verified bank closing balance as of 27-10-2026 (A/c 474902010030343)", td_style)],
            [Paragraph("Term Deposits / Fixed Deposits", td_style_bold), Paragraph("Rs. 1,00,000.00", td_style_r_bold), Paragraph("Funded on 07-04-2026 (Two Rs. 50k FDs: A/c 474903030163834 & 835)", td_style)],
            [Paragraph("Total Liquid Reserves", td_style_bold), Paragraph("Rs. 2,67,710.67", td_style_r_bold), Paragraph("Total available liquid society reserves in bank", td_style_bold)],
            [Paragraph("Cumulative Maintenance Billed (6 FYs)", td_style), Paragraph("Rs. 26,65,000.00", td_style_r), Paragraph("Base demand billed across all 41 plots (FY 21-22 to FY 26-27)", td_style)],
            [Paragraph("Total Member Maintenance Realized", td_style), Paragraph("Rs. 16,14,501.00", td_style_r), Paragraph("Actual cash received in bank account (Overall collection rate: 60.6%)", td_style)],
            [Paragraph("Cumulative Defaulter Outstanding", td_style_bold), Paragraph("Rs. 10,50,499.00", td_style_r_bold), Paragraph("37 out of 41 plots in default in Society Records (39.4% revenue gap)", td_red)],
            [Paragraph("Total Verified Expenditures Paid", td_style_bold), Paragraph("Rs. 14,82,003.33", td_style_r_bold), Paragraph("129 genuine debit entries verified against bank statements (FY 22-27)", td_style)],
        ]
        t_exec = Table(exec_data, colWidths=[150, 90, 283])
        t_exec.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BG_LIGHT]),
        ]))
        elements.append(t_exec)
        elements.append(Spacer(1, 4))

        # 2. Five-Year Spend Matrix Table
        elements.append(Paragraph("2. Five-Year Audited Spend Analysis (FY 22-23 to FY 26-27)", st_h1))
        spend_matrix_data = [
            [
                Paragraph("Expense Category", th_style),
                Paragraph("FY 22-23", th_style_r),
                Paragraph("FY 23-24", th_style_r),
                Paragraph("FY 24-25", th_style_r),
                Paragraph("FY 25-26", th_style_r),
                Paragraph("FY 26-27*", th_style_r),
                Paragraph("Total Spends", th_style_r),
            ],
            [Paragraph("1. Caretaker & Security (Pandit/Shivaji)", td_style_bold), Paragraph("Rs. 1,21,000", td_style_r), Paragraph("Rs. 1,44,000", td_style_r), Paragraph("Rs. 1,44,000", td_style_r), Paragraph("Rs. 1,68,000", td_style_r), Paragraph("Rs. 77,000", td_style_r), Paragraph("Rs. 6,54,000.00", td_style_r_bold)],
            [Paragraph("2. Electricity & Utilities (MSEDCL/MSEB)", td_style_bold), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 33,360", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 1,30,000", td_style_r), Paragraph("Rs. 3,69,097", td_style_r), Paragraph("Rs. 5,32,457.00", td_style_r_bold)],
            [Paragraph("3. Term Deposits / FD Reserves", td_style), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 1,00,000", td_style_r), Paragraph("Rs. 1,00,000.00", td_style_r)],
            [Paragraph("4. Site Maintenance & Member Reimb.", td_style), Paragraph("Rs. 2,220", td_style_r), Paragraph("Rs. 4,844", td_style_r), Paragraph("Rs. 9,700", td_style_r), Paragraph("Rs. 46,445", td_style_r), Paragraph("Rs. 6,750", td_style_r), Paragraph("Rs. 69,959.00", td_style_r)],
            [Paragraph("5. Repairs & Infrastructure (Civil/Pipes)", td_style), Paragraph("Rs. 26,150", td_style_r), Paragraph("Rs. 26,000", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 3,200", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 55,350.00", td_style_r)],
            [Paragraph("6. Accounting & Statutory Audit Fees", td_style), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 18,450", td_style_r), Paragraph("Rs. 8,200", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 26,650.00", td_style_r)],
            [Paragraph("7. Statutory Taxes (Mulshi NA Tax)", td_style), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 7,318", td_style_r), Paragraph("Rs. 14,586", td_style_r), Paragraph("Rs. 7,218", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 29,122.00", td_style_r)],
            [Paragraph("8. Capital Asset (Borewell Motor Pump)", td_style), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 13,916", td_style_r), Paragraph("Rs. 0", td_style_r), Paragraph("Rs. 13,916.00", td_style_r)],
            [Paragraph("9. Bank & Administrative Charges", td_style), Paragraph("Rs. 6", td_style_r), Paragraph("Rs. 16", td_style_r), Paragraph("Rs. 19", td_style_r), Paragraph("Rs. 376", td_style_r), Paragraph("Rs. 133", td_style_r), Paragraph("Rs. 549.33", td_style_r)],
            [Paragraph("Total Verified Society Spends", td_style_bold), Paragraph("Rs. 1,49,376", td_style_r_bold), Paragraph("Rs. 2,15,538", td_style_r_bold), Paragraph("Rs. 1,86,755", td_style_r_bold), Paragraph("Rs. 3,77,355", td_style_r_bold), Paragraph("Rs. 5,52,980", td_style_r_bold), Paragraph("Rs. 14,82,003.33", td_style_r_bold)],
        ]
        t_matrix = Table(spend_matrix_data, colWidths=[155, 56, 56, 56, 56, 62, 82])
        t_matrix.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, C_BG_LIGHT]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ]))
        elements.append(t_matrix)
        elements.append(Paragraph("<font size='6.2' color='#64748B'>*FY 26-27 reflects 7 months of actuals (April to October 2026).</font>", st_body))
        elements.append(Spacer(1, 3))

        # MSEB Clarification Callout Box
        mseb_box = [
            [Paragraph("<b>[FACTUAL CLARIFICATION] Electricity (MSEB) Spends & Meter Transfer:</b><br/>"
                       "&ndash; <b>Root Cause:</b> The society did <i>not receive any electricity bills from MSEDCL for 3 consecutive years</i>. When MSEDCL finally issued bills, it arrived as a consolidated demand with 3 years of accumulated arrears, defaulting interest, and penalty charges.<br/>"
                       "&ndash; <b>Tariff Classification:</b> The connection <b>is billed at Residential rates</b> (not Commercial).<br/>"
                       "&ndash; <b>Ownership Status:</b> All arrears and penalty charges have <b>now been cleared 100% in full</b>. The society has zero pending liabilities with MSEDCL and is fully entitled to complete the transfer of ownership into the Society's registered name.<br/>"
                       "&ndash; <b>Accountant Suspense Entries:</b> In <i>Society Records</i>, all Rs. 43,705 in member reimbursements previously tagged to suspense have been fully audited with vendor bills and allocated to Site Maintenance and Capital Assets.", st_callout)]
        ]
        t_mseb = Table(mseb_box, colWidths=[USABLE_W])
        t_mseb.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#3B82F6")),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t_mseb)

        # End of Page 1
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 2: DEFAULTERS ANALYSIS & SECTION 154B-29 LEGAL FRAMEWORK
        # ==================================================================
        elements.append(Paragraph("3. Defaulter Severity Analysis (Rs. 10.50 Lakhs Dues across 37 Plots)", st_h1))
        
        sev_data = [
            [Paragraph("Severity Bracket", th_style), Paragraph("Plots", th_style_c), Paragraph("Total Dues (Rs.)", th_style_r), Paragraph("Plots & Owners in Default", th_style)],
            [Paragraph("Tier 1: Severe Chronic (Dues >= Rs. 50k)", td_red), Paragraph("9 plots", td_style_c), Paragraph("Rs. 5,72,000.00", td_style_r_bold), Paragraph("Plot 01 Dalvi (Rs. 65k), Plot 09 Chavan (Rs. 65k), Plot 22 Joshi (Rs. 65k), Plot 32 Redkar (Rs. 65k), Plot 35 Bidkar (Rs. 65k), Plot 06 Nimbkar (Rs. 64k), Plot 21 Pawar (Rs. 64k), Plot 02 Raul (Rs. 61k), Plot 31 Joshi (Rs. 58k) [54.3% of total arrears]", td_style)],
            [Paragraph("Tier 2: Major Dues (Rs. 30k – Rs. 50k)", td_style_bold), Paragraph("5 plots", td_style_c), Paragraph("Rs. 2,25,999.00", td_style_r_bold), Paragraph("Plot 41 Dhebe (Rs. 49,999), Plot 28 Pujari (Rs. 46k), Plot 29 Pujari (Rs. 46k), Plot 19 Salunke (Rs. 44k), Plot 36 Palnitkar (Rs. 40k)", td_style)],
            [Paragraph("Tier 3: Moderate Dues (Rs. 10k – Rs. 30k)", td_style), Paragraph("12 plots", td_style_c), Paragraph("Rs. 1,93,000.00", td_style_r), Paragraph("Plot 18 Gavande (Rs. 29k), Plot 27 Bachikar (Rs. 24k), Plot 38 Deshpande (Rs. 18k), Plot 39 Deshpande (Rs. 18k), Plot 03 Ombale (Rs. 15k), Plot 04 Bidkar (Rs. 15k), Plot 23 Modak (Rs. 14k), Plot 11 Salvi (Rs. 12k), Plot 13 Phutane (Rs. 12k), Plot 14 Salvi (Rs. 12k), Plot 25 Snehal Sinkar (Rs. 12k), Plot 40 Salvi (Rs. 12k)", td_style)],
            [Paragraph("Tier 4: Minor / Current Dues (< Rs. 10k)", td_style), Paragraph("11 plots", td_style_c), Paragraph("Rs. 62,500.00", td_style_r), Paragraph("Plot 34 Bidkar (Rs. 9k), Plot 37 Radhakrishnan (Rs. 9k)*, Plot 12 Maskikar (Rs. 8.5k), Plot 10 Bhagwat (Rs. 7k), Plot 05 Rathod (Rs. 5k), Plot 15 Shete (Rs. 5k), Plot 20 Rathod (Rs. 5k), Plot 24 Bhosale (Rs. 5k), Plot 07 Fernandes (Rs. 4k), Plot 08 Kulkarni (Rs. 4k), Plot 17 Bhate (Rs. 1k)", td_style)],
            [Paragraph("Fully Settled (Zero Balance)", td_slate), Paragraph("2 plots", td_style_c), Paragraph("Rs. 0.00", td_style_r), Paragraph("Plot 26 Ashutosh Sinkar & Snehal Sinkar, Plot 30 Kishore Haridas", td_style)],
            [Paragraph("In Surplus (Advance Paid)", td_green), Paragraph("2 plots", td_style_c), Paragraph("-Rs. 3,000.00", td_style_r_bold), Paragraph("Plot 16 Tejashree Bhate (Rs. 1,000 advance), Plot 33 Sangita Sunil Varpe (Rs. 2,000 advance)", td_style)],
            [Paragraph("Total Society Plots Audited", td_style_bold), Paragraph("41 plots", td_style_c), Paragraph("Rs. 10,50,499.00", td_style_r_bold), Paragraph("100% of all 41 plots fully verified in Society Records", td_style_bold)],
        ]
        t_sev = Table(sev_data, colWidths=[130, 45, 80, 268])
        t_sev.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 2.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, C_BG_LIGHT]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ]))
        elements.append(t_sev)
        elements.append(Spacer(1, 2))
        elements.append(Paragraph("<font size='6.3' color='#64748B'>*Note on Plot 37 (Mr. Ajaykumar Radhakrishnan): Fully Settled (Rs. 0.00) in Accountant's Audit Report through 31-March-2026. Current Rs. 9,000 balance represents FY 26-27 demand (Rs. 5,000 paid to date via installments).</font>", st_body))
        elements.append(Spacer(1, 5))

        # Legal Powers Section
        elements.append(Paragraph("4. Legal Powers & Recovery Framework under Section 154B-29 (MCS Act)", st_h1))
        legal_text = (
            "<b>A. What is Section 154B-29 of the Maharashtra Co-operative Societies Act 1960?</b><br/>"
            "Under Chapter XIII-B of the MCS Act (inserted by 2019 Amendment specifically for Housing and Maintenance/Dekhbaal Societies), "
            "Section 154B-29 provides a specialized fast-track summary recovery code that replaces old Section 101. "
            "The certified statement of dues signed by the Secretary/Treasurer is admitted as <i>prima facie</i> evidence before the Deputy Registrar. "
            "Upon summary hearing, the Registrar issues an official <b>Recovery Certificate</b> with interest up to <b>21% per annum</b>. "
            "The Certificate has the force of a civil decree and is executed as arrears of land revenue by the Recovery Officer—empowering "
            "freezing of bank accounts, attachment of movable assets, placing liens on Revenue 7/12 extracts, and auctioning the plot.<br/><br/>"
            "<b>B. Can the Society Disconnect Water to Individual Plots in a Maintenance Society?</b><br/>"
            "&ndash; <i>Non-Essential Water (Construction, Farmhouse Lawns, Gardening, Tankers):</i> The Managing Committee <b>has immediate authority to cut off and disconnect</b> common water supply to defaulting plots. Non-payers have no legal right to consume common pumped water for horticulture or construction.<br/>"
            "&ndash; <i>Domestic Water Supply (Due Process Rule):</i> While basic drinking water is an essential amenity, the society is a private pumping entity operated via common electricity. Under Maharashtra co-operative law, domestic water can be restricted/disconnected <b>provided due process is followed:</b><br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Formal General Body AGM Resolution authorizing utility disconnection for defaults exceeding 12 months.<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Issuance of a formal 15-Day Final Notice giving opportunity to pay or sign an approved EMI.<br/>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. Disconnection of sub-valves from the common pipeline if unresolved.<br/>"
            "&ndash; <i>Administrative Sanctions:</i> Complete withholding of Society NOC for sale, transfer, mortgage, or PMRDA/Panchayat construction permits."
        )
        t_legal = Table([[Paragraph(legal_text, st_body)]], colWidths=[USABLE_W])
        t_legal.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
            ("BOX", (0, 0), (-1, -1), 0.8, C_AMBER),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t_legal)

        # End of Page 2
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 3: COMPLETE MASTER 41-PLOT LEDGER AUDIT TABLE
        # ==================================================================
        elements.append(Paragraph("5. Master 41-Plot Ledger Audit Table (As of 31 October 2026)", st_h1))
        elements.append(Paragraph("Complete individual plot reconciliation between Billed Maintenance, Actual Bank Payments, and Net Dues in Society Records:", st_body))

        master_headers = [
            Paragraph("Plot", m_th_c),
            Paragraph("Plot Owner Name", m_th),
            Paragraph("Billed (Dr)", m_th_r),
            Paragraph("Paid (Cr)", m_th_r),
            Paragraph("Net Balance", m_th_r),
            Paragraph("Status in Society Records", m_th_c),
        ]
        master_rows = [master_headers]

        # Process all 41 plots sorted by plot number
        df_mem_sorted = df_mem.copy()
        df_mem_sorted["Plot_Num"] = df_mem_sorted["Plot_No"].apply(lambda p: int(p) if str(p).isdigit() else 999)
        df_mem_sorted = df_mem_sorted.sort_values("Plot_Num")

        for _, m in df_mem_sorted.iterrows():
            mid = m["ID"]
            plot_no = str(m["Plot_No"]).strip()
            name = str(m["Plot_Owner_Name"]).strip()
            
            m_led = df_led[df_led["Member_ID"] == mid]
            tot_dr = float(m_led["Debit"].fillna(0).sum())
            tot_cr = float(m_led["Credit"].fillna(0).sum())
            net = tot_dr - tot_cr

            if net > 1.0:
                if net >= 50000:
                    status_para = Paragraph("<font color='#B91C1C'><b>[CHRONIC DEFAULTER]</b></font>", m_td_c)
                elif net >= 30000:
                    status_para = Paragraph("<font color='#C2410C'><b>[MAJOR DEFAULTER]</b></font>", m_td_c)
                else:
                    status_para = Paragraph("<font color='#854D0E'><b>[MODERATE DEFAULTER]</b></font>", m_td_c)
                bal_para = Paragraph(f"Rs. {net:,.2f}", m_td_r_bold if net >= 30000 else m_td_r)
            elif net < -1.0:
                status_para = Paragraph("<font color='#15803D'><b>[SURPLUS / ADVANCE]</b></font>", m_td_c)
                bal_para = Paragraph(f"+Rs. {abs(net):,.2f}", m_td_r_bold)
            else:
                status_para = Paragraph("<font color='#475569'><b>[FULLY SETTLED]</b></font>", m_td_c)
                bal_para = Paragraph("Rs. 0.00", m_td_r)

            master_rows.append([
                Paragraph(f"<b>Plot {plot_no.zfill(2)}</b>", m_td_c),
                Paragraph(name[:36], m_td),
                Paragraph(f"Rs. {tot_dr:,.0f}", m_td_r),
                Paragraph(f"Rs. {tot_cr:,.0f}", m_td_r),
                bal_para,
                status_para,
            ])

        # Add total row
        tot_billed = df_mem_sorted["ID"].apply(lambda mid: df_led[df_led["Member_ID"] == mid]["Debit"].fillna(0).sum()).sum()
        tot_paid = df_mem_sorted["ID"].apply(lambda mid: df_led[df_led["Member_ID"] == mid]["Credit"].fillna(0).sum()).sum()
        tot_net = tot_billed - tot_paid

        master_rows.append([
            Paragraph("<b>Total</b>", m_td_c),
            Paragraph("<b>41 Society Plots Master Total</b>", m_td_bold),
            Paragraph(f"<b>Rs. {tot_billed:,.0f}</b>", m_td_r_bold),
            Paragraph(f"<b>Rs. {tot_paid:,.0f}</b>", m_td_r_bold),
            Paragraph(f"<b>Rs. {tot_net:,.0f}</b>", m_td_r_bold),
            Paragraph("<b>60.6% Collection</b>", m_td_c),
        ])

        t_master = Table(master_rows, colWidths=[40, 165, 58, 58, 68, 134])
        t_master.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.35, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, C_BG_LIGHT]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ]))
        elements.append(t_master)

        # End of Page 3
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 4: PROPOSED OPEX ROUTINE BUDGET & 3-TIER PRIORITIZED CAPEX
        # ==================================================================
        elements.append(Paragraph("6. Proposed Next FY Operational Budget (OPEX) — Rs. 5,38,000 / Year", st_h1))
        
        opex_data = [
            [Paragraph("Operational Expense Head", th_style), Paragraph("Annual Budget", th_style_r), Paragraph("Scope, Staffing & Operational Details", th_style)],
            [Paragraph("1. Caretaker & Security (Pandit Hiraji)", td_style_bold), Paragraph("Rs. 1,82,000", td_style_r_bold), Paragraph("Salary hike from Rs. 12k to Rs. 14k/mo + 1-month Diwali bonus (Essential retention)", td_style)],
            [Paragraph("2. Dedicated Society Property Manager", td_style_bold), Paragraph("Rs. 1,08,000", td_style_r_bold), Paragraph("Part-time site supervisor @ Rs. 9,000/mo (Daily oversight of pumps, security & vendors)", td_style)],
            [Paragraph("3. Regularized MSEB Electricity Bill", td_style), Paragraph("Rs. 1,44,000", td_style_r), Paragraph("Post-arrears regularized residential bill @ Rs. 12k/mo (drops to Rs. 3k/mo post-solar)", td_style)],
            [Paragraph("4. Statutory Taxes (Mulshi NA Tax & Cess)", td_style), Paragraph("Rs. 16,000", td_style_r), Paragraph("Annual Tahsildar Mulshi non-agricultural revenue tax & Gram Panchayat cess", td_style)],
            [Paragraph("5. Statutory Audit & Account Writing Fees", td_style), Paragraph("Rs. 18,000", td_style_r), Paragraph("Statutory Auditor fee Rs. 5k + Walunj professional accounting & filing charges Rs. 13k", td_style)],
            [Paragraph("6. Seasonal Grass Cutting & Land Clearing", td_style), Paragraph("Rs. 24,000", td_style_r), Paragraph("3 seasonal community trims (pre-monsoon, post-monsoon, winter bush clearing)", td_style)],
            [Paragraph("7. Water Pump & Valve Maintenance", td_style), Paragraph("Rs. 25,000", td_style_r), Paragraph("Pump lubrication, valve replacements, underground distribution pipe leak fixes", td_style)],
            [Paragraph("8. Common Street Lights & Electricals", td_style), Paragraph("Rs. 15,000", td_style_r), Paragraph("LED bulb replacements on common poles, wire joint insulation, switchgear", td_style)],
            [Paragraph("9. AGM Logistics, Printing & SMS Charges", td_style), Paragraph("Rs. 6,000", td_style_r), Paragraph("Annual meeting venue, audit report printouts, statutory SMS notifications", td_style)],
            [Paragraph("Total Annual Routine OPEX", td_style_bold), Paragraph("Rs. 5,38,000", td_style_r_bold), Paragraph("Rs. 44,833 / month across society = Rs. 1,093 / month per plot baseline", td_style_bold)],
        ]
        t_opex = Table(opex_data, colWidths=[150, 75, 298])
        t_opex.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, C_BG_LIGHT]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ]))
        elements.append(t_opex)
        elements.append(Spacer(1, 5))

        # 7. Prioritized CAPEX Budget
        elements.append(Paragraph("7. Prioritized Capital Expenditure (CAPEX) Budget — Rs. 8,32,000 Total", st_h1))
        
        capex_data = [
            [Paragraph("Priority & Project Title", th_style), Paragraph("Estimated Cost", th_style_r), Paragraph("Strategic Return, Justification & Priority Classification", th_style)],
            # Category 1: MUST HAVE
            [Paragraph("<b>Category 1: MUST HAVE (Non-Negotiable Legal & Critical Essentials)</b>", ParagraphStyle("Cat1", parent=td_style_bold, textColor=C_RED)), Paragraph("<b>Rs. 2,05,000</b>", td_style_r_bold), Paragraph("<b>Mandatory statutory compliance and operational survivability</b>", td_style_bold)],
            [Paragraph("1. Legal Title of Club House & Common Area", td_style), Paragraph("Rs. 1,00,000", td_style_r), Paragraph("Deemed conveyance proceedings, title deed drafting, retaining specialized lawyer", td_style)],
            [Paragraph("2. MSEB Meter Ownership Transfer", td_style), Paragraph("Rs. 40,000", td_style_r), Paragraph("Transfer meter from developer to Society name (Zero arrears; ready for transfer)", td_style)],
            [Paragraph("3. Standby Water Pump & Valve Manifold", td_style), Paragraph("Rs. 65,000", td_style_r), Paragraph("Install backup pump, replace corroded distribution manifold, stop water leaks", td_style)],
            # Category 2: IMMEDIATE ATTENTION
            [Paragraph("<b>Category 2: REQUIRES IMMEDIATE ATTENTION (Infrastructure & Modernization)</b>", ParagraphStyle("Cat2", parent=td_style_bold, textColor=C_SECONDARY)), Paragraph("<b>Rs. 5,77,000</b>", td_style_r_bold), Paragraph("<b>Permanent cost reduction and security infrastructure</b>", td_style_bold)],
            [Paragraph("4. Solar Power Plant (5-7 kWp On-Grid)", td_style), Paragraph("Rs. 3,25,000", td_style_r), Paragraph("Rooftop on Pump House. Slashes MSEB power bills by 75-80%. Payback in 2.5 yrs!", td_style)],
            [Paragraph("5. CCTV Security Surveillance Network", td_style), Paragraph("Rs. 1,35,000", td_style_r), Paragraph("10-12 IP HD Cameras (Gate, Main Junctions, Pump House) with 4K NVR & UPS", td_style)],
            [Paragraph("6. Railings Red Oxide & Gate Overhaul", td_style), Paragraph("Rs. 70,000", td_style_r), Paragraph("Scraping, anti-rust red oxide on railings (Rs. 45k) + Main gate overhaul & paint (Rs. 25k)", td_style)],
            [Paragraph("7. Storm Drainage Gutters Deep Clean", td_style), Paragraph("Rs. 35,000", td_style_r), Paragraph("Excavator channel clearing & stone reinforcement to stop plot monsoon flooding", td_style)],
            [Paragraph("8. Grass Cutting Machine Overhaul", td_style), Paragraph("Rs. 12,000", td_style_r), Paragraph("Engine overhaul, new heavy-duty cutting blades, carburettor replacement", td_style)],
            # Category 3: NICE TO HAVE
            [Paragraph("<b>Category 3: NICE TO HAVE (Downplayed / Phase 2 Execution)</b>", ParagraphStyle("Cat3", parent=td_style_bold, textColor=C_GREEN)), Paragraph("<b>Rs. 50,000</b>", td_style_r_bold), Paragraph("<b>Non-critical community recreation enhancement</b>", td_style_bold)],
            [Paragraph("9. Children's Play Area & Basic Trees", td_style), Paragraph("Rs. 50,000", td_style_r), Paragraph("Basic leveling of pump house ground, simple safety fence, swing & shade trees", td_style)],
            [Paragraph("Total Prioritized CAPEX Outlay", td_style_bold), Paragraph("Rs. 8,32,000", td_style_r_bold), Paragraph("Funded via Special Levy of Rs. 20,000 / plot (in two Rs. 10,000 installments)", td_style_bold)],
        ]
        t_capex = Table(capex_data, colWidths=[150, 75, 298])
        t_capex.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PRIMARY),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, C_BG_LIGHT]),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#FEE2E2")),
            ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#E0E7FF")),
            ("BACKGROUND", (0, 11), (-1, 11), colors.HexColor("#DCFCE7")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ]))
        elements.append(t_capex)

        # End of Page 4
        elements.append(PageBreak())

        # ==================================================================
        # PAGE 5: RECOMMENDATIONS, RESOLUTIONS & CERTIFICATION
        # ==================================================================
        elements.append(Paragraph("8. Treasurer's Funding Recommendations & Defaulter Linkage", st_h1))
        
        recom_text = (
            "&ndash; <b>Recommendation A (Monthly Maintenance Revision):</b> Revise monthly charges from Rs. 1,000 to <b>Rs. 1,500 / month per plot</b> (Rs. 18,000 / year). "
            "Generates Rs. 7,38,000 / year, fully covering the Rs. 5.38L OPEX while generating a <b>Rs. 2.00 Lakh annual surplus</b> for the Statutory Sinking Fund.<br/>"
            "&ndash; <b>Recommendation B (Special Capital Development Levy):</b> Approve a one-time levy of <b>Rs. 20,000 per plot</b>, payable in two installments of Rs. 10,000 "
            "over 6 months. Generates Rs. 8,20,000 to fully fund the Must Have and Immediate Attention projects debt-free.<br/>"
            "&ndash; <b>Recommendation C (Defaulter Recovery Linkage):</b> Every rupee recovered from the <b>Rs. 10.50 Lakhs in defaulter arrears</b> under Section 154B-29 "
            "will be placed directly into the Capital Development Fund to <b>fast-track the Solar Power Plant and CCTV network</b>, or directly reduce the Special Capital Levy on compliant members!"
        )
        t_rec = Table([[Paragraph(recom_text, st_body)]], colWidths=[USABLE_W])
        t_rec.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
            ("BOX", (0, 0), (-1, -1), 0.8, C_GREEN),
            ("TOPPADDING", (0, 0), (-1, -1), 3.0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t_rec)
        elements.append(Spacer(1, 4))

        # 9. Draft AGM Resolutions
        elements.append(Paragraph("9. Formal Draft AGM Resolutions for General Body Adoption", st_h1))

        resolutions = [
            ("Resolution No. 1: Adoption of Five-Year Audited Expenses",
             "RESOLVED THAT the General Body hereby approves and adopts the Audited Expenditure Statement for FY 2021-22 through FY 2026-27 (as of 31 October 2026) totaling Rs. 14,82,003.33 across 129 verified bank debit entries, as presented by the Society Treasurer."),
            ("Resolution No. 2: Revision of Monthly Maintenance Charges to Rs. 1,500",
             "RESOLVED THAT the monthly maintenance charges payable by each plot owner be revised from Rs. 1,000/- to Rs. 1,500/- per month (Rs. 18,000/- per annum) effective 01 April 2027 to cover inflation, caretaker retention, and professional property management."),
            ("Resolution No. 3: Approval of Caretaker (Pandit) Salary Increment",
             "RESOLVED THAT the monthly salary of Society Caretaker Mr. Pandit Hiraji Vairal be enhanced from Rs. 12,000/- to Rs. 14,000/- per month, plus one-month annual Diwali festive bonus."),
            ("Resolution No. 4: Authorization to Retain a Society Property Manager",
             "RESOLVED THAT the Managing Committee be authorized to engage a part-time Society Property Manager at remuneration not exceeding Rs. 9,000/- per month for daily supervision of water pumps, caretaker logbooks, and vendor repairs."),
            ("Resolution No. 5: Sanction of Special Capital Development Levy & Modernization",
             "RESOLVED THAT a Special Capital Development Levy of Rs. 20,000/- per plot, payable in two equal installments of Rs. 10,000/-, be approved for: (1) Legal Ownership conveyance of Club House & common layout with legal counsel (Rs. 1.00L); (2) MSEB Meter transfer (Rs. 40k); (3) Standby water pump & manifold overhaul (Rs. 65k); (4) 5-7 kWp Solar Power Plant (Rs. 3.25L); (5) CCTV surveillance network (Rs. 1.35L); (6) Railing red oxide & gate overhaul (Rs. 70k); (7) Gutter cleaning (Rs. 35k); (8) Grass machine overhaul (Rs. 12k); (9) Basic play area & landscaping (Rs. 50k)."),
            ("Resolution No. 6: Statutory Recovery under Section 154B-29 & Water Regulation",
             "RESOLVED THAT a 30-Day Amnesty Window (ending 31 December 2026) be granted with 100% interest waiver. FURTHER RESOLVED THAT for all plot owners failing to regularize dues by 31 December 2026, the Managing Committee is directed to: (1) Issue Statutory Demand Notices with 21% p.a. interest; (2) File recovery applications before the Deputy Registrar under Section 154B-29; (3) Immediately disconnect common water for non-essential uses (construction, lawns, gardening), and restrict domestic water following a 15-day notice; (4) Withhold all Society NOCs for sale, transfer, lease, mortgage, or building permissions until 100% dues are cleared.")
        ]

        res_table_rows = []
        for r_title, r_text in resolutions:
            res_table_rows.append([Paragraph(f"<b>{r_title}</b>", td_style_bold)])
            res_table_rows.append([Paragraph(f"<i>\"{r_text}\"</i>", td_style)])
            res_table_rows.append([Spacer(1, 1.2)])

        t_res = Table(res_table_rows, colWidths=[USABLE_W])
        t_res.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t_res)
        elements.append(Spacer(1, 5))

        # Certification & Sign-off Block
        cert_box = [[
            Paragraph("<b>REPORT CERTIFICATION & SUBMISSION TO GENERAL BODY</b><br/>"
                      "I hereby certify that the financial figures, bank reconciliations, 5-year spend analyses, and 41-plot ledger audits presented in this document represent true and verified records extracted from the Society's official Union Bank of India account statements and audited books of account.<br/><br/>"
                      "<b>Ashutosh Sinkar</b><br/>Hon. Treasurer, Weekend Ville Maintenance Co-Operative Society Ltd.<br/>Date of Presentation: 22 November 2026", st_body)
        ]]
        t_cert = Table(cert_box, colWidths=[USABLE_W])
        t_cert.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX", (0, 0), (-1, -1), 0.8, C_PRIMARY),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
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
    primary = Path("Weekend_Ville_Treasurer_Budget_and_Expense_Analysis.pdf")
    copies = [
        Path("data/staging/whatsapp/Weekend_Ville_Treasurer_Budget_and_Expense_Analysis.pdf"),
        Path("/Users/ashutoshsinkar/.gemini/antigravity/brain/db392fa2-4f19-47cd-a060-f89008858d15/Weekend_Ville_Treasurer_Budget_and_Expense_Analysis.pdf"),
    ]
    generate_budget_pdf(primary, copies)
