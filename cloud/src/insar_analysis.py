from pathlib import Path
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform

from spatial_filter import contains_jeonju

INSAR_DIR = Path("data/insar")
OUTPUT_DIR = Path("outputs")
HOTSPOT_PERCENTILE = 98.5
MAX_HOTSPOTS = 500
AOI_BBOX_WGS84 = [126.95, 35.72, 127.25, 35.95]


def find_insar_file() -> Path | None:
    candidates = []
    for pattern in ("*vert_disp*.tif", "*vert_disp*.tiff", "*vert_disp*.vrt"):
        candidates.extend(sorted(INSAR_DIR.glob(pattern)))
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]

    fallback = []
    for pattern in ("*los_disp*.tif", "*los_disp*.tiff", "*los_disp*.vrt"):
        fallback.extend(sorted(INSAR_DIR.glob(pattern)))
    fallback.extend(sorted(INSAR_DIR.glob("*.tif")))
    fallback.extend(sorted(INSAR_DIR.glob("*.tiff")))
    fallback.extend(sorted(INSAR_DIR.glob("*.vrt")))
    return sorted(fallback, key=lambda path: path.stat().st_mtime, reverse=True)[0] if fallback else None


def classify_displacement(value: float, threshold: float) -> tuple[str, str]:
    abs_value = abs(value)

    if abs_value >= threshold * 1.8:
        level = "매우 큼"
    elif abs_value >= threshold * 1.25:
        level = "큼"
    else:
        level = "주의"

    if value < 0:
        direction = "침하 또는 하강 변위"
    elif value > 0:
        direction = "융기 또는 상승 변위"
    else:
        direction = "변위 거의 없음"

    return level, direction


def save_empty_outputs(message: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "status": "no_insar_input",
                "message": message,
            }
        ]
    ).to_csv(OUTPUT_DIR / "insar_status.csv", index=False, encoding="utf-8-sig")

    for path in (
        OUTPUT_DIR / "insar_hotspots.csv",
        OUTPUT_DIR / "insar_displacement_summary.csv",
    ):
        pd.DataFrame().to_csv(path, index=False, encoding="utf-8-sig")


def save_displacement_preview(displacement: np.ndarray, output_path: Path) -> None:
    valid = np.isfinite(displacement)
    if not valid.any():
        return

    vmax = float(np.nanpercentile(np.abs(displacement[valid]), 98))
    vmax = vmax if vmax > 0 else 1

    plt.figure(figsize=(8, 7))
    plt.imshow(displacement, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    plt.colorbar(label="Displacement")
    plt.title("InSAR displacement preview")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INSAR_DIR.mkdir(parents=True, exist_ok=True)

    insar_path = find_insar_file()
    if insar_path is None:
        save_empty_outputs(
            "처리 완료된 InSAR 변위 GeoTIFF가 없습니다. data/insar 폴더에 HyP3 등에서 받은 변위 GeoTIFF를 넣으면 자동 분석됩니다."
        )
        print("No InSAR displacement GeoTIFF found in data/insar.")
        return

    with rasterio.open(insar_path) as src:
        displacement = src.read(1).astype(np.float32)
        nodata = src.nodata
        raster_transform = src.transform
        crs = src.crs

    if nodata is not None:
        displacement = np.where(displacement == nodata, np.nan, displacement)

    valid = np.isfinite(displacement)
    if not valid.any():
        save_empty_outputs("InSAR 파일은 찾았지만 유효한 변위 픽셀이 없습니다.")
        print("InSAR file has no valid pixels.")
        return

    values = displacement[valid]
    abs_values = np.abs(values)
    threshold = float(np.nanpercentile(abs_values, HOTSPOT_PERCENTILE))

    rows, cols = np.where(valid & (np.abs(displacement) >= threshold))
    records = []
    min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84

    for row, col in zip(rows, cols):
        value = float(displacement[row, col])
        x_coord, y_coord = rasterio.transform.xy(raster_transform, row, col)
        lon_values, lat_values = transform(crs, "EPSG:4326", [x_coord], [y_coord])
        lon = lon_values[0]
        lat = lat_values[0]
        if (
            not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat)
            or not contains_jeonju(lon, lat)
        ):
            continue
        level, direction = classify_displacement(value, threshold)

        records.append(
            {
                "source": str(insar_path),
                "row": int(row),
                "col": int(col),
                "latitude": lat,
                "longitude": lon,
                "displacement": value,
                "absolute_displacement": abs(value),
                "displacement_level": level,
                "displacement_direction": direction,
                "threshold_percentile": HOTSPOT_PERCENTILE,
                "hotspot_threshold": threshold,
            }
        )

    if records:
        hotspots = (
            pd.DataFrame(records)
            .sort_values("absolute_displacement", ascending=False)
            .head(MAX_HOTSPOTS)
        )
    else:
        hotspots = pd.DataFrame(
            columns=[
                "source",
                "row",
                "col",
                "latitude",
                "longitude",
                "displacement",
                "absolute_displacement",
                "displacement_level",
                "displacement_direction",
                "threshold_percentile",
                "hotspot_threshold",
            ]
        )
    hotspots.to_csv(OUTPUT_DIR / "insar_hotspots.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(
        [
            {
                "source": str(insar_path),
                "crs": str(crs),
                "valid_pixel_count": int(valid.sum()),
                "mean_displacement": float(np.nanmean(values)),
                "median_displacement": float(np.nanmedian(values)),
                "min_displacement": float(np.nanmin(values)),
                "max_displacement": float(np.nanmax(values)),
                "std_displacement": float(np.nanstd(values)),
                "hotspot_threshold": threshold,
                "hotspot_count": int(len(hotspots)),
                "max_hotspots_saved": MAX_HOTSPOTS,
            }
        ]
    )
    summary.to_csv(
        OUTPUT_DIR / "insar_displacement_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    if os.environ.get("SKIP_PLOTS") != "1":
        save_displacement_preview(displacement, OUTPUT_DIR / "insar_displacement_map.png")

    print(f"InSAR source: {insar_path}")
    print(f"Hotspot threshold: {threshold:.6f}")
    print(f"Hotspots: {len(hotspots)}")
    print("Saved: outputs/insar_hotspots.csv")
    print("Saved: outputs/insar_displacement_summary.csv")
    print("Saved: outputs/insar_displacement_map.png")


if __name__ == "__main__":
    main()
