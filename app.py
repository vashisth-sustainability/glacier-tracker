import json
import io
import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import matplotlib.pyplot as plt

# ReportLab Imports for Professional PDF
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION & STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="Himalayan Glacier Satellite Monitor",
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
    .sub-green { color: #00E676 !important; }
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
# 2. PASSWORD PROTECTION SYSTEM (WITH ADMIN URL BYPASS)
# ---------------------------------------------------------
def check_password():
    query_params = st.query_params
    if query_params.get("key") == "swastik":
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.markdown("## 🔒 Access Restricted")
        st.caption("This dashboard is password protected. Enter authorized passcode to continue.")
        st.text_input("Enter Passcode", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.markdown("## 🔒 Access Restricted")
        st.caption("This dashboard is password protected. Enter authorized passcode to continue.")
        st.text_input("Enter Passcode", type="password", on_change=password_entered, key="password")
        st.error("❌ Incorrect Passcode")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ---------------------------------------------------------
# 3. EARTH ENGINE INITIALIZATION
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
# 4. GLACIER DATABASE (UPGRADED WITH WGMS METADATA)
# ---------------------------------------------------------
GLACIERS = {
    "Gangotri Glacier (Uttarakhand)": {
        "basin": "Ganga Basin",
        "wgi_id": "IN-5O131-00-012",
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
        "wgi_id": "IN-5Q212-00-001",
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
        "wgi_id": "IN-5Q210-00-008",
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
        "wgi_id": "IN-5O132-00-005",
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

# ---------------------------------------------------------
# 5. SIDEBAR CONTROLS (WGMS BASIN FILTERING)
# ---------------------------------------------------------
st.sidebar.title("🧊 Glacier Tracker AI")
st.sidebar.markdown("---")

selected_basin = st.sidebar.selectbox("Filter River Basin (WGMS Standard)", ["All Basins", "Ganga Basin", "Indus Basin", "Brahmaputra Basin"])

filtered_glaciers = [
    g for g, data in GLACIERS.items()
    if selected_basin == "All Basins" or data["basin"] == selected_basin
]

selected_glacier_name = st.sidebar.selectbox("Select Target Glacier", filtered_glaciers)
selected_glacier = GLACIERS[selected_glacier_name]

st.sidebar.markdown("### 🗓️ Comparison Timeline")
year_baseline = st.sidebar.slider("Baseline Year", 2018, 2022, 2021)
year_current = st.sidebar.slider("Current Year", 2023, 2026, 2026)

# ---------------------------------------------------------
# 6. CORE ANALYTICS ENGINE & GRAPH PLOTTER
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

# Dynamic Matplotlib Chart Engine for PDF Inclusion
def generate_pdf_chart(area_b, area_c, b_yr, c_yr):
    plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(6, 2.8), dpi=200)
    
    bars = ax.bar(
        [f'Baseline ({b_yr})', f'Current ({c_yr})'], 
        [area_b, area_c], 
        color=['#0284c7', '#dc2626'],
        width=0.45
    )
    
    ax.set_ylabel('Ice Surface Area (sq km)', fontsize=9, fontweight='bold', color='#1e293b')
    ax.set_title('Glacier Coverage Reduction Analysis', fontsize=10, fontweight='bold', color='#0f172a', pad=10)
    ax.tick_params(axis='both', which='major', labelsize=8.5)
    ax.set_ylim(0, max(area_b, area_c) * 1.25)
    
    for bar in bars:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width()/2.0, 
            yval + (max(area_b, area_c) * 0.03), 
            f'{yval:.2f} sq km', 
            ha='center', 
            va='bottom', 
            fontsize=8.5, 
            fontweight='bold',
            color='#0f172a'
        )

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    img_buf.seek(0)
    return img_buf

# ---------------------------------------------------------
# 7. ENHANCED AUTO-GENERATED PDF REPORT GENERATOR WITH GRAPH
# ---------------------------------------------------------
def generate_pdf_report(glacier_name, baseline_yr, current_yr, area_b, area_c, area_l, perc_l, loss_rate, info):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()

    COLOR_PRIMARY = colors.HexColor("#0f172a")
    COLOR_ACCENT = colors.HexColor("#0284c7")

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'],
        fontSize=15, textColor=COLOR_PRIMARY, spaceAfter=2, fontName="Helvetica-Bold"
    )
    subtitle_style = ParagraphStyle(
        'DocSub', parent=styles['Normal'],
        fontSize=8.5, textColor=colors.HexColor("#475569"), spaceAfter=8
    )
    heading_style = ParagraphStyle(
        'SecHead', parent=styles['Heading2'],
        fontSize=10.5, textColor=COLOR_ACCENT, spaceBefore=6, spaceAfter=4, fontName="Helvetica-Bold"
    )
    body_style = ParagraphStyle(
        'BodyTextCustom', parent=styles['Normal'],
        fontSize=8, leading=11, textColor=colors.HexColor("#1e293b")
    )
    bold_style = ParagraphStyle(
        'BoldCustom', parent=body_style, fontName="Helvetica-Bold"
    )

    story = []

    # Title Banner
    story.append(Paragraph("HIMALAYAN GLACIER SATELLITE ANALYSIS REPORT", title_style))
    story.append(Paragraph(f"Target Location: <b>{glacier_name}</b> | WGI ID: {info['wgi_id']} | Basin: {info['basin']}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=COLOR_ACCENT, spaceAfter=8))

    # Metrics Summary & Visual Plot (Graphical Representation)
    story.append(Paragraph("1. SATELLITE RETREAT METRICS & GRAPHICAL ANALYSIS", heading_style))
    
    table_data = [
        [Paragraph("<b>Metric Parameter</b>", body_style), Paragraph("<b>Observed Value</b>", body_style)],
        [Paragraph(f"Baseline Ice Coverage ({baseline_yr})", body_style), Paragraph(f"{area_b:.2f} sq km", body_style)],
        [Paragraph(f"Current Ice Coverage ({current_yr})", body_style), Paragraph(f"{area_c:.2f} sq km", body_style)],
        [Paragraph("Net Ice Coverage Loss", body_style), Paragraph(f"<font color='#dc2626'><b>-{area_l:.2f} sq km (-{perc_l:.1f}%)</b></font>", body_style)],
        [Paragraph("Annual Loss Velocity", body_style), Paragraph(f"<b>{loss_rate:.2f} sq km / year</b>", body_style)]
    ]
    t = Table(table_data, colWidths=[180, 120])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))

    # Add Visual Chart Plot
    chart_img_buf = generate_pdf_chart(area_b, area_c, baseline_yr, current_yr)
    rl_chart = RLImage(chart_img_buf, width=220, height=105)

    layout_table = Table([[t, rl_chart]], colWidths=[310, 230])
    layout_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(layout_table)
    story.append(Spacer(1, 6))

    # Danger Zones & GLOF Hazard Status
    story.append(Paragraph("2. HAZARD MAP & CRITICAL DANGER ZONES", heading_style))
    
    risk_table_data = [
        [
            Paragraph("<font color='#dc2626'><b>🚨 HIGH RISK DANGER ZONE</b></font>", bold_style),
            Paragraph(f"<b>Area:</b> {info['danger_zones']}<br/><b>Threat:</b> Crevasse formation, icefall, and structural snout collapse.", body_style)
        ],
        [
            Paragraph("<font color='#d97706'><b>⚠️ GLOF & LAKE EXPANSION</b></font>", bold_style),
            Paragraph(f"<b>Lake Status:</b> {info['glof_risk']}<br/><b>Early Warning Arrival Window:</b> {info['early_warning_window']}", body_style)
        ],
        [
            Paragraph("<font color='#16a34a'><b>✅ RECOMMENDED SAFE BASE</b></font>", bold_style),
            Paragraph(f"<b>Staging Zone:</b> {info['safe_zones']}<br/><b>Protocol:</b> Camp strictly above bedrock levels away from melt outflow paths.", body_style)
        ]
    ]
    
    rt = Table(risk_table_data, colWidths=[160, 380])
    rt.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,0), (0,0), colors.HexColor("#fef2f2")),
        ('BACKGROUND', (0,1), (0,1), colors.HexColor("#fffbeb")),
        ('BACKGROUND', (0,2), (0,2), colors.HexColor("#f0fdf4")),
    ]))
    story.append(rt)
    story.append(Spacer(1, 6))

    # Environmental Trigger & Public Guidelines
    story.append(Paragraph("3. ENVIRONMENTAL TRIGGERS & FIELD GUIDELINES", heading_style))
    adv_text = (
        f"• <b>Heatwave Melt Trigger:</b> {info['heatwave_trigger']}<br/>"
        f"• <b>Downstream Impact:</b> Accelerated melting affects {info['downstream_impact']} with river siltation.<br/>"
        f"• <b>Trekker Guideline:</b> Snout boundaries are structurally unviable. Entry into flagged zones is dangerous without technical ice gear."
    )
    story.append(Paragraph(adv_text, body_style))
    story.append(Spacer(1, 10))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#94a3b8"), spaceAfter=4))
    story.append(Paragraph("<i>Auto-Generated Environmental Intelligence Report • SP Vasisth Sustainability Consulting</i>", ParagraphStyle('Foot', parent=styles['Normal'], fontSize=7.5, textColor=colors.HexColor("#64748b"))))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ---------------------------------------------------------
# 8. DASHBOARD HEADER, WGMS METADATA & METRICS
# ---------------------------------------------------------
st.title("🛰️ Real-Time Himalayan Glacier Retreat Tracker")
st.caption(f"Live ESA Sentinel-2 Satellite Analytics Engine • Location: {selected_glacier_name}")

# WGMS Standard Metadata Header Card
st.markdown("### 📍 WGMS Standard Metadata Card")
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric("WGI Standard ID", selected_glacier["wgi_id"])
m_col2.metric("River Basin", selected_glacier["basin"])
m_col3.metric("Mean Elevation", selected_glacier["mean_elevation"])
m_col4.metric("Annual Retreat", selected_glacier["retreat_rate"])

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

# ---------------------------------------------------------
# 9. MAP VISUALIZATION
# ---------------------------------------------------------
st.subheader(f"🗺️ Interactive Glacier Ice Overlay ({year_baseline} vs {year_current})")

m = folium.Map(
    location=[selected_glacier["lat"], selected_glacier["lon"]],
    zoom_start=selected_glacier["zoom"],
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery"
)

viz_params = {'min': 0, 'max': 1, 'palette': ['000000', '00FFFF']}

map_id_base = ee.Image(mask_base.updateMask(mask_base)).getMapId(viz_params)
folium.TileLayer(
    tiles=map_id_base['tile_fetcher'].url_format,
    attr='Google Earth Engine',
    name=f'Glacier Ice ({year_baseline})'
).add_to(m)

map_id_curr = ee.Image(mask_curr.updateMask(mask_curr)).getMapId(viz_params)
folium.TileLayer(
    tiles=map_id_curr['tile_fetcher'].url_format,
    attr='Google Earth Engine',
    name=f'Glacier Ice ({year_current})'
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, width=1300, height=500)

# ---------------------------------------------------------
# 10. MULTI-DECADE HISTORICAL TREND & PDF EXPORTER
# ---------------------------------------------------------
st.markdown("---")

chart_col, pdf_col = st.columns([3, 1])

with chart_col:
    st.subheader("📈 Multi-Decade Historical Trend Chart (1990–2026)")
    
    h_years = list(selected_glacier["historical_data"].keys())
    h_areas = list(selected_glacier["historical_data"].values())
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=h_years, y=h_areas,
        mode='lines+markers',
        name='Surface Area (sq km)',
        line=dict(color='#00CC96', width=3),
        marker=dict(size=8, color='#636EFA')
    ))
    fig.update_layout(
        title=f"35-Year Surface Ice Reduction Curve: {selected_glacier_name}",
        xaxis_title="Year",
        yaxis_title="Area (Square Kilometers)",
        template="plotly_dark",
        height=350
    )
    st.plotly_chart(fig, use_container_width=True)

with pdf_col:
    st.subheader("📄 Automated PDF Briefing")
    st.markdown("Export a clean, single-page **Weekly Environmental Analysis Report** with graphical plot for local distribution and field planning.")
    
    pdf_bytes = generate_pdf_report(
        selected_glacier_name,
        year_baseline,
        year_current,
        area_base,
        area_curr,
        area_lost,
        perc_lost,
        annual_loss_rate,
        selected_glacier
    )

    file_name = f"{selected_glacier_name.split()[0]}_Weekly_Glacier_Report.pdf"

    st.download_button(
        label="📥 Download Weekly Report",
        data=pdf_bytes,
        file_name=file_name,
        mime="application/pdf",
        use_container_width=True
    )

# ---------------------------------------------------------
# 11. WEEKLY GLACIER ANALYSIS & RISK BRIEFING
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📋 Weekly Glacier Health & Environmental Analysis")

rep_col1, rep_col2, rep_col3 = st.columns(3)

with rep_col1:
    st.markdown(f"""
        <div class="risk-card-high">
            <h4>🚨 Danger Zones & Structural Risks</h4>
            <p><b>Targeted Area:</b> {selected_glacier['danger_zones']}</p>
            <p><b>Crevasse Hazard:</b> Rapid snout retreat causes internal structural fractures and dangerous icefalls.</p>
        </div>
    """, unsafe_allow_html=True)

with rep_col2:
    st.markdown(f"""
        <div class="risk-card-moderate">
            <h4>⚠️ GLOF & Meltwater Lake Expansion</h4>
            <p><b>Lake Risk Status:</b> {selected_glacier['glof_risk']}</p>
            <p><b>Early Warning Arrival Window:</b> {selected_glacier['early_warning_window']}</p>
        </div>
    """, unsafe_allow_html=True)

with rep_col3:
    st.markdown(f"""
        <div class="risk-card-safe">
            <h4>✅ Recommended Staging Safe Zones</h4>
            <p><b>Safe Base:</b> {selected_glacier['safe_zones']}</p>
            <p><b>Heatwave Trigger:</b> {selected_glacier['heatwave_trigger']}</p>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

st.info(f"""
**📢 Automated Weekly Field Intelligence Summary:**
* **Retreat Summary:** Between **{year_baseline}** and **{year_current}**, {selected_glacier_name} experienced a net ice loss of **{area_lost:.2f} sq km** (**-{perc_lost:.1f}%**) at an average velocity of **{annual_loss_rate:.2f} sq km/year**.
* **Environmental Impact:** Meltwater surge impacts **{selected_glacier['downstream_impact']}**, increasing seasonal river turbidity and flood risk.
* **Trekker Advisory:** Maintain camp setups strictly in recommended safe staging zones. Snout ice boundaries should be avoided without professional high-altitude ice gear.
""")
