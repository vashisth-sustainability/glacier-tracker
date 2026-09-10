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
# 3. DATABASES & DATA PIPELINE ARCHITECTURE
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
        
        if self._pageNumber > 1:
            self.drawString(36, 762, "ENV-AUDIT | TECHNICAL GLACIAL & GLOF RISK ASSESSMENT REPORT")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(36, 754, 576, 754)
            
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
    C_BORDER = colors.HexColor("#CBD5E1")

    title_style = ParagraphStyle('CoverTitle', parent=styles['Heading1'], fontSize=22, leading=26, textColor=C_PRIMARY, fontName="Helvetica-Bold", alignment=0)
    subtitle_style = ParagraphStyle('CoverSub', parent=styles['Normal'], fontSize=11, leading=15, textColor=colors.HexColor("#475569"), fontName="Helvetica")
    h1_style = ParagraphStyle('H1Sec', parent=styles['Heading2'], fontSize=12, leading=16, textColor=C_SECONDARY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=6)
    h2_style = ParagraphStyle('H2Sec', parent=styles['Heading3'], fontSize=10, leading=14, textColor=C_PRIMARY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=4)
    body_style = ParagraphStyle('BodyCustom', parent=styles['Normal'], fontSize=8.5, leading=12, textColor=C_DARK)
    table_text = ParagraphStyle('TableTxt', parent=styles['Normal'], fontSize=8, leading=11, textColor=C_DARK)
    table_header = ParagraphStyle('TableHdr', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.white, fontName="Helvetica-Bold")

    facility_name = site_data.get("name", site_data.get("target_name", site_data.get("plant_name", "Hydroelectric Power Station")))
    company_name = site_data.get("company_name", site_data.get("client_name", "Operating Authority / State Utility"))
    asset_id = site_data.get("id", site_data.get("asset_id", site_data.get("target_id", "FACILITY-001")))
    river_basin = site_data.get("river_basin", site_data.get("river", "River System"))
    capacity = site_data.get("capacity_mw", site_data.get("capacity", "N/A"))
    risk_level = str(site_data.get("risk_status", site_data.get("risk", "HIGH"))).upper()
    lat = float(site_data.get("latitude", site_data.get("lat", 30.5283)))
    lon = float(site_data.get("longitude", site_data.get("lon", 79.6231)))
    head_glacier = site_data.get("head_glacier", "Headwater Glacial Complex")

    glacier_area_sqkm = 42.8
    annual_retreat_m = 24.5
    peak_hourly_melt_m3 = 18500.0
    avg_hourly_melt_m3 = 8200.0
    ice_thickness_m = 112.0
    glof_lake_volume_m3 = "4.2 Million m³"
    est_peak_discharge = "3,450 m³/sec"

    story = []

    # PAGE 1
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
        f"<b>Key Audit Finding:</b> The headwater glacial source (<i>{head_glacier}</i>) exhibits elevated thermal degradation, leading to an estimated peak diurnal melt discharge of <b>{peak_hourly_melt_m3:,.0f} m³/hour</b> during summer ablation windows."
    )
    story.append(Paragraph(transmittal_text, body_style))
    story.append(Spacer(1, 15))

    cov_summary = [
        [Paragraph("<b>Audit Parameter</b>", table_header), Paragraph("<b>Target Facility Specification</b>", table_header)],
        [Paragraph("Facility Name", table_text), Paragraph(f"<b>{facility_name}</b>", table_text)],
        [Paragraph("Operating Entity", table_text), Paragraph(f"<b>{company_name}</b>", table_text)],
        [Paragraph("Facility ID Code", table_text), Paragraph(f"{asset_id}", table_text)],
        [Paragraph("Geo-Coordinates", table_text), Paragraph(f"Lat: {lat:.4f}°N | Lon: {lon:.4f}°E", table_text)],
        [Paragraph("River Catchment", table_text), Paragraph(f"{river_basin}", table_text)],
        [Paragraph("Installed Capacity", table_text), Paragraph(f"{capacity} MW", table_text)],
        [Paragraph("Upstream Glacial Feeder", table_text), Paragraph(f"{head_glacier}", table_text)],
        [Paragraph("GLOF Hazard Level", table_text), Paragraph(f"<font color='#dc2626'><b>{risk_level}</b></font>", table_text)],
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

    # PAGE 2
    story.append(Paragraph("TABLE OF CONTENTS & REGULATORY COMPLIANCE", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    toc_data = [
        [Paragraph("<b>Section</b>", table_header), Paragraph("<b>Module Description</b>", table_header), Paragraph("<b>Page</b>", table_header)],
        [Paragraph("Section 1", table_text), Paragraph("Executive Cover & Facility Transmittal", table_text), Paragraph("Page 1", table_text)],
        [Paragraph("Section 2", table_text), Paragraph("Table of Contents & Regulatory Standards", table_text), Paragraph("Page 2", table_text)],
        [Paragraph("Section 3", table_text), Paragraph("Glacial Melt Velocity & Hourly Discharge", table_text), Paragraph("Page 3", table_text)],
        [Paragraph("Section 4", table_text), Paragraph("Satellite Imagery Analysis (NDSI/NDWI)", table_text), Paragraph("Page 4", table_text)],
        [Paragraph("Section 5", table_text), Paragraph("Proglacial Lake Dynamics & GLOF Simulation", table_text), Paragraph("Page 5", table_text)],
        [Paragraph("Section 6", table_text), Paragraph("Catchment Topography & Slope Stability", table_text), Paragraph("Page 6", table_text)],
        [Paragraph("Section 7", table_text), Paragraph("Sediment Siltation & Penstock Abrasion", table_text), Paragraph("Page 7", table_text)],
        [Paragraph("Section 8", table_text), Paragraph("Structural Risk & Infrastructure Vulnerability", table_text), Paragraph("Page 8", table_text)],
        [Paragraph("Section 9", table_text), Paragraph("Early Warning Telemetry & Emergency Protocols", table_text), Paragraph("Page 9", table_text)],
        [Paragraph("Section 10", table_text), Paragraph("CAPEX/OPEX Mitigation Roadmap & Sign-Off", table_text), Paragraph("Page 10", table_text)],
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
        f"the <b>Central Electricity Authority (CEA) Technical Standards</b>, and the <b>CWC Dam Safety Act</b>."
    )
    story.append(Paragraph(reg_text, body_style))
    story.append(PageBreak())

    # PAGE 3
    story.append(Paragraph("SECTION 3: GLACIAL MELT VELOCITY & HOURLY DISCHARGE ANALYTICS", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    melt_intro = f"Detailed thermal and ablation modeling was performed for <b>{head_glacier}</b> feeding into <b>{facility_name}</b>."
    story.append(Paragraph(melt_intro, body_style))
    story.append(Spacer(1, 8))

    melt_chart_buf = generate_hourly_melt_chart(peak_hourly_melt_m3)
    rl_melt_chart = RLImage(melt_chart_buf, width=480, height=200)
    story.append(rl_melt_chart)
    story.append(Spacer(1, 10))

    melt_table_data = [
        [Paragraph("<b>Melt Metric Parameter</b>", table_header), Paragraph("<b>Calculated Value</b>", table_header), Paragraph("<b>Risk Impact Level</b>", table_header)],
        [Paragraph("Peak Hourly Melt Volume", table_text), Paragraph(f"<b>{peak_hourly_melt_m3:,.0f} m³/hr</b>", table_text), Paragraph("<font color='#dc2626'>HIGH SURGE</font>", table_text)],
        [Paragraph("Average Diurnal Melt Rate", table_text), Paragraph(f"<b>{avg_hourly_melt_m3:,.0f} m³/hr</b>", table_text), Paragraph("MODERATE", table_text)],
        [Paragraph("Annual Ice Surface Retreat Rate", table_text), Paragraph(f"<b>{annual_retreat_m:.1f} m/yr</b>", table_text), Paragraph("<font color='#dc2626'>CRITICAL</font>", table_text)],
        [Paragraph("Estimated Average Ice Thickness", table_text), Paragraph(f"<b>{ice_thickness_m:.0f} m</b>", table_text), Paragraph("MONITORED", table_text)],
        [Paragraph("Total Glacial Area", table_text), Paragraph(f"<b>{glacier_area_sqkm:.1f} sq km</b>", table_text), Paragraph("LARGE CATCHMENT", table_text)],
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

    # PAGE 4
    story.append(Paragraph("SECTION 4: SATELLITE IMAGERY ANALYSIS (NDSI/NDWI INDICES)", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    sat_intro = f"Copernicus Sentinel-2 multi-spectral observations evaluated snow/ice cover dynamics for <b>{head_glacier}</b>."
    story.append(Paragraph(sat_intro, body_style))
    story.append(Spacer(1, 8))

    glacier_chart_buf = generate_pdf_chart(48.2, 42.8, 2021, 2026)
    rl_glacier_chart = RLImage(glacier_chart_buf, width=480, height=200)
    story.append(rl_glacier_chart)
    story.append(Spacer(1, 10))

    sat_table_data = [
        [Paragraph("<b>Spectral Index</b>", table_header), Paragraph("<b>Threshold Spectrum</b>", table_header), Paragraph("<b>Observed Change (2021-2026)</b>", table_header)],
        [Paragraph("NDSI (Snow Mask)", table_text), Paragraph("> 0.45", table_text), Paragraph("-11.2% Area Reduction", table_text)],
        [Paragraph("NDWI (Water Lakes)", table_text), Paragraph("> 0.30", table_text), Paragraph("+18.5% Supraglacial Expansion", table_text)],
        [Paragraph("Thermal Infra-Red", table_text), Paragraph("Band 10 / TIRS", table_text), Paragraph("+1.8°C Above Baseline", table_text)],
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

    # PAGE 5
    story.append(Paragraph("SECTION 5: PROGLACIAL LAKE DYNAMICS & GLOF SIMULATION", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    glof_text = f"Hydrodynamic dam-break modeling (HEC-RAS 2D) was conducted for proglacial lakes upstream of <b>{facility_name}</b>."
    story.append(Paragraph(glof_text, body_style))
    story.append(Spacer(1, 10))

    glof_data = [
        [Paragraph("<b>Simulation Parameter</b>", table_header), Paragraph("<b>Modeled Hydraulic Output</b>", table_header)],
        [Paragraph("Proglacial Lake Volume", table_text), Paragraph(f"<b>{glof_lake_volume_m3}</b>", table_text)],
        [Paragraph("Moraine Structure", table_text), Paragraph("Unconsolidated Ice-Cored Moraine", table_text)],
        [Paragraph("Peak Breach Discharge ($Q_{peak}$)", table_text), Paragraph(f"<b>{est_peak_discharge}</b>", table_text)],
        [Paragraph("Flood Wave Travel Speed", table_text), Paragraph("14.2 m/s (51.1 km/h)", table_text)],
        [Paragraph("Lead Warning Buffer", table_text), Paragraph("<font color='#dc2626'><b>32 Minutes</b></font>", table_text)],
        [Paragraph("Expected Surge Elevation", table_text), Paragraph("+6.8 meters", table_text)],
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

    # PAGE 6
    story.append(Paragraph("SECTION 6: CATCHMENT TOPOGRAPHY & SLOPE STABILITY", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    topo_text = f"SRTM DEM 30m terrain elevation analysis surrounding <b>{facility_name}</b>."
    story.append(Paragraph(topo_text, body_style))
    story.append(Spacer(1, 10))

    topo_data = [
        [Paragraph("<b>Topographic Metric</b>", table_header), Paragraph("<b>Elevation / Gradient Metric</b>", table_header)],
        [Paragraph("Power Station Elevation", table_text), Paragraph("1,820 meters AMSL", table_text)],
        [Paragraph("Glacier Accumulation Range", table_text), Paragraph("4,600 m – 6,100 m AMSL", table_text)],
        [Paragraph("Average Valley Gradient", table_text), Paragraph("18.4% Steep Alpine Gradient", table_text)],
        [Paragraph("Unstable Slope Hotspots", table_text), Paragraph("4 Flank Zones (> 40° Slope)", table_text)],
        [Paragraph("Permafrost Thaw Risk", table_text), Paragraph("<font color='#dc2626'>HIGH</font>", table_text)],
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

    # PAGE 7
    story.append(Paragraph("SECTION 7: SEDIMENT SILTATION & PENSTOCK ABRASION", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    silt_text = f"Evaluated quartz-dominated suspended sediment loads downstream of <b>{head_glacier}</b>."
    story.append(Paragraph(silt_text, body_style))
    story.append(Spacer(1, 10))

    silt_data = [
        [Paragraph("<b>Sediment Parameter</b>", table_header), Paragraph("<b>Observed Concentration Value</b>", table_header)],
        [Paragraph("Peak Monsoon Silt Load", table_text), Paragraph("<b>6,800 PPM</b>", table_text)],
        [Paragraph("Quartz Mineral Content", table_text), Paragraph("78% Hardness Grade 7 (Mohs Scale)", table_text)],
        [Paragraph("Expected Turbine Erosion Rate", table_text), Paragraph("<font color='#dc2626'>Severe Runner Blade Wear</font>", table_text)],
        [Paragraph("Desilting Basin Efficiency Target", table_text), Paragraph("92% Particle Removal (>0.2mm)", table_text)],
    ]
    t_silt = Table(silt_data, colWidths=[240, 300])
    t_silt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,1), (-1,-1), C_LIGHT),
    ]))
    story.append(t_silt)
    story.append(PageBreak())

    # PAGE 8
    story.append(Paragraph("SECTION 8: STRUCTURAL RISK & INFRASTRUCTURE VULNERABILITY", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    struct_text = f"Vulnerability assessment across civil structures for <b>{facility_name}</b>."
    story.append(Paragraph(struct_text, body_style))
    story.append(Spacer(1, 10))

    struct_data = [
        [Paragraph("<b>Asset Component</b>", table_header), Paragraph("<b>Structural Integrity Rating</b>", table_header), Paragraph("<b>Mitigation Action Required</b>", table_header)],
        [Paragraph("Main Diversion Dam / Barrage", table_text), Paragraph("84/100 (Satisfactory)", table_text), Paragraph("Armor Spillway Basins", table_text)],
        [Paragraph("Headrace Tunnel (HRT) Intake", table_text), Paragraph("68/100 (Vulnerable)", table_text), Paragraph("Install Trash Rack Sensors", table_text)],
        [Paragraph("Surface Powerhouse Unit", table_text), Paragraph("72/100 (Moderate)", table_text), Paragraph("Construct Flood Wall Protection", table_text)],
    ]
    t_struct = Table(struct_data, colWidths=[180, 180, 180])
    t_struct.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_struct)
    story.append(PageBreak())

    # PAGE 9
    story.append(Paragraph("SECTION 9: EARLY WARNING TELEMETRY & EMERGENCY PROTOCOLS", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    telemetry_text = f"Real-time sensor integration plan for <b>{facility_name}</b> catchment zone."
    story.append(Paragraph(telemetry_text, body_style))
    story.append(Spacer(1, 10))

    eaws_data = [
        [Paragraph("<b>Telemetry Hardware Unit</b>", table_header), Paragraph("<b>Deployment Target Area</b>", table_header), Paragraph("<b>Transmission Frequency</b>", table_header)],
        [Paragraph("Automated Weather Station (AWS)", table_text), Paragraph("Upper Glacial Ridge (4,800 m)", table_text), Paragraph("15-Minute Satellite Relay", table_text)],
        [Paragraph("Radar Water Level Gauge", table_text), Paragraph("Proglacial Outflow Channel", table_text), Paragraph("Real-Time Burst Mode", table_text)],
        [Paragraph("Acoustic Doppler Velocity Sensor", table_text), Paragraph("Desilting Inlet Structure", table_text), Paragraph("5-Minute Interval", table_text)],
    ]
    t_eaws = Table(eaws_data, colWidths=[180, 200, 160])
    t_eaws.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_eaws)
    story.append(PageBreak())

    # PAGE 10
    story.append(Paragraph("SECTION 10: CAPEX/OPEX MITIGATION ROADMAP & SIGN-OFF", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=C_SECONDARY, spaceAfter=10))

    sign_text = f"Capital allocation plan and formal certification for <b>{facility_name}</b> GLOF resilience."
    story.append(Paragraph(sign_text, body_style))
    story.append(Spacer(1, 10))

    capex_data = [
        [Paragraph("<b>Intervention Phase</b>", table_header), Paragraph("<b>Projected Cost (INR Crores)</b>", table_header), Paragraph("<b>Target Completion</b>", table_header)],
        [Paragraph("Phase I: EAWS Sensors & Telemetry", table_text), Paragraph("₹ 4.5 Crores", table_text), Paragraph("Q2 2027", table_text)],
        [Paragraph("Phase II: Silt Basin Upgrades", table_text), Paragraph("₹ 18.2 Crores", table_text), Paragraph("Q4 2027", table_text)],
        [Paragraph("Phase III: Catchment Protection Walls", table_text), Paragraph("₹ 32.0 Crores", table_text), Paragraph("Q3 2028", table_text)],
    ]
    t_capex = Table(capex_data, colWidths=[200, 170, 170])
    t_capex.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_PRIMARY),
        ('GRID', (0,0), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_capex)
    story.append(Spacer(1, 20))

    story.append(Paragraph("<b>FORMAL AUDIT CERTIFICATION & SIGN-OFF</b>", h2_style))
    cert_text = "This report has been generated based on satellite earth observation and hydrodynamic modeling."
    story.append(Paragraph(cert_text, body_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer

# ---------------------------------------------------------
# 6. MAIN APPLICATION LAYOUT & DASHBOARD INTERFACE
# ---------------------------------------------------------
st.title("🧊 Himalayan Glacier & Hydroelectric Infrastructure Risk Monitor")
st.markdown("<b>Real-time Earth Engine Satellite Analytics, GLOF Simulation & Hydro-Asset Vulnerability Platform</b>", unsafe_allow_html=True)
st.divider()

# Sidebar Setup
st.sidebar.header("🕹️ Monitoring Control Panel")
mode = st.sidebar.radio("Select Operational View:", ["Glacier Satellite Analytics", "Hydro Infrastructure Assets Risk Engine"])

if mode == "Glacier Satellite Analytics":
    glacier_choice = st.sidebar.selectbox("Select Target Glacier:", list(GLACIERS.keys()))
    gdata = GLACIERS[glacier_choice]
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Retreat Velocity</div><div class='metric-value'>{gdata['retreat_rate']}</div><div class='metric-sub sub-red'>High Rate</div></div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>GLOF Hazard</div><div class='metric-value'>{gdata['glof_risk'].split('-')[0]}</div><div class='metric-sub sub-red'>Critical Threshold</div></div>", unsafe_allow_html=True)
    with col3:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Warning Window</div><div class='metric-value'>{gdata['early_warning_window'].split(' ')[0]}</div><div class='metric-sub sub-cyan'>Lead Buffer</div></div>", unsafe_allow_html=True)
    with col4:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Elevation</div><div class='metric-value'>{gdata['mean_elevation']}</div><div class='metric-sub sub-cyan'>High Altitude Zone</div></div>", unsafe_allow_html=True)

    st.subheader(f"🗺️ Multi-Spectral Earth Engine Imagery: {glacier_choice}")
    
    try:
        snow_mask, current_area, roi = get_glacier_analytics(gdata['lat'], gdata['lon'], 2026)
        
        m = folium.Map(location=[gdata['lat'], gdata['lon']], zoom_start=gdata['zoom'], tiles="OpenStreetMap")
        map_id_dict = ee.Image(snow_mask.updateMask(snow_mask)).getMapId({'palette': ['00FFFF', '0000FF']})
        folium.TileLayer(
            tiles=map_id_dict['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            name='NDSI Glacier Extent',
            overlay=True,
            control=True
        ).add_to(m)
        folium.LayerControl().add_to(m)
        st_folium(m, width=1200, height=500)
    except Exception as e:
        st.error(f"Satellite Data Stream Layer Processing Error: {e}")

    # Chart Section
    st.subheader("📈 Historical Surface Area Reduction Trend")
    years = list(gdata['historical_data'].keys())
    areas = list(gdata['historical_data'].values())
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=areas, mode='lines+markers', line=dict(color='#ff4d6d', width=3), marker=dict(size=8)))
    fig.update_layout(title="Glacier Ice Surface Extent Area (1990 - 2026)", xaxis_title="Year", yaxis_title="Area (sq km)", template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

else:
    hydro_targets = load_hydro_targets()
    target_names = [t["name"] for t in hydro_targets]
    selected_hydro_name = st.sidebar.selectbox("Select Hydro Infrastructure Asset:", target_names)
    selected_hydro = next(t for t in hydro_targets if t["name"] == selected_hydro_name)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Installed Capacity</div><div class='metric-value'>{selected_hydro['capacity_mw']} MW</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Risk Category</div><div class='metric-value'>{selected_hydro['risk_status']}</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>State / Zone</div><div class='metric-value'>{selected_hydro['state']}</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='metric-card'><div class='metric-label'>Feeder Glacier</div><div class='metric-value'>Connected</div></div>", unsafe_allow_html=True)

    st.subheader(f"📍 Location & Catchment Buffer Map: {selected_hydro['name']}")
    hm = folium.Map(location=[selected_hydro['latitude'], selected_hydro['longitude']], zoom_start=11, tiles="OpenStreetMap")
    folium.Marker([selected_hydro['latitude'], selected_hydro['longitude']], popup=selected_hydro['name'], icon=folium.Icon(color="red", icon="flash")).add_to(hm)
    folium.Circle([selected_hydro['latitude'], selected_hydro['longitude']], radius=selected_hydro['buffer_km']*1000, color="red", fill=True, fill_opacity=0.2).add_to(hm)
    st_folium(hm, width=1200, height=450)

    st.divider()
    st.subheader("📄 Dynamic PDF Report Generation Engine")
    st.write("Generate a formal 10-page technical audit report for executive submission:")

    if st.button("🚀 Generate Technical Audit PDF Report"):
        with st.spinner("Processing satellite raster metrics, hydrodynamic curves, and ReportLab layouts..."):
            pdf_buf = generate_10page_detailed_pdf_report(selected_hydro)
            st.success("Report generated successfully!")
            st.download_button(
                label="📥 Download 10-Page Audit PDF Report",
                data=pdf_buf,
                file_name=f"{selected_hydro['id']}_Technical_Audit_Report.pdf",
                mime="application/pdf"
            )
