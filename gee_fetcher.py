import ee

# Earth Engine Initialize karein
try:
    ee.Initialize()
except Exception as e:
    # Service account key se authenticate karein agar local/server par hain
    # ee.Initialize(ee.ServiceAccountCredentials('YOUR_SERVICE_ACCOUNT_EMAIL', 'path/to/key.json'))
    print(f"GEE Initialization Info: {e}")

def fetch_satellite_metrics(lat, lon, date_start="2026-08-01", date_end="2026-09-10", buffer_km=5):
    """
    Sentinel-2 satellite imagery se water body area calculate karta hai.
    """
    point = ee.Geometry.Point([lon, lat])
    region = point.buffer(buffer_km * 1000)

    # Sentinel-2 Surface Reflectance Collection
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(date_start, date_end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .sort("system:time_start", False)
    )

    image = collection.first()

    # NDWI (Normalized Difference Water Index) = (Green - NIR) / (Green + NIR)
    ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')
    water_mask = ndwi.gt(0.2) # Threshold > 0.2 indicates water

    water_area = water_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=10,
        maxPixels=1e9
    )

    area_sq_km = ee.Number(water_area.get('NDWI')).divide(1e6).getInfo()
    img_date = image.date().format('YYYY-MM-dd').getInfo()

    return {
        "date": img_date,
        "lake_area_sq_km": round(area_sq_km, 3),
        "status": "HIGH RISK" if area_sq_km > 1.2 else "SAFE"
    }
