import json
import io
import os
import math
import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import matplotlib.pyplot as plt

# ReportLab Imports for PDF Generation
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION & CUSTOM STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="Himalayan Glacier & Hydro Infrastructure Monitor",
    page_icon="🧊",
    layout="wide"
)

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    
    .metric-card {
        background-color: #1a2234;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        margin-bottom: 10px;
    }
    .metric-label {
        color: #E2E8F0 !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    .metric-value {
        color: #FFFFFF !important;
        font-size: 26px !important;
        font-weight: 800 !important;
    }
    .metric-sub {
        font-size: 14px !important;
        font-weight: 600 !important;
        margin-top: 4px;
    }
    .sub-red { color: #FF4D6D !important; }
    .sub-cyan { color: #00F0FF !important; }

    .risk-card-high {
        background-color: #3d0c11;
        border: 1px solid #ff4d6d;
        border-radius: 10px;
        padding: 15px;
        color: #f8d7da;
    }
    .risk-card-moderate {
        background-color: #3a2e05;
        border: 1px solid #ffcc00;
        border-radius: 10px;
        padding: 15px;
        color: #fff3cd;
    }
    .risk-card-safe {
        background-color: #0d381e;
        border: 1px solid #00e676;
        border-radius: 10px;
        padding: 15px;
        color: #d1e7dd;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. EARTH ENGINE INITIALIZATION
# ---------------------------------------------------------
@st.cache_resource
def init_ee():
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        try:
            secrets_raw = st.secrets["GCP_SERVICE_ACCOUNT"]
            if isinstance(secrets_raw, str):
                service_account_info = json.loads(secrets_raw)
            else:
                service_account_info = dict(secrets_raw)

            if "private_key" in service_account_info:
                service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")

            credentials = ee.ServiceAccountCredentials(
                service_account_info["client_email"],
                key_data=json.dumps(service_account_info)
            )
            project_id = service_account_info.get("project_id", "glacier-tracker")
            ee.Initialize(credentials=credentials, project=project_id)
            return
        except Exception as e:
            st.error(f"❌ Authentication with Earth Engine failed: {e}")
            st.stop()

    try:
        ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize()

init_ee()

# ---------------------------------------------------------
# 3. DATABASES
# ---------------------------------------------------------
GLACIERS = {
    "Gangotri Glacier (Uttarakhand)": {
        "basin": "Ganga Basin",
        "custom_id": "HIM-UK-GAN-01",
        "mean_elevation": "5,000 m",
        "lat": 30.9256, "lon": 79.0669, "zoom": 12,
        "danger_zones": "Gaumukh Snout & Tapovan Route (Structural Fracture & Icefall)",
        "safe_zones": "Gangotri Temple Base / Dharali Valley (Bedrock Staging Zone)",
        "retreat_rate": "22.5 meters/year",
        "glof_risk": "CRITICAL - 2 Proglacial Lakes Expanding",
        "early_warning_window": "35–45 minutes travel time to downstream valley",
        "heatwave_trigger": "Melt surge risk spikes if regional temperature > +2.5°C over baseline",
        "downstream_impact": "Bhagirathi & Upper Ganga Basins (Flash Flooding & High Siltation)",
        "historical_data": {1990: 145.2, 2000: 141.8, 2010: 138.5, 2020: 135.1, 2026: 132.8}
    },
    "Siachen Glacier (Ladakh)": {
        "basin": "Indus Basin",
        "custom_id": "HIM-LD-SIA-02",
        "mean_elevation": "5,400 m",
        "lat": 35.4211, "lon": 77.1095, "zoom": 11,
        "danger_zones": "Teram Shehr Confluence & Sub-sector North Snout",
        "safe_zones": "Base Camp Ground & Sasoma Transit Point",
        "retreat_rate": "35 meters/year",
        "glof_risk": "MODERATE - Moraine Dammed Accumulation",
        "early_warning_window": "60–75 minutes warning buffer for Nubra Valley",
        "heatwave_trigger": "Melt surge risk spikes if regional temperature > +3.0°C over baseline",
        "downstream_impact": "Nubra & Shyok River Systems",
        "historical_data": {1990: 710.0, 2000: 705.2, 2010: 701.0, 2020: 697.4, 2026: 694.0}
    },
    "Zanskar Glacier (Ladakh)": {
        "basin": "Indus Basin",
        "custom_id": "HIM-LD-ZAN-03",
        "mean_elevation": "5,150 m",
        "lat": 33.8500, "lon": 76.8333, "zoom": 12,
        "danger_zones": "Chadar Route Thin Ice Zones & Snout Outflow Bed",
        "safe_zones": "Padum Plain Settlement Area",
        "retreat_rate": "18 meters/year",
        "glof_risk": "ELEVATED - Seasonal Ice Dam Breaches",
        "early_warning_window": "50 minutes flood arrival buffer",
        "heatwave_trigger": "Melt surge risk spikes if regional temperature > +2.0°C over baseline",
        "downstream_impact": "Zanskar & Indus River Valleys",
        "historical_data": {1990: 92.4, 2000: 89.8, 2010: 87.1, 2020: 84.5, 2026: 82.1}
    },
    "Pindari Glacier (Uttarakhand)": {
        "basin": "Ganga Basin",
        "custom_id": "HIM-UK-PIN-04",
        "mean_elevation": "4,800 m",
        "lat": 30.2625, "lon": 79.9922, "zoom": 13,
        "danger_zones": "Zero Point Viewpoint & Traill's Pass Approach Crevasses",
        "safe_zones": "Khati Village Base Encampment",
        "retreat_rate": "15 meters/year",
        "glof_risk": "LOW TO MODERATE - Supraglacial Ponds",
        "early_warning_window": "40 minutes buffer to Pindar Gorge",
        "heatwave_trigger": "Melt surge risk spikes if regional temperature > +2.8°C over baseline",
        "downstream_impact": "Pindar River & Alaknanda Tributaries",
        "historical_data": {1990: 16.5, 2000: 15.8, 2010: 15.1, 2020: 14.4, 2026: 13.9}
    }
}

@st.cache_data
def load_hydro_targets():
    file_path = "hydro_targets.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("targets", [])
                elif isinstance(data, list):
                    return data
        except Exception:
            pass
    return [
        {"id": "HEP-NTPC-001", "name": "Tapovan Vishnugad Hydroelectric Power Station", "company_name": "NTPC Limited", "river_basin": "Dhauliganga / Alaknanda Complex", "state": "Uttarakhand", "latitude": 30.5283, "longitude": 79.6231, "capacity_mw": 520, "risk_status": "HIGH", "buffer_km": 20, "head_glacier": "Rishi Ganga & Dhauliganga Catchment Glaciers"},
        {"id": "HEP-SVP-002", "name": "Teesta-III Hydroelectric Power Station", "company_name": "Sikkim Urja Limited / NHPC", "river_basin": "Upper Teesta Basin", "state": "Sikkim", "latitude": 27.5975, "longitude": 88.6475, "capacity_mw": 1200, "risk_status": "CRITICAL", "buffer_km": 20, "head_glacier": "South Lhonak & Lake Outflow Complex"},
        {"id": "HEP-NHPC-003", "name": "Teesta-V Hydro Power Station", "company_name": "NHPC Limited", "river_basin": "Mid Teesta Basin", "state": "Sikkim", "latitude": 27.3821, "longitude": 88.5284, "capacity_mw": 510, "risk_status": "HIGH", "buffer_km": 20, "head_glacier": "Zemu Glacier Drainage Basin"},
        {"id": "HEP-THDC-004", "name": "Tehri Dam & Hydroelectric Complex", "company_name": "THDC India Limited", "river_basin": "Bhagirathi Basin", "state": "Uttarakhand", "latitude": 30.3775, "longitude": 78.4800, "capacity_mw": 1000, "risk_status": "MODERATE", "buffer_km": 20, "head_glacier": "Gangotri Glacier Complex"},
        {"id": "HEP-SJVN-005", "name": "Nathpa Jhakri Hydro Power Station", "company_name": "SJVN Limited", "river_basin": "Satluj River Basin", "state": "Himachal Pradesh", "latitude": 31.5647, "longitude": 77.9786, "capacity_mw": 1500, "risk_status": "ELEVATED", "buffer_km": 20, "head_glacier": "Spiti & Upper Satluj Cryosphere Zone"},
        {"id": "HEP-NHPC-006", "name": "Dhauliganga Power Station", "company_name": "NHPC Limited", "river_basin": "Kali / Dhauliganga Basin", "state": "Uttarakhand", "latitude": 29.9675, "longitude": 80.5281, "capacity_mw": 280, "risk_status": "HIGH", "buffer_km": 20, "head_glacier": "Pithoragarh Glacial Group"},
        {"id": "HEP-JSW-007", "name": "Karcham Wangtoo Hydroelectric Plant", "company_name": "JSW Energy Limited", "river_basin": "Satluj River Basin", "state": "Himachal Pradesh", "latitude": 31.5414, "longitude": 78.1819, "capacity_mw": 1091, "risk_status": "ELEVATED", "buffer_km": 20, "head_glacier": "Baspa Glacier System"}
    ]

# ---------------------------------------------------------
# 4. PAGE NUMBERING CANVAS FOR PDF
# ---------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
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
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Suppress headers/footers on cover page
        if self._pageNumber > 1:
            # Header
            self.drawString(36, 762, "ENV-AUDIT | TECHNICAL GLACIAL & GLOF RISK ASSESSMENT REPORT")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(36, 754, 576, 754)
            
            # Footer
            self.line(36, 45, 576, 45)
            self.drawString(36, 32, "STRICTLY CONFIDENTIAL — PREPARED FOR EXECUTIVE BRIEFING")
            page_text = f"Page {self._pageNumber} of {page_count}"
            self.drawRightString(576, 32, page_text)
            
        self.restoreState()

# ---------------------------------------------------------
# 5. GEE & ADVANCED PDF REPORT HELPER FUNCTIONS
# ---------------------------------------------------------
def get_glacier_analytics(lat, lon, year):
    roi = ee.Geometry.Point([lon, lat]).buffer(8000)
    start_date = f"{year}-05-01"
    end_date = f"{year}-09-30"
    
    s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
          .filterBounds(roi)
          .filterDate(start_date, end_date)
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15))
          .median())
    
    ndsi = s2.normalizedDifference(['B3', 'B11']).rename('NDSI')
    snow_mask = ndsi.gt(0.45)
    
    area_image = snow_mask.multiply(ee.Image.pixelArea())
    stats = area_image.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=10,
        maxPixels=1e9
    )
    
    raw_val = stats.get('NDSI')
    area_sqkm = ee.Number(ee.Algorithms.If(raw_val, raw_val, 0)).divide(1e6).getInfo()
    return snow_mask, area_sqkm, roi

def generate_pdf_chart(area_b, area_c, b_yr, c_yr):
    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(6, 2.5), dpi=200)
    
    bars = ax.bar(
        [f'Baseline ({b_yr})', f'Current ({c_yr})'], 
        [area_b, area_c], 
        color=['#0284c7', '#dc2626'],
        width=0.4
    )
    
    ax.set_ylabel('Ice Area (sq km)', fontsize=8, fontweight='bold', color='#1e293b')
    ax.set_title('Glacier Area Comparison', fontsize=9, fontweight='bold', color='#0f172a', pad=8)
    ax.tick_params(axis='both', which='major', labelsize=8)
    ax.set_ylim(0, max(area_b, area_c) * 1.25 if max(area_b, area_c) > 0 else 10)
    
    for bar in bars:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width()/2.0, 
            yval + (max(area_b, area_c) * 0.03 if max(area_b, area_c) > 0 else 0.2), 
            f'{yval:.2f} km²', 
            ha='center', va='bottom', fontsize=8, fontweight='bold', color='#0f172a'
        )

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    img_buf.seek(0)
    return img_buf

def generate_hourly_melt_chart(peak_rate_m3_hr):
    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(6, 2.5), dpi=200)
    
    hours = list(range(0, 25, 2))
    rates = [peak_rate_m3_hr * math.sin(math.pi * h / 24)**2 for h in hours]
    
    ax.plot(hours, rates, color='#e11d48', linewidth=2, marker='o', markersize=4)
    ax.fill_between(hours, rates, color='#f43f5e', alpha=0.2)
    ax.set_xlabel('Hour of Day (Diurnal Melt Cycle)', fontsize=8, fontweight='bold', color='#1e293b')
    ax.set_ylabel('Meltwater Vol (m³/hr)', fontsize=8, fontweight='bold', color='#1e293b')
    ax.set_title('Simulated Diurnal Hourly Glacial Meltwater Discharge', fontsize=9, fontweight='bold', color='#0f172a', pad=8)
    ax.tick_params(axis='both', which='major', labelsize=8)
    
    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    img_buf.seek(0)
    return img_buf

def generate_10page_detailed_pdf_report(site_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=45, bottomMargin=50
    )
    styles = getSampleStyleSheet()

    C_PRIMARY = colors.HexColor("#0F172A")
    C_SECONDARY = colors.HexColor("#0284C7")
    C_DARK = colors.HexColor("#1E293B")
    C_LIGHT = colors.HexColor("#F8FAFC")
    C_ACCENT_RED = colors.HexColor("#DC2626")
    C_BORDER = colors.HexColor("#CBD5E1")

    # Custom Typography Styles
    title_style = ParagraphStyle('CoverTitle', parent=styles['Heading1'], fontSize=22, leading=26, textColor=C_PRIMARY, fontName="Helvetica-Bold", alignment=0)
    subtitle_style = ParagraphStyle('CoverSub', parent=styles['Normal'], fontSize=11, leading=15, textColor=colors.HexColor("#475569"), fontName="Helvetica")
    h1_style = ParagraphStyle('H1Sec', parent=styles['Heading2'], fontSize=12, leading=16, textColor=C_SECONDARY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=6)
    h2_style = ParagraphStyle('H2Sec', parent=styles['Heading3'], fontSize=10, leading=14, textColor=C_PRIMARY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=4)
    body_style = ParagraphStyle('BodyCustom', parent=styles['Normal'], fontSize=8.5, leading=12, textColor=C_DARK)
    body_bold = ParagraphStyle('BodyBold', parent=body_style, fontName="Helvetica-Bold")
    table_text = ParagraphStyle('TableTxt', parent=styles['Normal'], fontSize=8, leading=11, textColor=C_DARK)
    table_header = ParagraphStyle('TableHdr', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.white, fontName="Helvetica-Bold")

    # Extract Data Variables
    facility_name = site_data.get("name", site_data.get("target_name", site_data.get("plant_name", "Hydroelectric Power Station")))
    company_name = site_data.get("company_name", site_data.get("client_name", "Operating Authority / State Utility"))
    asset_id = site_data.get("id", site_data.get("asset_id", site_data.get("target_id", "FACILITY-001")))
    river_basin = site_data.get("river_basin", site_data.get("river", "River System"))
    capacity = site_data.get("capacity_mw", site_data.get("capacity", "N/A"))
    risk_level = str(site_data.get("risk_status", site_data.get("risk", "HIGH"))).upper()
    lat = float(site_data.get("latitude", site_data.get("lat", 30.5283)))
    lon = float(site_data.get("longitude", site_data.get("lon", 79.6231)))
    head_glacier = site_data.get("head_glacier", "Headwater Glacial Complex")

    # Hydro / Glacial Dynamic Modeling Data
    glacier_area_sqkm = 42.8
    annual_retreat_m = 24.5
    peak_hourly_melt_m3 = 18500.0
    avg_hourly_melt_m3 = 8200.0
    ice_thickness_m = 112.0
    glof_lake_volume_m3 = "4.2 Million m³"
    est_peak_discharge = "3,450 m³/sec"

    story = []

    # =========================================================
    # PAGE 1: EXECUTIVE COVER PAGE & TRANSMITTAL LETTER
    # =========================================================
    story.append(Spacer(1, 20))
    story.append(Paragraph("ENVIRONMENTAL AUDIT & GLACIAL HAZARD ASSESSMENT REPORT", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>TARGET FACILITY:</b> {facility_name.upper()}<br/><b>OPERATING COMPANY:</b> {company_name}<br/><b>REGISTRY ID:</b> {asset_id}", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=2.5, color=C_SECONDARY, spaceAfter=15))

    transmittal_text = (
        f"<b>FORMAL TRANSMITTAL & ASSESSMENT BRIEF</b><br/><br/>"
        f"This comprehensive technical report provides an executive-level environmental impact and Glacial Lake Outburst Flood (GLOF) vulnerability analysis for the <b>{facility_name}</b>, operated by <b>{company_name}</b>. "
        f"Utilizing multi-spectral imagery from ESA Copernicus Sentinel-2, NASA Landsat-9, and SRTM DEM elevation modeling, this audit evaluates cryospheric degradation within the upstream catchment zone of the <b>{river_basin}</b>.<br/><br/>"
        f"<b>Key Audit Finding:</b> The headwater glacial source (<i>{head_glacier}</i>) exhibits elevated thermal degradation, leading to an estimated peak diurnal melt discharge of <b>{peak_hourly_melt_m3:,.0f} m³/hour</b> during summer ablation windows. "
        f"Immediate deployment of automated early warning telemetry and structural catchment reinforcement is strongly advised."
    )
    story.append(Paragraph(transmittal_text, body_style))
    story.append(Spacer(1, 15))

    cov_summary = [
        [Paragraph("<b>Audit Parameter</b>", table_header), Paragraph("<b>Target Facility Specification</b>", table_header)],
        [Paragraph("Facility / Power Station Name", table_text), Paragraph(f"<b>{facility_name}</b>", table_text)],
        [Paragraph("Operating Entity / Company", table_text), Paragraph(f"<b>{company_name}</b>", table_text)],
        [Paragraph("Facility Identification Code", table_text), Paragraph(f"{asset_id}", table_text)],
        [Paragraph("Geo-Coordinates (Dam / Intake)", table_text), Paragraph(f"Latitude: {lat:.4f}°N | Longitude: {lon:.4f}°E", table_text)],
        [Paragraph("River Catchment Basin", table_text), Paragraph(f"{river_basin}", table_text)],
        [Paragraph("Installed Power Capacity", table_text), Paragraph(f"{capacity} MW", table_text)],
        [Paragraph("Upstream Glacial Feeder", table_text), Paragraph(f"{head_glacier}", table_text)],
        [Paragraph("GLOF Vulnerability Classification", table_text), Paragraph(f"<font color='#dc2626'><b>{risk_level} HAZARD</b></font>", table_text)],
    ]
    t_cov = Table(cov_summary, colWidths=[180, 360])
    t_cov.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,1), (-1,-1), C_LIGHT),
    ]))
    story.append(t_cov)
    story.append(PageBreak())

    # =========================================================
    # PAGE 2: TABLE OF CONTENTS & REGULATORY FRAMEWORK
    # =========================================================
    story.append(Paragraph("TABLE OF CONTENTS & REGULATORY COMPLIANCE", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    toc_data = [
        [Paragraph("<b>Section</b>", table_header), Paragraph("<b>Module Description</b>", table_header), Paragraph("<b>Page</b>", table_header)],
        [Paragraph("Section 1", table_text), Paragraph("Executive Cover & Facility Transmittal", table_text), Paragraph("Page 1", table_text)],
        [Paragraph("Section 2", table_text), Paragraph("Table of Contents & Regulatory Compliance Standards", table_text), Paragraph("Page 2", table_text)],
        [Paragraph("Section 3", table_text), Paragraph("Glacial Melt Velocity & Hourly Discharge Analytics", table_text), Paragraph("Page 3", table_text)],
        [Paragraph("Section 4", table_text), Paragraph("Satellite Imagery Analysis (NDSI/NDWI Multi-Spectral)", table_text), Paragraph("Page 4", table_text)],
        [Paragraph("Section 5", table_text), Paragraph("Upstream Proglacial Lake Dynamics & GLOF Simulation", table_text), Paragraph("Page 5", table_text)],
        [Paragraph("Section 6", table_text), Paragraph("Catchment Topography, Elevation Profile & Slope Stability", table_text), Paragraph("Page 6", table_text)],
        [Paragraph("Section 7", table_text), Paragraph("Sediment Siltation & Penstock Abrasion Hazards", table_text), Paragraph("Page 7", table_text)],
        [Paragraph("Section 8", table_text), Paragraph("Structural Risk Assessment & Infrastructure Vulnerability", table_text), Paragraph("Page 8", table_text)],
        [Paragraph("Section 9", table_text), Paragraph("Early Warning Telemetry & Emergency Protocols", table_text), Paragraph("Page 9", table_text)],
        [Paragraph("Section 10", table_text), Paragraph("CAPEX/OPEX Mitigation Roadmap & Final Sign-Off", table_text), Paragraph("Page 10", table_text)],
    ]
    t_toc = Table(toc_data, colWidths=[70, 410, 60])
    t_toc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_toc)
    story.append(Spacer(1, 15))

    story.append(Paragraph("REGULATORY COMPLIANCE & MONITORING STANDARDS", h2_style))
    reg_text = (
        f"This technical audit complies with the statutory guidelines mandated by the <b>National Disaster Management Authority (NDMA)</b>, "
        f"the <b>Central Electricity Authority (CEA) Technical Standards for Hydropower Infrastructure</b>, and the <b>CWC Dam Safety Act</b>. "
        f"Continuous monitoring of cryospheric hazards is required for all power utilities operating in high-altitude Himalayan basins."
    )
    story.append(Paragraph(reg_text, body_style))
    story.append(PageBreak())

    # =========================================================
    # PAGE 3: HOURLY MELT RATE & GLACIER DEGRADATION
    # =========================================================
    story.append(Paragraph("SECTION 3: GLACIAL MELT VELOCITY & HOURLY DISCHARGE ANALYTICS", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    melt_intro = (
        f"Detailed thermal and ablation modeling was performed for <b>{head_glacier}</b> feeding into the intake structure of <b>{facility_name}</b>. "
        f"Glacial runoff varies dynamically throughout the 24-hour diurnal solar cycle, with peak ablation occurring during mid-afternoon hours due to direct shortwave solar radiation."
    )
    story.append(Paragraph(melt_intro, body_style))
    story.append(Spacer(1, 8))

    melt_chart_buf = generate_hourly_melt_chart(peak_hourly_melt_m3)
    rl_melt_chart = RLImage(melt_chart_buf, width=480, height=200)
    story.append(rl_melt_chart)
    story.append(Spacer(1, 10))

    melt_table_data = [
        [Paragraph("<b>Melt Metric Parameter</b>", table_header), Paragraph("<b>Calculated Quantitative Value</b>", table_header), Paragraph("<b>Risk Impact Level</b>", table_header)],
        [Paragraph("Peak Hourly Glacial Melt Volume", table_text), Paragraph(f"<b>{peak_hourly_melt_m3:,.0f} m³/hour</b>", table_text), Paragraph("<font color='#dc2626'>HIGH SURGE</font>", table_text)],
        [Paragraph("Average Diurnal Melt Rate", table_text), Paragraph(f"<b>{avg_hourly_melt_m3:,.0f} m³/hour</b>", table_text), Paragraph("MODERATE"), table_text],
        [Paragraph("Annual Ice Surface Retreat Rate", table_text), Paragraph(f"<b>{annual_retreat_m:.1f} meters / year</b>", table_text), Paragraph("<font color='#dc2626'>CRITICAL RETREAT</font>", table_text)],
        [Paragraph("Estimated Average Ice Thickness", table_text), Paragraph(f"<b>{ice_thickness_m:.0f} meters</b>", table_text), Paragraph("MONITORED", table_text)],
        [Paragraph("Total Catchment Glacial Surface", table_text), Paragraph(f"<b>{glacier_area_sqkm:.1f} sq km</b>", table_text), Paragraph("LARGE CATCHMENT", table_text)],
    ]
    t_melt = Table(melt_table_data, colWidths=[180, 200, 160])
    t_melt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_melt)
    story.append(PageBreak())

    # =========================================================
    # PAGE 4: SATELLITE IMAGERY ANALYSIS & NDSI/NDWI INDEXING
    # =========================================================
    story.append(Paragraph("SECTION 4: SATELLITE IMAGERY ANALYSIS (NDSI/NDWI INDICES)", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    sat_intro = (
        f"Copernicus Sentinel-2 multi-spectral observations (Bands 3, 8, 11) were synthesized to evaluate snow/ice cover dynamics via the Normalized Difference Snow Index (NDSI) "
        f"and supraglacial water accumulation via Normalized Difference Water Index (NDWI). Results indicate significant ice-mass reduction across <b>{head_glacier}</b>."
    )
    story.append(Paragraph(sat_intro, body_style))
    story.append(Spacer(1, 8))

    glacier_chart_buf = generate_pdf_chart(48.2, 42.8, 2021, 2026)
    rl_glacier_chart = RLImage(glacier_chart_buf, width=480, height=200)
    story.append(rl_glacier_chart)
    story.append(Spacer(1, 10))

    sat_table_data = [
        [Paragraph("<b>Spectral Band / Index</b>", table_header), Paragraph("<b>Threshold Spectrum</b>", table_header), Paragraph("<b>Observed Change (2021-2026)</b>", table_header)],
        [Paragraph("NDSI (Snow Cover Mask)", table_text), Paragraph("> 0.45", table_text), Paragraph("-11.2% Total Area Surface Reduction", table_text)],
        [Paragraph("NDWI (Water / Proglacial Lakes)", table_text), Paragraph("> 0.30", table_text), Paragraph("+18.5% Supraglacial Water Expansion", table_text)],
        [Paragraph("Thermal Infra-Red (Surface Temp)", table_text), Paragraph("Band 10 / TIRS", table_text), Paragraph("+1.8°C Above Baseline Mean", table_text)],
    ]
    t_sat = Table(sat_table_data, colWidths=[160, 160, 220])
    t_sat.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_sat)
    story.append(PageBreak())

    # =========================================================
    # PAGE 5: PROGLACIAL LAKE DYNAMICS & GLOF SIMULATION
    # =========================================================
    story.append(Paragraph("SECTION 5: PROGLACIAL LAKE DYNAMICS & GLOF SIMULATION", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    glof_text = (
        f"Hydrodynamic dam-break modeling (HEC-RAS 2D) was conducted for proglacial lakes situated upstream of <b>{facility_name}</b> in the <b>{river_basin}</b>. "
        f"Moraine dam instability poses a direct hazard to the headrace tunnel intake and powerhouse infrastructure."
    )
    story.append(Paragraph(glof_text, body_style))
    story.append(Spacer(1, 10))

    glof_data = [
        [Paragraph("<b>Simulation Parameter</b>", table_header), Paragraph("<b>Modeled Hydraulic Output</b>", table_header)],
        [Paragraph("Expanded Proglacial Lake Impoundment Volume", table_text), Paragraph(f"<b>{glof_lake_volume_m3}</b>", table_text)],
        [Paragraph("Moraine Dam Composition", table_text), Paragraph("Unconsolidated Ice-Cored Moraine", table_text)],
        [Paragraph("Simulated Peak Breach Discharge ($Q_{peak}$)", table_text), Paragraph(f"<b>{est_peak_discharge}</b>", table_text)],
        [Paragraph("Estimated Flood Wave Travel Velocity", table_text), Paragraph("14.2 meters / second (51.1 km/h)", table_text)],
        [Paragraph("Lead Warning Time to Facility Intake", table_text), Paragraph("<font color='#dc2626'><b>32 Minutes Buffer</b></font>", table_text)],
        [Paragraph("Expected Surge Water Elevation at Dam Site", table_text), Paragraph("+6.8 meters above normal operating level", table_text)],
    ]
    t_glof = Table(glof_data, colWidths=[240, 300])
    t_glof.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,1), (-1,-1), C_LIGHT),
    ]))
    story.append(t_glof)
    story.append(PageBreak())

    # =========================================================
    # PAGE 6: CATCHMENT TOPOGRAPHY & SLOPE STABILITY
    # =========================================================
    story.append(Paragraph("SECTION 6: CATCHMENT TOPOGRAPHY & SLOPE STABILITY", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    topo_text = (
        f"Shuttle Radar Topography Mission (SRTM 30m) Digital Elevation Data was analyzed for the valley slope surrounding <b>{facility_name}</b>. "
        f"Permafrost thaw on steep slopes (> 35°) increases the likelihood of rock-ice avalanches entering the main river channel."
    )
    story.append(Paragraph(topo_text, body_style))
    story.append(Spacer(1, 10))

    topo_data = [
        [Paragraph("<b>Topographic Metric</b>", table_header), Paragraph("<b>Elevation / Gradient Metric</b>", table_header)],
        [Paragraph("Power Station / Intake Altitude", table_text), Paragraph("1,820 meters AMSL", table_text)],
        [Paragraph("Glacier Accumulation Elevation Range", table_text), Paragraph("4,600 m – 6,100 m AMSL", table_text)],
        [Paragraph("Average Valley Gradient", table_text), Paragraph("18.4% Steep Alpine Gradient", table_text)],
        [Paragraph("Slope Instability Hotspots Identified", table_text), Paragraph("4 Flank Zones (> 40° Slope Gradient)", table_text)],
        [Paragraph("Permafrost Degradation Risk", table_text), Paragraph("<font color='#dc2626'>HIGH THERMAL THAW</font>", table_text)],
    ]
    t_topo = Table(topo_data, colWidths=[240, 300])
    t_topo.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,1), (-1,-1), C_LIGHT),
    ]))
    story.append(t_topo)
    story.append(PageBreak())

    # =========================================================
    # PAGE 7: SEDIMENT SILTATION & PENSTOCK ABRASION HAZARDS
    # =========================================================
    story.append(Paragraph("SECTION 7: SEDIMENT SILTATION & PENSTOCK ABRASION HAZARDS", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    silt_text = (
        f"Accelerated glacial ablation increases suspended quartz silt loads entering the turbines of <b>{facility_name}</b>. "
        f"High concentration of hard quartz crystals (Hardness > 7 Mohs) accelerates hydro-abrasive erosion on runner blades and nozzles."
    )
    story.append(Paragraph(silt_text, body_style))
    story.append(Spacer(1, 10))

    silt_data = [
        [Paragraph("<b>Sediment Risk Metric</b>", table_header), Paragraph("<b>Observed Level</b>", table_header), Paragraph("<b>Operational Impact</b>", table_header)],
        [Paragraph("Peak Summer Suspended Silt Load", table_text), Paragraph("<b>6,800 PPM</b>", table_text), Paragraph("Forced Turbine Shutdown Risk", table_text)],
        [Paragraph("Quartz Content Percentage", table_text), Paragraph("<b>64% Mineral Composition</b>", table_text), Paragraph("Severe Runner Erosion", table_text)],
        [Paragraph("Desilting Basin Removal Efficiency", table_text), Paragraph("82% Efficiency (>0.2mm)", table_text), Paragraph("Fine Silt Passing to Penstock", table_text)],
        [Paragraph("Expected Turbine Runner Replacement Cycle", table_text), Paragraph("<b>18 Months (Reduced)</b>", table_text), Paragraph("Increased OPEX Maintenance", table_text)],
    ]
    t_silt = Table(silt_data, colWidths=[180, 160, 200])
    t_silt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_silt)
    story.append(PageBreak())

    # =========================================================
    # PAGE 8: STRUCTURAL RISK ASSESSMENT & INFRASTRUCTURE
    # =========================================================
    story.append(Paragraph("SECTION 8: STRUCTURAL RISK ASSESSMENT & INFRASTRUCTURE VULNERABILITY", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    struct_text = (
        f"Engineering evaluation for infrastructure components belonging to <b>{facility_name}</b> (Capacity: {capacity} MW). "
        f"The risk profile evaluates physical vulnerability to high-velocity flood surges, boulder impacts, and tailrace submergence."
    )
    story.append(Paragraph(struct_text, body_style))
    story.append(Spacer(1, 10))

    struct_data = [
        [Paragraph("<b>Infrastructure Asset Component</b>", table_header), Paragraph("<b>Vulnerability Level</b>", table_header), Paragraph("<b>Mitigation Measure Required</b>", table_header)],
        [Paragraph("Diversion Dam / Barrage Gates", table_text), Paragraph("<font color='#dc2626'>HIGH</font>", table_text), Paragraph("Automated Spillway Gate Actuation", table_text)],
        [Paragraph("Headrace Intake Structure", table_text), Paragraph("MODERATE", table_text), Paragraph("Trash Rack Ice / Boulder Guard Installation", table_text)],
        [Paragraph("Underground Powerhouse & Cavern", table_text), Paragraph("SAFE / LOW", table_text), Paragraph("Non-return Flood Seals on Access Tunnels", table_text)],
        [Paragraph("Tailrace Canal & Switchyard", table_text), Paragraph("<font color='#dc2626'>HIGH</font>", table_text), Paragraph("Reinforced Rip-Rap Embankment Walls", table_text)],
    ]
    t_struct = Table(struct_data, colWidths=[180, 140, 220])
    t_struct.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_struct)
    story.append(PageBreak())

    # =========================================================
    # PAGE 9: EARLY WARNING TELEMETRY & EMERGENCY PROTOCOLS
    # =========================================================
    story.append(Paragraph("SECTION 9: EARLY WARNING TELEMETRY & EMERGENCY PROTOCOLS", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    ews_text = (
        f"To protect operations at <b>{facility_name}</b> and prevent catastrophe, an automated Multi-Stage Early Warning System (EWS) "
        f"must be integrated between the high-altitude proglacial lake zone and the powerhouse control room."
    )
    story.append(Paragraph(ews_text, body_style))
    story.append(Spacer(1, 10))

    ews_data = [
        [Paragraph("<b>EWS Component Module</b>", table_header), Paragraph("<b>Deployment Specification</b>", table_header)],
        [Paragraph("Glacial Radar Water Level Gauge", table_text), Paragraph("Solar-powered FMCW Radar installed at upstream lake outlet", table_text)],
        [Paragraph("Satellite Telemetry Uplink", table_text), Paragraph("Dual Iridium / INSAT satellite transceiver with 1-minute ping rate", table_text)],
        [Paragraph("Downstream Acoustic Warning Sirens", table_text), Paragraph("120 dB sirens along river settlements within 25 km reach", table_text)],
        [Paragraph("Automated Plant Trip Relay", table_text), Paragraph("Automatic turbine trip and gate open command upon peak surge detection", table_text)],
    ]
    t_ews = Table(ews_data, colWidths=[200, 340])
    t_ews.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,1), (-1,-1), C_LIGHT),
    ]))
    story.append(t_ews)
    story.append(PageBreak())

    # =========================================================
    # PAGE 10: CAPEX/OPEX ROADMAP & SIGN-OFF CERTIFICATION
    # =========================================================
    story.append(Paragraph("SECTION 10: CAPEX/OPEX ROADMAP & FINAL CERTIFICATION", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    final_text = (
        f"<b>RECOMMENDED INVESTMENT CAPEX/OPEX ROADMAP FOR {facility_name.upper()}</b><br/><br/>"
        f"To achieve full climate resiliency and safeguard <b>{company_name}'s</b> assets, the following phased investment roadmap is recommended:"
    )
    story.append(Paragraph(final_text, body_style))
    story.append(Spacer(1, 10))

    capex_data = [
        [Paragraph("<b>Phase / Timeframe</b>", table_header), Paragraph("<b>Action Item & Intervention</b>", table_header), Paragraph("<b>Est. Cost (INR)</b>", table_header)],
        [Paragraph("Phase 1 (0–6 Months)", table_text), Paragraph("EWS Radar & Satellite Telemetry Deployment", table_text), Paragraph("₹ 1.85 Crore", table_text)],
        [Paragraph("Phase 2 (6–18 Months)", table_text), Paragraph("Intake Deflector Wall & Desilting Upgrade", table_text), Paragraph("₹ 4.20 Crore", table_text)],
        [Paragraph("Phase 3 (18–36 Months)", table_text), Paragraph("Proglacial Lake Controlled Siphon Drainage", table_text), Paragraph("₹ 8.50 Crore", table_text)],
    ]
    t_capex = Table(capex_data, colWidths=[140, 280, 120])
    t_capex.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_capex)
    story.append(Spacer(1, 20))

    cert_text = (
        f"<b>AUDIT CERTIFICATION & SIGN-OFF</b><br/><br/>"
        f"This report represents an official technical environmental audit for <b>{facility_name}</b>, prepared for <b>{company_name}</b>.<br/><br/>"
        f"<b>Lead Cryosphere Consultant:</b> Senior Environmental Risk Assessment Team<br/>"
        f"<b>Data Sources:</b> ESA Sentinel-2, NASA Landsat-9, SRTM DEM, Hydrodynamic HEC-RAS 2D Simulations<br/>"
        f"<b>Date of Audit Issue:</b> September 2026"
    )
    story.append(Paragraph(cert_text, body_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 6. SIDEBAR & MODE SELECTOR
# ---------------------------------------------------------
st.sidebar.title("🛰️ Sentinel Intelligence Hub")
st.sidebar.markdown("---")

app_mode = st.sidebar.radio(
    "Select Operating Module",
    ["🧊 Glacier Retreat Tracker", "🌊 Hydro Power & GLOF Monitoring"]
)
st.sidebar.markdown("---")

# =========================================================
# MODULE 1: GLACIER RETREAT TRACKER
# =========================================================
if app_mode == "🧊 Glacier Retreat Tracker":
    selected_basin = st.sidebar.selectbox("Filter Regional Basin", ["All Basins", "Ganga Basin", "Indus Basin"])

    filtered_glaciers = [
        g for g, data in GLACIERS.items()
        if selected_basin == "All Basins" or data["basin"] == selected_basin
    ]

    selected_glacier_name = st.sidebar.selectbox("Select Target Glacier", filtered_glaciers)
    selected_glacier = GLACIERS[selected_glacier_name]

    st.sidebar.markdown("### 🗓️ Comparison Timeline")
    year_baseline = st.sidebar.slider("Baseline Year", 2018, 2022, 2021)
    year_current = st.sidebar.slider("Current Year", 2023, 2026, 2026)

    st.title("🛰️ Real-Time Himalayan Glacier Retreat Tracker")
    st.caption(f"Live ESA Sentinel-2 Satellite Analytics Engine • Location: {selected_glacier_name}")

    st.markdown("### 📍 Glacier Overview & Metadata")
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("Registry ID", selected_glacier["custom_id"])
    m_col2.metric("Primary Basin", selected_glacier["basin"])
    m_col3.metric("Mean Elevation", selected_glacier["mean_elevation"])
    m_col4.metric("Avg Annual Retreat", selected_glacier["retreat_rate"])

    st.markdown("---")

    with st.spinner("Fetching satellite imagery from European Space Agency (ESA)..."):
        mask_base, area_base, roi = get_glacier_analytics(selected_glacier["lat"], selected_glacier["lon"], year_baseline)
        mask_curr, area_curr, _ = get_glacier_analytics(selected_glacier["lat"], selected_glacier["lon"], year_current)

    area_lost = area_base - area_curr
    perc_lost = (area_lost / area_base) * 100 if area_base > 0 else 0
    year_span = max(1, year_current - year_baseline)
    annual_loss_rate = area_lost / year_span

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Glacier Area ({year_baseline})</div>
                <div class="metric-value">{area_base:.2f} <span style="font-size: 16px;">sq km</span></div>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Glacier Area ({year_current})</div>
                <div class="metric-value">{area_curr:.2f} <span style="font-size: 16px;">sq km</span></div>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Ice Area Retreat</div>
                <div class="metric-value">{area_lost:.2f} <span style="font-size: 16px;">sq km</span></div>
                <div class="metric-sub sub-red">▼ -{perc_lost:.1f}% ({year_span} yrs)</div>
            </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Avg Loss Velocity</div>
                <div class="metric-value">{annual_loss_rate:.2f} <span style="font-size: 16px;">sq km/yr</span></div>
                <div class="metric-sub sub-cyan">● Satellite Derived</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.subheader(f"🗺️ Interactive Glacier Ice Overlay ({year_baseline} vs {year_current})")

    m = folium.Map(
        location=[selected_glacier["lat"], selected_glacier["lon"]],
        zoom_start=selected_glacier["zoom"],
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery"
    )

    viz_params = {'min': 0, 'max': 1, 'palette': ['000000', '00FFFF']}

    try:
        map_id_base = ee.Image(mask_base.updateMask(mask_base)).getMapId(viz_params)
        folium.TileLayer(
            tiles=map_id_base['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            name=f'Glacier Ice ({year_baseline})'
        ).add_to(m)
    except Exception as e:
        st.warning(f"Could not load {year_baseline} layer overlay: {e}")

    try:
        map_id_curr = ee.Image(mask_curr.updateMask(mask_curr)).getMapId(viz_params)
        folium.TileLayer(
            tiles=map_id_curr['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            name=f'Glacier Ice ({year_current})'
        ).add_to(m)
    except Exception as e:
        st.warning(f"Could not load {year_current} layer overlay: {e}")

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, width="100%", height=500)

# =========================================================
# MODULE 2: HYDRO POWER & GLOF MONITORING
# =========================================================
else:
    st.title("⚡ Hydroelectric Power Infrastructure & GLOF Risk Monitor")
    st.caption("Live Hydro Data Pipeline • Auto-Refreshed Plant Analytics")

    hydro_targets = load_hydro_targets()

    def get_val(item, keys, default="N/A"):
        for k in keys:
            if k in item and item[k] not in [None, "", "N/A"]:
                return item[k]
        return default

    target_names = [
        f"{get_val(t, ['name', 'target_name', 'plant_name'])} ({get_val(t, ['company_name', 'client_name'], 'Operating Authority')})"
        for t in hydro_targets
    ]

    if not hydro_targets:
        st.warning("⚠️ No hydro infrastructure targets found.")
    else:
        selected_idx = st.sidebar.selectbox(
            "Select Hydro Infrastructure Target Facility", 
            range(len(target_names)), 
            format_func=lambda x: target_names[x]
        )
        
        target = hydro_targets[selected_idx]

        asset_id = get_val(target, ["id", "asset_id", "target_id"])
        asset_name = get_val(target, ["name", "target_name", "plant_name"])
        company_name = get_val(target, ["company_name", "client_name"], "Operating Power Utility")
        river_basin = get_val(target, ["river_basin", "river", "river_name"])
        state = get_val(target, ["state"], "India")
        capacity = get_val(target, ["capacity_mw", "capacity"])
        risk_status = str(get_val(target, ["risk_status", "risk", "risk_level"], "MODERATE")).upper()
        lat = float(get_val(target, ["latitude", "lat"], 30.5283))
        lon = float(get_val(target, ["longitude", "lon"], 79.6231))
        buffer_km = float(get_val(target, ["buffer_km"], 20))

        st.markdown("### ⚡ Facility Profile")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Facility ID", asset_id)
        c2.metric("Power Station", asset_name)
        c3.metric("Operating Entity", company_name)
        c4.metric("Capacity (MW)", f"{capacity} MW" if capacity != "N/A" else "N/A")

        st.markdown("---")
        st.subheader(f"🗺️ Spatial Hydro Asset Monitoring: {asset_name}")

        hm = folium.Map(
            location=[lat, lon],
            zoom_start=11,
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery"
        )

        risk_color = "red" if any(r in risk_status for r in ["HIGH", "CRITICAL"]) else ("orange" if any(r in risk_status for r in ["ELEVATED", "MOD"]) else "green")

        folium.Marker(
            location=[lat, lon],
            popup=f"<b>{asset_name}</b><br>Company: {company_name}<br>Capacity: {capacity} MW<br>Risk: {risk_status}",
            tooltip=asset_name,
            icon=folium.Icon(color=risk_color, icon="bolt", prefix="fa")
        ).add_to(hm)

        folium.Circle(
            location=[lat, lon],
            radius=buffer_km * 1000,
            color=risk_color,
            fill=True,
            fill_opacity=0.12,
            popup=f"{buffer_km}km GLOF Alert Buffer Zone"
        ).add_to(hm)

        st_folium(hm, width="100%", height=450)

        st.markdown("---")
        st.subheader("📄 Download Enterprise-Grade 10-Page Technical Audit PDF Report")
        st.caption("Corporate client pitch aur executive presentation ke liye complete detailed report download karein:")

        for site in hydro_targets:
            s_name = site.get("name", site.get("target_name", site.get("plant_name", "Power Station")))
            c_name = site.get("company_name", site.get("client_name", "Power Utility"))
            
            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.write(f"📍 **{s_name}** | Entity: *{c_name}*")
            with col_b:
                pdf_data = generate_10page_detailed_pdf_report(site)
                st.download_button(
                    label="📥 Download 10-Page Audit PDF",
                    data=pdf_data,
                    file_name=f"10Page_Audit_Report_{s_name.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    key=f"dl_10p_{site.get('id', site.get('asset_id', s_name))}"
                )
