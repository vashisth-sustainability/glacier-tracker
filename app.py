import json
import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION & HIGH CONTRAST STYLING
# ---------------------------------------------------------
st.set_page_config(
    page_title="Himalayan Glacier Satellite Monitor",
    page_icon="🧊",
    layout="wide"
)

# High contrast styling for Streamlit metric cards and text readability
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    
    /* High contrast metric containers */
    div[data-testid="stMetric"] {
        background-color: #1e293b !important;
        padding: 16px !important;
        border-radius: 10px !important;
        border: 1px solid #334155 !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }
    
    /* Metric title text */
    div[data-testid="stMetricLabel"] > label {
        color: #94a3b8 !important;
        font-size: 0.95rem !important;
        font-weight: 600 !important;
    }
    
    /* Metric main numbers/values */
    div[data-testid="stMetricValue"] > div {
        color: #ffffff !important;
        font-size: 1.8rem !important;
        font-weight: 700 !important;
    }
    
    /* Metric delta text adjustment */
    div[data-testid="stMetricDelta"] {
        font-weight: 600 !important;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. EARTH ENGINE INITIALIZATION (Robust Secrets Parser)
# ---------------------------------------------------------
@st.cache_resource
def init_ee():
    # Priority 1: Check Streamlit Secrets for Cloud Deployment
    if "GCP_SERVICE_ACCOUNT" in st.secrets:
        try:
            secrets_raw = st.secrets["GCP_SERVICE_ACCOUNT"]
            
            # Handle both JSON string and TOML dictionary formats
            if isinstance(secrets_raw, str):
                service_account_info = json.loads(secrets_raw)
            else:
                service_account_info = dict(secrets_raw)

            # Fix newline formatting in private key
            if "private_key" in service_account_info:
                service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")

            credentials = ee.ServiceAccountCredentials(
                service_account_info["client_email"],
                key_data=json.dumps(service_account_info)
            )
            ee.Initialize(credentials=credentials)
            return
        except Exception as e:
            st.error(f"Google Earth Engine Authentication Failed: {e}")
            st.stop()

    # Priority 2: Fallback for local machine testing
    try:
        ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize()

init_ee()

# ---------------------------------------------------------
# 3. GLACIER DATABASE (Coordinates & Default Zooms)
# ---------------------------------------------------------
GLACIERS = {
    "Gangotri Glacier (Uttarakhand)": {"lat": 30.9256, "lon": 79.0669, "zoom": 12},
    "Siachen Glacier (Ladakh)": {"lat": 35.4211, "lon": 77.1095, "zoom": 11},
    "Zanskar Glacier (Ladakh)": {"lat": 33.8500, "lon": 76.8333, "zoom": 12},
    "Pindari Glacier (Uttarakhand)": {"lat": 30.2625, "lon": 79.9922, "zoom": 13}
}

# ---------------------------------------------------------
# 4. SIDEBAR CONTROLS
# ---------------------------------------------------------
st.sidebar.title("🧊 Glacier Tracker AI")
st.sidebar.markdown("---")

selected_glacier_name = st.sidebar.selectbox("Select Target Glacier", list(GLACIERS.keys()))
selected_glacier = GLACIERS[selected_glacier_name]

st.sidebar.markdown("### 🗓️ Comparison Timeline")
year_baseline = st.sidebar.slider("Baseline Year", 2018, 2022, 2021)
year_current = st.sidebar.slider("Current Year", 2023, 2026, 2026)

# ---------------------------------------------------------
# 5. CORE ANALYTICS ENGINE (NDSI Algorithm & Area Calculation)
# ---------------------------------------------------------
def get_glacier_analytics(lat, lon, year):
    roi = ee.Geometry.Point([lon, lat]).buffer(8000) # 8km Radius Area
    start_date = f"{year}-05-01"
    end_date = f"{year}-09-30"
    
    # Fetch Copernicus Sentinel-2 Surface Reflectance
    s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
          .filterBounds(roi)
          .filterDate(start_date, end_date)
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 15))
          .median())
    
    # Normalized Difference Snow Index (NDSI = (B3 - B11) / (B3 + B11))
    ndsi = s2.normalizedDifference(['B3', 'B11']).rename('NDSI')
    snow_mask = ndsi.gt(0.45) # Snow Thresholding
    
    # Square Kilometer Pixel Area Calculation
    area_image = snow_mask.multiply(ee.Image.pixelArea())
    stats = area_image.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=10,
        maxPixels=1e9
    )
    
    area_sqkm = ee.Number(stats.get('NDSI')).divide(1e6).getInfo()
    return snow_mask, area_sqkm, roi

# ---------------------------------------------------------
# 6. DASHBOARD HEADER & LIVE METRICS
# ---------------------------------------------------------
st.title("🛰️ Real-Time Himalayan Glacier Retreat Tracker")
st.caption(f"Live ESA Sentinel-2 Satellite Analytics Engine • Location: {selected_glacier_name}")

with st.spinner("Fetching satellite imagery from European Space Agency (ESA)..."):
    mask_base, area_base, roi = get_glacier_analytics(selected_glacier["lat"], selected_glacier["lon"], year_baseline)
    mask_curr, area_curr, _ = get_glacier_analytics(selected_glacier["lat"], selected_glacier["lon"], year_current)

# Area Change Math
area_lost = area_base - area_curr
perc_lost = (area_lost / area_base) * 100 if area_base > 0 else 0

# Metric Cards Layout
col1, col2, col3, col4 = st.columns(4)
col1.metric(f"Glacier Area ({year_baseline})", f"{area_base:.2f} sq km")
col2.metric(f"Glacier Area ({year_current})", f"{area_curr:.2f} sq km")
col3.metric("Ice Area Retreat", f"{area_lost:.2f} sq km", delta=f"-{perc_lost:.1f}%", delta_color="inverse")
col4.metric("Data Source", "Sentinel-2 (10m Res)", delta="Live Stream")

st.markdown("---")

# ---------------------------------------------------------
# 7. MAP VISUALIZATION (Esri World Imagery + GEE Overlay)
# ---------------------------------------------------------
st.subheader(f"🗺️ Interactive Glacier Ice Overlay ({year_baseline} vs {year_current})")

m = folium.Map(
    location=[selected_glacier["lat"], selected_glacier["lon"]],
    zoom_start=selected_glacier["zoom"],
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery"
)

# Cyan Palette for Glacier Ice Highlight
viz_params = {'min': 0, 'max': 1, 'palette': ['000000', '00FFFF']}

# Baseline Layer Overlay
map_id_base = ee.Image(mask_base.updateMask(mask_base)).getMapId(viz_params)
folium.TileLayer(
    tiles=map_id_base['tile_fetcher'].url_format,
    attr='Google Earth Engine',
    name=f'Glacier Ice ({year_baseline})'
).add_to(m)

# Current Year Layer Overlay
map_id_curr = ee.Image(mask_curr.updateMask(mask_curr)).getMapId(viz_params)
folium.TileLayer(
    tiles=map_id_curr['tile_fetcher'].url_format,
    attr='Google Earth Engine',
    name=f'Glacier Ice ({year_current})'
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# Render Folium Map in Streamlit
st_folium(m, width=1300, height=500)

# ---------------------------------------------------------
# 8. ANALYTICS CHART
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
