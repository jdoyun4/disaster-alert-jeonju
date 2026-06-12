from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform as transform_coords

from spatial_filter import contains_jeonju


DEM_TILE_DIR = Path("data/dem/tiles")
OUTPUT_PATH = Path("outputs/lowland_flood_risk.csv")
AOI_BBOX_WGS84 = [126.99, 35.72, 127.24, 35.91]
GRID_STEP_PIXELS = 28
LOCAL_RADIUS_PIXELS = 24
MAX_POINTS = 220


def normalize(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype="float64")
    finite = np.isfinite(values)
    result = np.zeros_like(values)
    if not finite.any():
        return result
    low, high = np.nanpercentile(values[finite], [2, 98])
    if high <= low:
        return result
    result[finite] = np.clip((values[finite] - low) / (high - low), 0, 1)
    return result


def local_mean(elevation: np.ndarray, row: int, col: int) -> float:
    window = elevation[
        max(0, row - LOCAL_RADIUS_PIXELS) : row + LOCAL_RADIUS_PIXELS + 1,
        max(0, col - LOCAL_RADIUS_PIXELS) : col + LOCAL_RADIUS_PIXELS + 1,
    ]
    return float(np.nanmean(window)) if np.isfinite(window).any() else float("nan")


def evidence_level(row: pd.Series) -> tuple[str, int]:
    evidence = 0
    evidence += int(row["elevation_m"] <= row["very_low_threshold_m"])
    evidence += int(row["relative_depression_m"] >= 2.0)
    evidence += int(row["slope_proxy_m"] <= 8.0)
    if evidence == 3 and row["relative_depression_m"] >= 4.0:
        return "매우 높음", evidence
    if evidence >= 2:
        return "높음", evidence
    if evidence == 1:
        return "주의", evidence
    return "낮음", evidence


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tiles = [path for pattern in ("*.tif", "*.tiff") for path in DEM_TILE_DIR.glob(pattern)]
    if not tiles:
        pd.DataFrame().to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        print("No DEM tiles found.")
        return

    min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84
    tile_data = []
    valid_parts = []
    for path in sorted(tiles):
        with rasterio.open(path) as source:
            elevation = source.read(1).astype("float32")
            if source.nodata is not None:
                elevation[elevation == source.nodata] = np.nan
            tile_data.append((elevation, source.transform, source.crs))
            valid_parts.append(elevation[np.isfinite(elevation)])
    valid = np.concatenate([part for part in valid_parts if part.size])
    if not valid.size:
        pd.DataFrame().to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        return

    low_threshold = float(np.percentile(valid, 35))
    very_low_threshold = float(np.percentile(valid, 15))
    rows = []
    for elevation, transform, crs in tile_data:
        for row in range(0, elevation.shape[0], GRID_STEP_PIXELS):
            for col in range(0, elevation.shape[1], GRID_STEP_PIXELS):
                value = float(elevation[row, col])
                if not np.isfinite(value):
                    continue
                x, y = rasterio.transform.xy(transform, row, col)
                lon, lat = transform_coords(crs, "EPSG:4326", [x], [y])
                lon, lat = float(lon[0]), float(lat[0])
                if (
                    not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat)
                    or not contains_jeonju(lon, lat)
                ):
                    continue
                nearby = local_mean(elevation, row, col)
                local = elevation[
                    max(0, row - 1) : row + 2, max(0, col - 1) : col + 2
                ]
                rows.append(
                    {
                        "latitude": lat,
                        "longitude": lon,
                        "elevation_m": value,
                        "local_mean_elevation_m": nearby,
                        "relative_depression_m": max(0.0, nearby - value),
                        "slope_proxy_m": float(np.nanmax(local) - np.nanmin(local)),
                        "low_threshold_m": low_threshold,
                        "very_low_threshold_m": very_low_threshold,
                    }
                )

    data = pd.DataFrame(rows)
    if data.empty:
        data.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        return

    data["lowland_flood_score"] = 100 * (
        0.42 * (1 - normalize(data["elevation_m"]))
        + 0.25 * (1 - normalize(data["slope_proxy_m"]))
        + 0.33 * normalize(data["relative_depression_m"])
    )
    levels = data.apply(evidence_level, axis=1)
    data["lowland_flood_level"] = [value[0] for value in levels]
    data["terrain_evidence_count"] = [value[1] for value in levels]
    data["lowland_flood_reason"] = data.apply(
        lambda row: (
            f"고도 {row.elevation_m:.1f}m, 주변 평균보다 {row.relative_depression_m:.1f}m 낮음, "
            f"국지 고도차 {row.slope_proxy_m:.1f}m. 지형 근거 {int(row.terrain_evidence_count)}/3개. "
            "배수관·하천 수위·불투수면을 반영하지 않은 지형 기반 침수 후보입니다."
        ),
        axis=1,
    )
    data.sort_values(
        ["terrain_evidence_count", "lowland_flood_score"], ascending=False
    ).head(MAX_POINTS).to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Lowland flood risk rows: {min(len(data), MAX_POINTS)}")


if __name__ == "__main__":
    main()
