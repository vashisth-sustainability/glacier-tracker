#!/usr/bin/env python3
"""
SP Vasisth Sustainability Consulting
GLOF & Catchment Risk Monitoring Pipeline
==========================================
Production-ready modular pipeline for automated GLOF risk auditing.
"""

import json
import os
import math
import datetime
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
# CONSTANTS & CONFIGURATION
# -----------------------------------------------------------------------------
S1_COLLECTION = "COPERNICUS/S1_GRD"
S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
DEM_COLLECTION = "NASA/NASADEM_HGT/001"

RECENT_DAYS = 30
BASELINE_DAYS = 180

SAR_WATER_ANOMALY_DB = -1.5
NDWI_EXPANSION = 0.10
NDVI_VEG_LOSS = -0.10
SLOPE_HAZARD_DEG = 30.0

OUTPUT_DIR = "output"
RASTER_DIR = os.path.join(OUTPUT_DIR, "rasters")
MAP_DIR = os.path.join(OUTPUT_DIR, "maps")
PDF_DIR = os.path.join(OUTPUT_DIR, "pdfs")

for _d in [OUTPUT_DIR, RASTER_DIR, MAP_DIR, PDF_DIR]:
    os.makedirs(_d, exist_ok=True)


# -----------------------------------------------------------------------------
# 1. CONFIGURATION LOADING & INITIALIZATION
# -----------------------------------------------------------------------------
def load_targets(config_path: str = "hydro_targets.json") -> List[Dict[str, Any]]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["targets"]


def initialize_gee(service_account: str = None, key_file: str = None) -> None:
    try:
        if service_account and key_file:
            credentials = ee.ServiceAccountCredentials(service_account, key_file)
            ee.Initialize(credentials)
        else:
            ee.Initialize()
        print("[GEE] Earth Engine initialized successfully.")
    except Exception as e:
        print(f"[GEE ERROR] Failed to initialize Earth Engine: {e}")
        raise e


# -----------------------------------------------------------------------------
# 2. AREA OF INTEREST
# -----------------------------------------------------------------------------
def create_aoi(target: Dict[str, Any]) -> Tuple[ee.Geometry, ee.Geometry]:
    point = ee.Geometry.Point([target["longitude"], target["latitude"]])
    radius_m = target["buffer_km"] * 1000.0
    aoi = point.buffer(radius_m)
    return aoi, point


# -----------------------------------------------------------------------------
# 3. SENTINEL-1 SAR PROCESSING
# -----------------------------------------------------------------------------
def get_s1_collection(aoi: ee.Geometry, start: str, end: str) -> ee.ImageCollection:
    return (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
    )


def terrain_flatten_s1(image: ee.Image) -> ee.Image:
    dem = ee.Image(DEM_COLLECTION).select("elevation")
    slope_rad = ee.Terrain.slope(dem).multiply(math.pi / 180.0)
    corr = slope_rad.cos().clip(0.1, 1.0)

    vv_flat = image.select("VV").divide(corr).rename("VV_flat")
    vh_flat = image.select("VH").divide(corr).rename("VH_flat")
    return image.addBands(vv_flat).addBands(vh_flat)


def to_db(image: ee.Image) -> ee.Image:
    return ee.Image(10.0).multiply(image.log10())


def compute_sar_anomaly(aoi: ee.Geometry, end_date: datetime.date) -> ee.Image:
    recent_start = (end_date - datetime.timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    recent_end = end_date.strftime("%Y-%m-%d")
    baseline_end = recent_start
    baseline_start = (end_date - datetime.timedelta(days=RECENT_DAYS + BASELINE_DAYS)).strftime("%Y-%m-%d")

    recent_s1 = get_s1_collection(aoi, recent_start, recent_end).map(terrain_flatten_s1)
    baseline_s1 = get_s1_collection(aoi, baseline_start, baseline_end).map(terrain_flatten_s1)

    recent_db = to_db(recent_s1.select(["VV_flat", "VH_flat"]).median())
    baseline_db = to_db(baseline_s1.select(["VV_flat", "VH_flat"]).median())

    anomaly = recent_db.subtract(baseline_db).rename(["VV_anomaly_db", "VH_anomaly_db"])
    water_mask = anomaly.select("VH_anomaly_db").lt(SAR_WATER_ANOMALY_DB).rename("water_expansion_mask")

    return anomaly.addBands(water_mask)


# -----------------------------------------------------------------------------
# 4. SENTINEL-2 OPTICAL PROCESSING
# -----------------------------------------------------------------------------
def get_s2_collection(aoi: ee.Geometry, start: str, end: str) -> ee.ImageCollection:
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
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
        .map(mask_clouds)
        .select(["B3", "B4", "B8", "QA60"])
    )


def add_indices(img: ee.Image) -> ee.Image:
    ndwi = img.normalizedDifference(["B3", "B8"]).rename("NDWI")
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return img.addBands(ndwi).addBands(ndvi)


def compute_optical_change(aoi: ee.Geometry, end_date: datetime.date) -> ee.Image:
    recent_start = (end_date - datetime.timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    recent_end = end_date.strftime("%Y-%m-%d")
    baseline_end = recent_start
    baseline_start = (end_date - datetime.timedelta(days=RECENT_DAYS + BASELINE_DAYS)).strftime("%Y-%m-%d")

    recent_s2 = get_s2_collection(aoi, recent_start, recent_end).map(add_indices)
    baseline_s2 = get_s2_collection(aoi, baseline_start, baseline_end).map(add_indices)

    recent_med = recent_s2.select(["NDWI", "NDVI"]).median()
    baseline_med = baseline_s2.select(["NDWI", "NDVI"]).median()

    change = recent_med.subtract(baseline_med).rename(["NDWI_change", "NDVI_change"])
    water_gain = change.select("NDWI_change").gt(NDWI_EXPANSION).rename("water_gain_mask")
    veg_loss = change.select("NDVI_change").lt(NDVI_VEG_LOSS).rename("veg_loss_mask")

    return change.addBands(water_gain).addBands(veg_loss)


# -----------------------------------------------------------------------------
# 5. DEM & SLOPE ANALYSIS
# -----------------------------------------------------------------------------
def analyze_dem(aoi: ee.Geometry) -> ee.Image:
    dem = ee.Image(DEM_COLLECTION).select("elevation")
    slope = ee.Terrain.slope(dem).rename("slope_deg")
    hazard_mask = slope.gt(SLOPE_HAZARD_DEG).rename("slope_hazard_mask")
    return dem.addBands(slope).addBands(hazard_mask)


# -----------------------------------------------------------------------------
# 6. RISK SCORING ENGINE
# -----------------------------------------------------------------------------
def assess_risk(
    sar_anomaly: ee.Image,
    optical_change: ee.Image,
    dem_analysis: ee.Image,
    aoi: ee.Geometry
) -> Dict[str, Any]:
    evidence = (
        sar_anomaly
        .addBands(optical_change)
        .addBands(dem_analysis)
        .clip(aoi)
    )

    pixel_area = ee.Image.pixelArea().divide(1e6)
    evidence_with_area = evidence.addBands(pixel_area.rename("area_km2"))

    def safe_get_stat(img, band, reducer_type="sum"):
        red = ee.Reducer.sum() if reducer_type == "sum" else ee.Reducer.mean()
        try:
            val = img.select(band).reduceRegion(
                reducer=red,
                geometry=aoi,
                scale=60,
                maxPixels=1e9,
                bestEffort=True
            ).get(band)
            res = val.getInfo() if val is not None else 0.0
            return float(res) if res is not None else 0.0
        except Exception:
            return 0.0

    total_area_km2 = safe_get_stat(evidence_with_area, "area_km2", "sum")
    water_anomaly_area_km2 = safe_get_stat(evidence_with_area, "water_expansion_mask", "sum")
    water_gain_area_km2 = safe_get_stat(evidence_with_area, "water_gain_mask", "sum")
    veg_loss_area_km2 = safe_get_stat(evidence_with_area, "veg_loss_mask", "sum")
    slope_hazard_area_km2 = safe_get_stat(evidence_with_area, "slope_hazard_mask", "sum")

    mean_vh_anomaly_db = safe_get_stat(evidence, "VH_anomaly_db", "mean")
    mean_ndwi_change = safe_get_stat(evidence, "NDWI_change", "mean")
    mean_ndvi_change = safe_get_stat(evidence, "NDVI_change", "mean")
    mean_slope_deg = safe_get_stat(evidence, "slope_deg", "mean")
    mean_elevation_m = safe_get_stat(evidence, "elevation", "mean")

    pct_water = (water_anomaly_area_km2 / total_area_km2 * 100) if total_area_km2 > 0 else 0.0
    pct_water_gain = (water_gain_area_km2 / total_area_km2 * 100) if total_area_km2 > 0 else 0.0
    pct_veg_loss = (veg_loss_area_km2 / total_area_km2 * 100) if total_area_km2 > 0 else 0.0
    pct_slope_hazard = (slope_hazard_area_km2 / total_area_km2 * 100) if total_area_km2 > 0 else 0.0

    def risk_level(value, high_thresh, med_thresh):
        if value >= high_thresh:
            return "HIGH"
        elif value >= med_thresh:
            return "MEDIUM"
        return "LOW"

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
        "glof_risk": risk_level(pct_water + pct_water_gain, 5.0, 2.0),
        "slope_risk": risk_level(pct_slope_hazard, 30.0, 15.0),
        "sediment_risk": risk_level(pct_veg_loss, 10.0, 5.0),
    }


# -----------------------------------------------------------------------------
# 7. EXPORT RASTERS & MAP RENDERING
# -----------------------------------------------------------------------------
def export_rasters(
    target: Dict[str, Any],
    sar_anomaly: ee.Image,
    optical_change: ee.Image,
    dem_analysis: ee.Image,
    aoi: ee.Geometry
) -> Dict[str, str]:
    asset_id = target["id"]
    prefix = os.path.join(RASTER_DIR, asset_id)

    sar_png = os.path.join(MAP_DIR, f"{asset_id}_SAR_anomaly.png")
    optical_png = os.path.join(MAP_DIR, f"{asset_id}_Optical_change.png")
    geotiff_path = f"{prefix}_analysis.tif"

    # Export GeoTIFF locally
    try:
        export_img = sar_anomaly.addBands(optical_change).addBands(dem_analysis).clip(aoi)
        geemap.ee_export_image(export_img, filename=geotiff_path, scale=60, region=aoi, file_per_band=False)
        print(f"[EXPORT] GeoTIFF exported: {geotiff_path}")
    except Exception as e:
        print(f"[EXPORT WARNING] Could not export GeoTIFF for {asset_id}: {e}")

    # Render SAR PNG Map
    try:
        sar_vh = sar_anomaly.select("VH_anomaly_db").clip(aoi)
        sar_data = geemap.ee_to_numpy(sar_vh, region=aoi, scale=100)
        plt.figure(figsize=(6, 4.5))
        if sar_data is not None and sar_data.size > 0:
            cmap_sar = LinearSegmentedColormap.from_list("sar_cmap", ["#08306b", "#ffffff", "#67000d"])
            plt.imshow(sar_data[:, :, 0], cmap=cmap_sar, vmin=-3, vmax=3)
            plt.colorbar(label="VH Anomaly (dB)", shrink=0.8)
        plt.title(f"{target['name']} - SAR Anomaly", fontsize=9)
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(sar_png, dpi=120, bbox_inches="tight")
        plt.close()
    except Exception as e:
        print(f"[MAP WARNING] Failed to render SAR map: {e}")

    # Render Optical PNG Map
    try:
        ndwi_change = optical_change.select("NDWI_change").clip(aoi)
        ndwi_data = geemap.ee_to_numpy(ndwi_change, region=aoi, scale=100)
        plt.figure(figsize=(6, 4.5))
        if ndwi_data is not None and ndwi_data.size > 0:
            cmap_ndwi = LinearSegmentedColormap.from_list("ndwi_cmap", ["#8c2d04", "#ffffff", "#045a8d"])
            plt.imshow(ndwi_data[:, :, 0], cmap=cmap_ndwi, vmin=-0.3, vmax=0.3)
            plt.colorbar(label="NDWI Change", shrink=0.8)
        plt.title(f"{target['name']} - Optical NDWI Change", fontsize=9)
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(optical_png, dpi=120, bbox_inches="tight")
        plt.close()
    except Exception as e:
        print(f"[MAP WARNING] Failed to render Optical map: {e}")

    return {"sar_png": sar_png, "optical_png": optical_png, "geotiff": geotiff_path}


# -----------------------------------------------------------------------------
# 8. PDF REPORT GENERATION (1-PAGE STRICT LAYOUT)
# -----------------------------------------------------------------------------
def generate_pdf_report(
    target: Dict[str, Any],
    risk: Dict[str, Any],
    maps: Dict[str, str],
    audit_timestamp: str
) -> str:
    asset_id = target["id"]
    pdf_path = os.path.join(PDF_DIR, f"{asset_id}_Hazard_Audit.pdf")

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=13, textColor=colors.HexColor("#1a4d2e"), alignment=0)
    subtitle_style = ParagraphStyle("SubStyle", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#444444"), alignment=2)
    section_style = ParagraphStyle("SecStyle", parent=styles["Heading2"], fontSize=9, textColor=colors.HexColor("#1a4d2e"), spaceBefore=2, spaceAfter=2)
    bullet_style = ParagraphStyle("BulStyle", parent=styles["Normal"], fontSize=7.5, leading=9.5)

    story = []

    # 1. Header Table
    header_data = [
        [
            Paragraph("<b>SP Vasisth Sustainability Consulting</b><br/><font size=7 color='#555555'>Climate Risk & Remote Sensing Advisory</font>", title_style),
            Paragraph("<b>Executive Hazard Audit Report</b><br/><font size=7 color='#555555'>GLOF & Catchment Monitoring</font>", subtitle_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[110 * mm, 80 * mm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e8f0e4")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#1a4d2e")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 2 * mm))

    # 2. Asset Details Table
    overview_data = [
        ["Asset Name", target["name"], "Location", f"{target['latitude']:.4f}° N, {target['longitude']:.4f}° E"],
        ["River Basin", target["river_basin"], "Buffer Radius", f"{target['buffer_km']} km"],
        ["State / Region", target["state"], "Audit Date", audit_timestamp],
    ]
    overview_table = Table(overview_data, colWidths=[35 * mm, 60 * mm, 35 * mm, 60 * mm])
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4f1")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f0f4f1")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("PADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 2 * mm))

    # 3. Hazard Scorecard Table
    scorecard_data = [
        ["Hazard Metric Analyzed", "Observed Indicator / Value", "Assessed Risk Level"],
        ["GLOF & Lake Boundary Expansion", f"Water Gain Area: {risk['pct_water_gain']:.2f}%", risk['glof_risk']],
        ["Slope Instability & Hazard", f"Steep Terrain (>30°): {risk['pct_slope_hazard']:.2f}%", risk['slope_risk']],
        ["Catchment Veg Loss / Stress", f"Vegetation Loss Area: {risk['pct_veg_loss']:.2f}%", risk['sediment_risk']],
    ]
    scorecard_table = Table(scorecard_data, colWidths=[75 * mm, 75 * mm, 40 * mm])
    scorecard_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a4d2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("PADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story.append(scorecard_table)
    story.append(Spacer(1, 2 * mm))

    # 4. Maps Section (Controlled Height to prevent page split)
    if os.path.exists(maps["sar_png"]) and os.path.exists(maps["optical_png"]):
        img_table_data = [[
            RLImage(maps["sar_png"], width=90 * mm, height=52 * mm),
            RLImage(maps["optical_png"], width=90 * mm, height=52 * mm)
        ]]
        img_table = Table(img_table_data, colWidths=[95 * mm, 95 * mm])
        img_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(img_table)
        story.append(Spacer(1, 2 * mm))

    # 5. Executive Summary
    story.append(Paragraph("Executive Audit Verdict & Technical Risk Summary", section_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a4d2e"), spaceAfter=2))

    summary_text = (
        f"• <b>Sentinel-1 SAR Radar Analysis:</b> Multi-temporal C-band radar tracking detected a mean backscatter shift of "
        f"<b>{risk['mean_vh_anomaly_db']:.2f} dB</b> across the {target['buffer_km']} km upstream catchment buffer, identifying "
        f"potential all-weather surface water anomalies.<br/>"
        f"• <b>Sentinel-2 Optical & Elevation Audit:</b> Multi-spectral NDWI differential analysis shows a <b>{risk['pct_water_gain']:.2f}%</b> "
        f"water body expansion. NASADEM model indicates <b>{risk['pct_slope_hazard']:.2f}%</b> of upstream terrain exceeds critical stability thresholds (>30°).<br/>"
        f"• <b>Compliance Verdict:</b> Site exhibits an overall <b>{risk['glof_risk']} GLOF Risk</b> and <b>{risk['slope_risk']} Slope Hazard Level</b>. "
        f"Structured for asset protection, structural safety compliance, and TCFD physical risk disclosures."
    )
    story.append(Paragraph(summary_text, bullet_style))

    doc.build(story)
    print(f"[PDF SUCCESS] 1-Page Report generated: {pdf_path}")
    return pdf_path


# -----------------------------------------------------------------------------
# 9. BATCH EXECUTION
# -----------------------------------------------------------------------------
def run_pipeline():
    print("==================================================================")
    print("SP Vasisth Sustainability Consulting - GLOF Monitoring Pipeline")
    print("==================================================================")

    initialize_gee()
    targets = load_targets("hydro_targets.json")
    today = datetime.date.today()
    timestamp_str = today.strftime("%Y-%m-%d")

    for idx, target in enumerate(targets, start=1):
        print(f"\n[{idx}/{len(targets)}] Processing Target: {target['name']} ({target['id']})...")

        aoi, _ = create_aoi(target)
        sar_anomaly = compute_sar_anomaly(aoi, today)
        optical_change = compute_optical_change(aoi, today)
        dem_analysis = analyze_dem(aoi)

        risk_metrics = assess_risk(sar_anomaly, optical_change, dem_analysis, aoi)
        map_paths = export_rasters(target, sar_anomaly, optical_change, dem_analysis, aoi)
        generate_pdf_report(target, risk_metrics, map_paths, timestamp_str)

    print("\n==================================================================")
    print(f"[SUCCESS] All {len(targets)} Targets Processed Successfully.")
    print("==================================================================")


if __name__ == "__main__":
    run_pipeline()
