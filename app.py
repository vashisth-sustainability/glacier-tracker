import json
import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go

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
    
    /* Custom High-Contrast Metric Cards */
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

    /* Danger / Risk Zone Styling */
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
    # 🗝️ ADMIN BYPASS: Checking if 'key=swastik' is in URL parameters
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
    st.stop()  # Lock app execution until correct password or admin key is hit

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
# 4. GLACIER DATABASE
# ---------------------------------------------------------
GLACIERS = {
    "Gangotri Glacier (Uttarakhand)": {
        "lat": 30.9256, "lon": 79.0669, "zoom": 12,
        "danger_zones": "Gaumukh Snout & Tapovan Trek Area (High Glacial Lake Outburst Risk)",
        "safe_zones": "Gangotri Temple Base / Dharali Valley",
        "retreat_rate": "22.5 meters/year",
        "downstream_impact": "Bhagirathi & Ganga River Basins (High siltation & flash flood threat)"
    },
    "Siachen Glacier (Ladakh)": {
        "lat": 35.4211, "lon": 77.1095, "zoom": 11,
        "danger_zones": "Sub-sector North Snout & Teram Shehr Glacier confluence (Ice avalanche prone)",
        "safe_zones": "Base Camp Ground & Sasoma Valley Transit Point",
        "retreat_rate": "35 meters/year",
        "downstream_impact": "Nubra & Shyok River Systems"
    },
    "Zanskar Glacier (Ladakh)": {
        "lat": 33.8500, "lon": 76.8333, "zoom": 12,
        "danger_zones": "Chadar Trek Route (Thin ice collapse zones in early spring)",
        "safe_zones": "Padum Plain Settlement Area",
        "retreat_rate": "18 meters/year",
        "downstream_impact": "Zanskar & Indus River Valley"
    },
    "Pindari Glacier (Uttarakhand)": {
        "lat": 30.2625, "lon": 79.9922, "zoom": 13,
        "danger_zones": "Zero Point Viewpoint & Trail leading to Traill's Pass (Crevasse formation)",
        "safe_zones": "Khati Village Base Encampment",
        "retreat_rate": "15 meters/year",
        "downstream_impact": "Pindar River & Alaknanda Tributaries"
    }
}

# ---------------------------------------------------------
# 5. SIDEBAR CONTROLS
# ---------------------------------------------------------
st.sidebar.title("🧊 Glacier Tracker AI")
st.sidebar.markdown("---")

selected_glacier_name = st.sidebar.selectbox("Select Target Glacier", list(GLACIERS.keys()))
selected_glacier = GLACIERS[selected_glacier_name]

st.sidebar.markdown("### 🗓️ Comparison Timeline")
year_baseline = st.sidebar.slider("Baseline Year", 2018, 2022, 2021)
year_current = st.sidebar.slider("Current Year", 2023, 2026, 2026)

# ---------------------------------------------------------
# 6. CORE ANALYTICS ENGINE
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

# ---------------------------------------------------------
# 7. DASHBOARD HEADER & METRICS
# ---------------------------------------------------------
st.title("🛰️ Real-Time Himalayan Glacier Retreat Tracker")
st.caption(f"Live ESA Sentinel-2 Satellite Analytics Engine • Location: {selected_glacier_name}")

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
# 8. MAP VISUALIZATION
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
# 9. ANALYTICS CHART
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📊 Ice Area Retreat Summary Chart")

fig = go.Figure(data=[
    go.Bar(
        x=[f"{year_baseline} Baseline", f"{year_current} Current"],
        y=[area_base, area_curr],
        marker_color=['#00b4d8', '#ff4d6d'],
        text=[f"{area_base:.2f} sq km", f"{area_curr:.2f} sq km"],
        textposition='auto'
    )
])

fig.update_layout(
    title=f"Total Surface Ice Coverage Reduction for {selected_glacier_name}",
    yaxis_title="Area (Square Kilometers)",
    template="plotly_dark",
    height=350
)

st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------
# 10. WEEKLY GLACIER ANALYSIS & RISK BRIEFING (NEW)
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📋 Weekly Glacier Health & Safety Analysis Report")

rep_col1, rep_col2, rep_col3 = st.columns(3)

with rep_col1:
    st.markdown(f"""
        <div class="risk-card-high">
            <h4>🚨 Danger Zones (Avoid Movement)</h4>
            <p><b>Targeted Area:</b> {selected_glacier['danger_zones']}</p>
            <p><b>Primary Hazard:</b> Crevasse formation, structural ice collapse, and GLOF (Glacial Lake Outburst Flood) risks due to meltwater accumulation.</p>
        </div>
    """, unsafe_allow_html=True)

with rep_col2:
    st.markdown(f"""
        <div class="risk-card-safe">
            <h4>✅ Recommended Safe Zones</h4>
            <p><b>Staging Base:</b> {selected_glacier['safe_zones']}</p>
            <p><b>Safety Protocol:</b> Maintain encampment strictly below structural bedrock levels and away from narrow river paths.</p>
        </div>
    """, unsafe_allow_html=True)

with rep_col3:
    st.markdown(f"""
        <div class="risk-card-moderate">
            <h4>🌍 Environmental & Downstream Impact</h4>
            <p><b>Melt Velocity:</b> ~{selected_glacier['retreat_rate']}</p>
            <p><b>Impacted Regions:</b> {selected_glacier['downstream_impact']}</p>
            <p><b>Seasonal Risk:</b> Surge in river water levels and sudden siltation affecting local infrastructure.</p>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Detailed Advisory Text
st.info(f"""
**📢 Field Safety Advisory for Local Communities & Trekkers:**
* **Glacier Retreat Trend:** Between **{year_baseline}** and **{year_current}**, {selected_glacier_name} lost **{area_lost:.2f} sq km** of total ice cover (average decline rate of **{annual_loss_rate:.2f} sq km/year**).
* **Structural Stability:** Rapid retreat accelerates snout fracturing. Trekkers and pilgrims are advised **not to step onto snout ice boundaries** without high-altitude safety gear.
* **Early Warning:** Continuous monitoring via Sentinel-2 satellite images helps track proglacial lakes that can burst during summer heatwaves.
""")
