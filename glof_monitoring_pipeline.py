#!/usr/bin/env python3
"""
SP Vasisth Sustainability Consulting
GLOF & Catchment Risk Monitoring Pipeline
==========================================
Production-ready modular pipeline that:
  1. Loads hydro asset targets from hydro_targets.json
  2. Runs Sentinel-1 SAR (VV/VH) multi-temporal backscatter analysis
  3. Runs Sentinel-2 optical NDWI/NDVI change detection
  4. Extracts SRTM/NASADEM slope & elevation hazard metrics
  5. Exports GeoTIFF/PNG evidence maps
  6. Generates a 1-page executive PDF Hazard Audit Report per asset

Dependencies:
    pip install earthengine-api geemap reportlab matplotlib numpy requests pillow

Authentication:
    ee.Initialize()  # or pass service account credentials
"""

import json
import os
import math
import datetime
import tempfile
from typing import Dict, List, Any, Tuple

import ee
import geemap
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    Image as RLImage, HRFlowable
)

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------
S1_COLLECTION = "COPERNICUS/S1_GRD"
S2_COLLECTION = "COPERNICUS/S2_SR"
DEM_COLLECTION = "NASA/NASADEM_HGT/001"

# Analysis windows (days)
RECENT_DAYS = 30          # "current" window
BASELINE_DAYS = 180       # "baseline" window ending before recent window

# Hazard thresholds
SAR_WATER_ANOMALY_DB = -1.5   # VH/VV decrease indicating new water
NDWI_EXPANSION = 0.10         # NDWI increase indicating water gain
NDVI_VEG_LOSS = -0.10         # NDVI decrease indicating vegetation/sediment stress
SLOPE_HAZARD_DEG = 30.0       # steep slope threshold

# Output directories
OUTPUT_DIR = "output"
RASTER_DIR = os.path.join(OUTPUT_DIR, "rasters")
MAP_DIR = os.path.join(OUTPUT_DIR, "maps")
PDF_DIR = os.path.join(OUTPUT_DIR, "pdfs")

for _d in [OUTPUT_DIR, RASTER_DIR, MAP_DIR, PDF_DIR]:
    os.makedirs(_d, exist_ok=True)


# -----------------------------------------------------------------------------
# 1. CONFIGURATION LOADING
# -----------------------------------------------------------------------------
def load_targets(config_path: str = "hydro_targets.json") -> List[Dict[str, Any]]:
    """Load hydro asset target list from JSON configuration."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["targets"]


# -----------------------------------------------------------------------------
# 2. GEE INITIALIZATION
# -----------------------------------------------------------------------------
def initialize_gee(service_account: str = None, key_file: str = None) -> None:
    """Initialize Earth Engine with user auth or service account."""
    if service_account and key_file:
        credentials = ee.ServiceAccountCredentials(service_account, key_file)
        ee.Initialize(credentials)
    else:
        ee.Initialize()
    print("[GEE] Earth Engine initialized successfully.")


# -----------------------------------------------------------------------------
# 3. AREA OF INTEREST
# -----------------------------------------------------------------------------
def create_aoi(target: Dict[str, Any]) -> Tuple[ee.Geometry, ee.Geometry]:
    """Create a circular buffer AOI around the target asset."""
    point = ee.Geometry.Point([target["longitude"], target["latitude"]])
    radius_m = target["buffer_km"] * 1000.0
    aoi = point.buffer(radius_m)
    return aoi, point


# -----------------------------------------------------------------------------
# 4. SENTINEL-1 SAR PROCESSING
# -----------------------------------------------------------------------------
def get_s1_collection(aoi: ee.Geometry, start: str, end: str) -> ee.ImageCollection:
    """Filter Sentinel-1 GRD scenes for the AOI and date range."""
    return (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.inList("orbitProperties_pass", ["ASCENDING", "DESCENDING"]))
        .select(["VV", "VH"])
    )


def terrain_flatten_s1(image: ee.Image) -> ee.Image:
    """Apply first-order radiometric terrain flattening correction using NASADEM."""
    dem = ee.Image(DEM_COLLECTION).select("elevation")
    slope_rad = ee.Terrain.slope(dem).multiply(math.pi / 180.0)
    corr = slope_rad.cos().clip(0.1, 1.0)

    vv_flat = image.select("VV").divide(corr).rename("VV_flat")
    vh_flat = image.select("VH").divide(corr).rename("VH_flat")
    return image.addBands(vv_flat).addBands(vh_flat)


def to_db(image: ee.Image) -> ee.Image:
    """Convert linear backscatter values to decibels (dB)."""
    return ee.Image(10.0).multiply(image.log10())


def compute_sar_anomaly(aoi: ee.Geometry, end_date: datetime.date) -> ee.Image:
    """Compute multi-temporal Sentinel-1 backscatter anomaly."""
    recent_start = (end_date - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    recent_end = end_date.isoformat()
    baseline_end = (end_date - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    baseline_start = (end_date - datetime.timedelta(days=RECENT_DAYS + BASELINE_DAYS)).isoformat()

    recent_s1 = get_s1_collection(aoi, recent_start, recent_end).map(terrain_flatten_s1)
    baseline_s1 = get_s1_collection(aoi, baseline_start, baseline_end).map(terrain_flatten_s1)

    recent_db = to_db(recent_s1.select(["VV_flat", "VH_flat"]).median())
    baseline_db = to_db(baseline_s1.select(["VV_flat", "VH_flat"]).median())

    anomaly = recent_db.subtract(baseline_db).rename(["VV_anomaly_db", "VH_anomaly_db"])
    water_mask = anomaly.select("VH_anomaly_db").lt(SAR_WATER_ANOMALY_DB).rename("water_expansion_mask")

    return anomaly.addBands(water_mask)


# -----------------------------------------------------------------------------
# 5. SENTINEL-2 OPTICAL PROCESSING
# -----------------------------------------------------------------------------
def get_s2_collection(aoi: ee.Geometry, start: str, end: str) -> ee.ImageCollection:
    """Filter Sentinel-2 SR scenes with QA60 cloud masking."""
    def mask_clouds(img):
        qa = img.select("QA60")
        cloud_bit = 1 << 10
        cirrus_bit = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0))
        return img.updateMask(mask)

    return (
        ee.ImageCollection(S2_COLLECTION)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .map(mask_clouds)
        .select(["B3", "B4", "B8", "QA60"])
    )


def add_indices(img: ee.Image) -> ee.Image:
    """Calculate and append NDWI and NDVI indices."""
    ndwi = img.normalizedDifference(["B3", "B8"]).rename("NDWI")
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return img.addBands(ndwi).addBands(ndvi)


def compute_optical_change(aoi: ee.Geometry, end_date: datetime.date) -> ee.Image:
    """Compute Sentinel-2 NDWI/NDVI change relative to baseline."""
    recent_start = (end_date - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    recent_end = end_date.isoformat()
    baseline_end = (end_date - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    baseline_start = (end_date - datetime.timedelta(days=RECENT_DAYS + BASELINE_DAYS)).isoformat()

    recent_s2 = get_s2_collection(aoi, recent_start, recent_end).map(add_indices)
    baseline_s2 = get_s2_collection(aoi, baseline_start, baseline_end).map(add_indices)

    recent_med = recent_s2.select(["NDWI", "NDVI"]).median()
    baseline_med = baseline_s2.select(["NDWI", "NDVI"]).median()

    change = recent_med.subtract(baseline_med).rename(["NDWI_change", "NDVI_change"])

    water_gain = change.select("NDWI_change").gt(NDWI_EXPANSION).rename("water_gain_mask")
    veg_loss = change.select("NDVI_change").lt(NDVI_VEG_LOSS).rename("veg_loss_mask")

    return change.addBands(water_gain).addBands(veg_loss)


# -----------------------------------------------------------------------------
# 6. DEM / SLOPE ANALYSIS
# -----------------------------------------------------------------------------
def analyze_dem(aoi: ee.Geometry) -> ee.Image:
    """Extract NASADEM elevation, slope, and critical slope hazard mask."""
    dem = ee.Image(DEM_COLLECTION).select("elevation")
    slope = ee.Terrain.slope(dem).rename("slope_deg")
    hazard_mask = slope.gt(SLOPE_HAZARD_DEG).rename("slope_hazard_mask")
    return dem.addBands(slope).addBands(hazard_mask)


# -----------------------------------------------------------------------------
# 7. RISK SCORING
# -----------------------------------------------------------------------------
def assess_risk(
    sar_anomaly: ee.Image,
    optical_change: ee.Image,
    dem_analysis: ee.Image,
    aoi: ee.Geometry
) -> Dict[str, Any]:
    """Compute area statistics and classify risk levels (High/Medium/Low)."""
    evidence = (
        sar_anomaly
        .addBands(optical_change)
        .addBands(dem_analysis)
        .select([
            "VH_anomaly_db", "water_expansion_mask",
            "NDWI_change", "NDVI_change", "water_gain_mask", "veg_loss_mask",
            "elevation", "slope_deg", "slope_hazard_mask"
        ])
        .clip(aoi)
    )

    pixel_area = ee.Image.pixelArea().divide(1e6)
    evidence_with_area = evidence.addBands(pixel_area.rename("area_km2"))

    def get_sum(band):
        val = evidence_with_area.select(band).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi,
            scale=30,
            maxPixels=1e10,
            bestEffort=True
        ).get(band)
        return ee.Number(val).getInfo() if val else 0.0

    def get_mean(band):
        val = evidence.select(band).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=30,
            maxPixels=1e10,
            bestEffort=True
        ).get(band)
        return ee.Number(val).getInfo() if val else 0.0

    total_area_km2 = get_sum("area_km2")
    water_anomaly_area_km2 = get_sum("water_expansion_mask")
    water_gain_area_km2 = get_sum("water_gain_mask")
    veg_loss_area_km2 = get_sum("veg_loss_mask")
    slope_hazard_area_km2 = get_sum("slope_hazard_mask")

    mean_vh_anomaly_db = get_mean("VH_anomaly_db")
    mean_ndwi_change = get_mean("NDWI_change")
    mean_ndvi_change = get_mean("NDVI_change")
    mean_slope_deg = get_mean("slope_deg")
    mean_elevation_m = get_mean("elevation")

    pct_water = (water_anomaly_area_km2 / total_area_km2 * 100) if total_area_km2 else 0
    pct_water_gain = (water_gain_area_km2 / total_area_km2 * 100) if total_area_km2 else 0
    pct_veg_loss = (veg_loss_area_km2 / total_area_km2 * 100) if total_area_km2 else 0
    pct_slope_hazard = (slope_hazard_area_km2 / total_area_km2 * 100) if total_area_km2 else 0

    def risk_level(value, high_thresh, med_thresh):
        if value >= high_thresh:
            return "HIGH"
        elif value >= med_thresh:
            return "MEDIUM"
        return "LOW"

    glof_risk = risk_level(pct_water + pct_water_gain, 5.0, 2.0)
    slope_risk = risk_level(pct_slope_hazard, 30.0, 15.0)
    sediment_risk = risk_level(pct_veg_loss, 10.0, 5.0)

    return {
        "total_area_km2": total_area_km2,
        "water_anomaly_area_km2": water_anomaly_area_km2,
        "water_gain_area_km2": water_gain_area_km2,
        "veg_loss_area_km2": veg_loss_area_km2,
        "slope_hazard_area_km2": slope_hazard_area_km2,
        "mean_vh_anomaly_db": mean_vh_anomaly_db,
        "mean_ndwi_change": mean_ndwi_change,
        "mean_ndvi_change": mean_ndvi_change,
        "mean_slope_deg": mean_slope_deg,
        "mean_elevation_m": mean_elevation_m,
        "pct_water_anomaly": pct_water,
        "pct_water_gain": pct_water_gain,
        "pct_veg_loss": pct_veg_loss,
        "pct_slope_hazard": pct_slope_hazard,
        "glof_risk": glof_risk,
        "slope_risk": slope_risk,
        "sediment_risk": sediment_risk,
    }


# -----------------------------------------------------------------------------
# 8. EXPORT RASTERS & MAPS
# -----------------------------------------------------------------------------
def export_rasters(
    target: Dict[str, Any],
    sar_anomaly: ee.Image,
    optical_change: ee.Image,
    dem_analysis: ee.Image,
    aoi: ee.Geometry
) -> Dict[str, str]:
    """Export GeoTIFF rasters locally and generate PNG visualization maps."""
    asset_id = target["id"]
    prefix = os.path.join(RASTER_DIR, asset_id)

    export_img = (
        sar_anomaly
        .addBands(optical_change)
        .addBands(dem_analysis)
        .select([
            "VV_anomaly_db", "VH_anomaly_db", "water_expansion_mask",
            "NDWI_change", "NDVI_change", "water_gain_mask", "veg_loss_mask",
            "elevation", "slope_deg", "slope_hazard_mask"
        ])
        .clip(aoi)
    )

    geotiff_path = f"{prefix}_analysis.tif"
    geemap.ee_export_image(
        export_img,
        filename=geotiff_path,
        scale=30,
        region=aoi,
        file_per_band=False
    )
    print(f"[EXPORT] GeoTIFF exported: {geotiff_path}")

    sar_png = os.path.join(MAP_DIR, f"{asset_id}_SAR_anomaly.png")
    optical_png = os.path.join(MAP_DIR, f"{asset_id}_Optical_change.png")

    # Render SAR anomaly PNG map
    sar_vh = sar_anomaly.select("VH_anomaly_db").clip(aoi)
    cmap_sar = LinearSegmentedColormap.from_list("sar_cmap", ["#08306b", "#ffffff", "#67000d"])
    plt.figure(figsize=(8, 6))
    sar_data = geemap.ee_to_numpy(sar_vh, region=aoi, scale=30)
    if sar_data is not None and sar_data.size:
        plt.imshow(sar_data[:, :, 0], cmap=cmap_sar, vmin=-3, vmax=3)
        plt.colorbar(label="VH anomaly (dB)")
    plt.title(f"{target['name']}\nSentinel-1 SAR Backscatter Anomaly (VH)")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(sar_png, dpi=150, bbox_inches="tight")
    plt.close()

    # Render Optical change PNG map
    ndwi_change = optical_change.select("NDWI_change").clip(aoi)
    cmap_ndwi = LinearSegmentedColormap.from_list("ndwi_cmap", ["#8c2d04", "#ffffff", "#045a8d"])
    plt.figure(figsize=(8, 6))
    ndwi_data = geemap.ee_to_numpy(ndwi_change, region=aoi, scale=30)
    if ndwi_data is not None and ndwi_data.size:
        plt.imshow(ndwi_data[:, :, 0], cmap=cmap_ndwi, vmin=-0.3, vmax=0.3)
        plt.colorbar(label="NDWI change")
    plt.title(f"{target['name']}\nSentinel-2 Optical Lake Boundary Change (NDWI)")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(optical_png, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"[MAP] SAR map saved: {sar_png}")
    print(f"[MAP] Optical map saved: {optical_png}")

    return {"sar_png": sar_png, "optical_png": optical_png, "geotiff": geotiff_path}


# -----------------------------------------------------------------------------
# 9. PDF REPORT GENERATION
# -----------------------------------------------------------------------------
def generate_pdf_report(
    target: Dict[str, Any],
    risk: Dict[str, Any],
    maps: Dict[str, str],
    audit_timestamp: str
) -> str:
    """Generate a 1-page executive PDF Hazard Audit Report."""
    asset_id = target["id"]
    pdf_path = os.path.join(PDF_DIR, f"{asset_id}_Hazard_Audit.pdf")

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Title"], fontSize=15, textColor=colors.HexColor("#1a4d2e"), alignment=0
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#444444"), alignment=2
    )
    section_style = ParagraphStyle(
        "SectionStyle", parent=styles["Heading2"], fontSize=10, textColor=colors.HexColor("#1a4d2e"),
        spaceBefore=4, spaceAfter=2
    )
    bullet_style = ParagraphStyle(
        "BulletStyle", parent=styles["Normal"], fontSize=8, leading=10.5
    )

    story = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph("<b>SP Vasisth Sustainability Consulting</b><br/><font size=8 color='#555555'>Climate Risk & Remote Sensing Advisory</font>", title_style),
            Paragraph(f"<b>Executive Hazard Audit Report</b><br/><font size=8 color='#555555'>GLOF & Catchment Monitoring</font>", subtitle_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[105 * mm, 80 * mm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e8f0e4")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#1a4d2e")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 3 * mm))

    # 2. Asset Overview Table
    overview_data = [
        ["Asset Name", target["name"], "Location Coordinates", f"{target['latitude']:.4f}° N, {target['longitude']:.4f}° E"],
        ["River Basin", target["river_basin"], "Catchment Buffer Radius", f"{target['buffer_km']} km"],
        ["State / Region", target["state"], "Audit Timestamp", audit_timestamp],
    ]
    overview_table = Table(overview_data, colWidths=[38 * mm, 55 * mm, 42 * mm, 50 * mm])
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4f1")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f0f4f1")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 3 * mm))

    # 3. Hazard Risk Scorecard
    scorecard_data = [
        ["Hazard Metric Analyzed", "Observed Value / Indicator", "Assessed Risk Level"],
        ["GLOF & Lake Boundary Expansion", f"Water Gain: {risk['pct_water_gain']:.2f}%", risk['glof_risk']],
        ["Slope Instability & Displacement", f"High Slope Area (>30°): {risk['pct_slope_hazard']:.2f}%", risk['slope_risk']],
        ["Catchment Sedimentation / Veg Loss", f"Vegetation Stress Area: {risk['pct_veg_loss']:.2f}%", risk['sediment_risk']],
    ]
    scorecard_table = Table(scorecard_data, colWidths=[70 * mm, 75 * mm, 40 * mm])
    scorecard_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a4d2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(scorecard_table)
    story.append(Spacer(1, 3 * mm))

    # 4. Satellite Visual Maps
    if os.path.exists(maps["sar_png"]) and os.path.exists(maps["optical_png"]):
        img_table_data = [[
            RLImage(maps["sar_png"], width=88 * mm, height=62 * mm),
            RLImage(maps["optical_png"], width=88 * mm, height=62 * mm)
        ]]
        img_table = Table(img_table_data, colWidths=[92 * mm, 92 * mm])
        img_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(img_table)
        story.append(Spacer(1, 3 * mm))

    # 5. Executive Summary & Verdict
    story.append(Paragraph("Executive Audit Verdict & Risk Statement", section_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a4d2e"), spaceAfter=3))

    summary_text = (
        f"• <b>Sentinel-1 SAR Radar Analysis:</b> Multi-temporal C-band radar tracking detected a mean backscatter shift of "
        f"<b>{risk['mean_vh_anomaly_db']:.2f} dB</b> across the {target['buffer_km']} km upstream catchment buffer, identifying "
        f"potential all-weather surface water anomalies.<br/>"
        f"• <b>Sentinel-2 Optical & Elevation Audit:</b> Multi-spectral NDWI differential analysis shows a <b>{risk['pct_water_gain']:.2f}%</b> "
        f"water body area expansion. NASADEM elevation model indicates <b>{risk['pct_slope_hazard']:.2f}%</b> of the upstream terrain exceeds critical stability thresholds (>30°).<br/>"
        f"• <b>Compliance Verdict:</b> Site exhibits an overall <b>{risk['glof_risk']} GLOF Risk</b> and <b>{risk['slope_risk']} Slope Hazard Level</b>. "
        f"This audit report is structured for asset protection, structural safety compliance, and TCFD physical risk disclosures."
    )
    story.append(Paragraph(summary_text, bullet_style))

    doc.build(story)
    print(f"[PDF] Executive PDF report generated: {pdf_path}")
    return pdf_path


# -----------------------------------------------------------------------------
# 10. BATCH EXECUTION ENGINE
# -----------------------------------------------------------------------------
def run_pipeline():
    """Main batch processing engine for all targets in hydro_targets.json."""
    print("==================================================================")
    print("SP Vasisth Sustainability Consulting - Satellite Monitoring Engine")
    print("==================================================================")

    # Initialize GEE
    initialize_gee()

    # Load targets
    targets = load_targets("hydro_targets.json")
    today = datetime.date.today()
    timestamp_str = today.strftime("%Y-%m-%d")

    for idx, target in enumerate(targets, start=1):
        print(f"\n[{idx}/{len(targets)}] Processing Target Asset: {target['name']} ({target['id']})...")
        
        # 1. Create AOI
        aoi, point = create_aoi(target)

        # 2. Run GEE Remote Sensing Pipelines
        print(" -> Running Sentinel-1 SAR Backscatter Anomaly Analysis...")
        sar_anomaly = compute_sar_anomaly(aoi, today)

        print(" -> Running Sentinel-2 Optical Change & Index Analysis...")
        optical_change = compute_optical_change(aoi, today)

        print(" -> Extracting NASADEM Elevation & Slope Metrics...")
        dem_analysis = analyze_dem(aoi)

        # 3. Assess Risk Metrics
        print(" -> Computing Catchment Risk Metrics & Scoring...")
        risk_metrics = assess_risk(sar_anomaly, optical_change, dem_analysis, aoi)

        # 4. Export Rasters & Visualization Maps
        print(" -> Exporting GeoTIFF Rasters and Rendering Satellite PNG Maps...")
        map_paths = export_rasters(target, sar_anomaly, optical_change, dem_analysis, aoi)

        # 5. Build 1-Page PDF Audit Report
        print(" -> Building 1-Page Executive PDF Hazard Audit Report...")
        generate_pdf_report(target, risk_metrics, map_paths, timestamp_str)

    print("\n==================================================================")
    print("[SUCCESS] All 6 Target Sites Processed Successfully.")
    print(f"PDF Reports Exported To: {os.path.abspath(PDF_DIR)}")
    print("==================================================================")


if __name__ == "__main__":
    run_pipeline()
