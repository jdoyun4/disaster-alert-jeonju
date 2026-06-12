from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform as transform_coords
from rasterio.windows import from_bounds


DEM_TILE_DIR = Path("data/dem/tiles")
OUTPUT_DIR = Path("outputs")
OUTPUT_PATH = OUTPUT_DIR / "lowland_flood_risk.csv"
AOI_BBOX_WGS84 = [126.95, 35.72, 127.25, 35.95]
GRID_STEP_PIXELS = 28
LOCAL_RADIUS_PIXELS = 24
MAX_POINTS = 220


def normalize(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype="float64")
    finite = np.isfinite(values)
    result = np.zeros_like(values, dtype="float64")
    if not finite.any():
        return result
    min_value = float(np.nanmin(values[finite]))
    max_value = float(np.nanmax(values[finite]))
    if max_value == min_value:
        return result
    result[finite] = (values[finite] - min_value) / (max_value - min_value)
    return result


def level(score: float) -> str:
    if score >= 80:
        return "매우 높음"
    if score >= 60:
        return "높음"
    if score >= 40:
        return "주의"
    return "낮음"


def find_dem_tiles() -> list[Path]:
    tiles = []
    for pattern in ("*.tif", "*.tiff"):
        tiles.extend(sorted(DEM_TILE_DIR.glob(pattern)))
    return tiles


def local_mean(elevation: np.ndarray, row: int, col: int) -> float:
    r0 = max(0, row - LOCAL_RADIUS_PIXELS)
    r1 = min(elevation.shape[0], row + LOCAL_RADIUS_PIXELS + 1)
    c0 = max(0, col - LOCAL_RADIUS_PIXELS)
    c1 = min(elevation.shape[1], col + LOCAL_RADIUS_PIXELS + 1)
    window = elevation[r0:r1, c0:c1]
    if not np.isfinite(window).any():
        return float("nan")
    return float(np.nanmean(window))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tiles = find_dem_tiles()
    if not tiles:
        pd.DataFrame().to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        print("No DEM tiles found. Put GeoTIFF DEM files in data/dem/tiles.")
        return

    sources = [rasterio.open(path) for path in tiles]
    try:
        mosaic, transform = merge(sources)
        crs = sources[0].crs
        nodata = sources[0].nodata
    finally:
        for src in sources:
            src.close()

    elevation = mosaic[0].astype("float32")
    if nodata is not None:
        elevation = np.where(elevation == nodata, np.nan, elevation)

    min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84
    xs, ys = transform_coords(
        "EPSG:4326",
        crs,
        [min_lon, min_lon, max_lon, max_lon],
        [min_lat, max_lat, min_lat, max_lat],
    )
    window = from_bounds(min(xs), min(ys), max(xs), max(ys), transform)
    row_start = max(0, int(np.floor(window.row_off)))
    row_stop = min(elevation.shape[0], int(np.ceil(window.row_off + window.height)))
    col_start = max(0, int(np.floor(window.col_off)))
    col_stop = min(elevation.shape[1], int(np.ceil(window.col_off + window.width)))

    cropped = elevation[row_start:row_stop, col_start:col_stop]
    if cropped.size == 0 or not np.isfinite(cropped).any():
        pd.DataFrame().to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        print("DEM does not overlap the analysis area.")
        return

    valid_values = cropped[np.isfinite(cropped)]
    low_threshold = float(np.nanpercentile(valid_values, 35))
    very_low_threshold = float(np.nanpercentile(valid_values, 15))

    rows = []
    for row in range(row_start, row_stop, GRID_STEP_PIXELS):
        for col in range(col_start, col_stop, GRID_STEP_PIXELS):
            value = float(elevation[row, col])
            if not np.isfinite(value):
                continue
            x_coord, y_coord = rasterio.transform.xy(transform, row, col)
            lon_values, lat_values = transform_coords(crs, "EPSG:4326", [x_coord], [y_coord])
            lon = float(lon_values[0])
            lat = float(lat_values[0])
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue

            nearby_mean = local_mean(elevation, row, col)
            depression = max(0.0, nearby_mean - value) if np.isfinite(nearby_mean) else 0.0

            r0 = max(0, row - 1)
            r1 = min(elevation.shape[0], row + 2)
            c0 = max(0, col - 1)
            c1 = min(elevation.shape[1], col + 2)
            window_values = elevation[r0:r1, c0:c1]
            slope_proxy = float(np.nanmax(window_values) - np.nanmin(window_values))
            rows.append(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "elevation_m": value,
                    "local_mean_elevation_m": nearby_mean,
                    "relative_depression_m": depression,
                    "slope_proxy_m": slope_proxy,
                    "low_threshold_m": low_threshold,
                    "very_low_threshold_m": very_low_threshold,
                }
            )

    data = pd.DataFrame(rows)
    if data.empty:
        data.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        print("No DEM sample points found.")
        return

    elevation_low = 1 - normalize(data["elevation_m"].to_numpy())
    flatness = 1 - normalize(data["slope_proxy_m"].to_numpy())
    depression_norm = normalize(data["relative_depression_m"].to_numpy())
    very_low_bonus = (data["elevation_m"] <= very_low_threshold).astype(float).to_numpy()
    low_bonus = (data["elevation_m"] <= low_threshold).astype(float).to_numpy()

    data["lowland_flood_score"] = (
        100
        * (
            0.42 * elevation_low
            + 0.24 * flatness
            + 0.22 * depression_norm
            + 0.08 * low_bonus
            + 0.04 * very_low_bonus
        )
    ).clip(0, 100)
    data["lowland_flood_reason"] = data.apply(
        lambda row: (
            f"해당 지점 고도 {row['elevation_m']:.1f}m, 주변 평균 대비 "
            f"{row['relative_depression_m']:.1f}m 낮음. "
            "상대적으로 낮고 완만한 지형일수록 폭우 때 빗물이 모이거나 배수가 지연될 수 있습니다."
        ),
        axis=1,
    )

    output = data.sort_values("lowland_flood_score", ascending=False).head(MAX_POINTS)
    q85 = float(output["lowland_flood_score"].quantile(0.85))
    q60 = float(output["lowland_flood_score"].quantile(0.60))
    q30 = float(output["lowland_flood_score"].quantile(0.30))
    output["lowland_flood_level"] = output["lowland_flood_score"].apply(
        lambda score: (
            "매우 높음"
            if score >= q85
            else "높음"
            if score >= q60
            else "주의"
            if score >= q30
            else "낮음"
        )
    )
    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"Lowland flood risk rows: {len(output)}")
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
