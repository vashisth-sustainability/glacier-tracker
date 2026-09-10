from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_site_pdf(asset_info, sat_data, output_pdf_name):
    doc = SimpleDocTemplate(output_pdf_name, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1a365d'), spaceAfter=12)
    heading_style = ParagraphStyle('HeadStyle', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#2c5282'), spaceAfter=10)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=10, leading=14, spaceAfter=8)

    # PAGE 1: Executive Summary
    story.append(Paragraph(f"<b>10-PAGE DETAILED RISK ASSESSMENT REPORT</b>", title_style))
    story.append(Paragraph(f"<b>Asset Name:</b> {asset_info['name']}", heading_style))
    story.append(Paragraph(f"<b>Asset ID:</b> {asset_info['id']} | <b>River Basin:</b> {asset_info['river']}", body_style))
    story.append(Spacer(1, 15))
    
    table_data = [
        ['Parameter', 'Current Value', 'Risk Flag'],
        ['Lake Surface Area', f"{sat_data['lake_area_sq_km']} sq. km", sat_data['status']],
        ['Latest Satellite Pass', sat_data['date'], 'Verified'],
        ['Installed Capacity', asset_info['capacity'], 'Baseline Information']
    ]
    t = Table(table_data, colWidths=[150, 150, 150])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#ebf8ff')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#2b6cb0')),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(PageBreak())

    # PAGE 2: Geomorphology & Catchment Analysis
    story.append(Paragraph("<b>PAGE 2: GEOMORPHOLOGY & BASIN HYDROLOGY</b>", heading_style))
    story.append(Paragraph("This section covers structural geology, river gradients, and mass balance stability...", body_style))
    story.append(PageBreak())

    # PAGE 3 - PAGE 10: Baaki Sections
    for page_num in range(3, 11):
        story.append(Paragraph(f"<b>PAGE {page_num}: DETAILED TECHNICAL SECTION {page_num}</b>", heading_style))
        story.append(Paragraph("Automated satellite metrics, velocity vectors, and evacuation protocols go here.", body_style))
        if page_num < 10:
            story.append(PageBreak())

    doc.build(story)
    print(f"✅ Generated 10-page report: {output_pdf_name}")
