from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform as transform_coords


OUTPUT_DIR = Path("outputs")
INSAR_DIR = Path("data/insar")
AOI_BBOX_WGS84 = [126.95, 35.72, 127.25, 35.95]
MATCH_RADIUS_DEGREES = 0.03
INSAR_GRID_MAX_POINTS = 260
INSAR_GRID_STEP_PIXELS = 45
INSAR_GRID_MIN_PERCENTILE = 72


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def normalize(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    min_value = values.min()
    max_value = values.max()
    if max_value == min_value:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return (values - min_value) / (max_value - min_value)


def risk_level(score: float) -> str:
    if score >= 85:
        return "매우 높음"
    if score >= 55:
        return "높음"
    if score >= 35:
        return "주의"
    return "낮음"


def find_insar_raster() -> Path | None:
    candidates = []
    for pattern in ("*vert_disp*.tif", "*vert_disp*.tiff", "*vert_disp*.vrt"):
        candidates.extend(sorted(INSAR_DIR.glob(pattern)))
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]

    fallback = []
    for pattern in ("*los_disp*.tif", "*los_disp*.tiff", "*.tif", "*.tiff", "*.vrt"):
        fallback.extend(sorted(INSAR_DIR.glob(pattern)))
    return sorted(fallback, key=lambda path: path.stat().st_mtime, reverse=True)[0] if fallback else None


def nearest_insar(row: pd.Series, insar: pd.DataFrame) -> dict:
    if insar.empty:
        return {
            "insar_latitude": np.nan,
            "insar_longitude": np.nan,
            "insar_distance_deg": np.nan,
            "insar_displacement": 0.0,
            "insar_abs_displacement": 0.0,
            "insar_direction": "InSAR 후보 없음",
            "insar_matched": False,
        }

    lat_diff = insar["latitude"] - row["latitude"]
    lon_diff = insar["longitude"] - row["longitude"]
    distance = np.sqrt(lat_diff**2 + lon_diff**2)
    nearest_idx = distance.idxmin()
    nearest = insar.loc[nearest_idx]
    nearest_distance = float(distance.loc[nearest_idx])

    return {
        "insar_latitude": float(nearest["latitude"]),
        "insar_longitude": float(nearest["longitude"]),
        "insar_distance_deg": nearest_distance,
        "insar_displacement": float(nearest.get("displacement", 0)),
        "insar_abs_displacement": float(nearest.get("absolute_displacement", 0)),
        "insar_direction": nearest.get("displacement_direction", "변위 방향 확인 필요"),
        "insar_matched": bool(nearest_distance <= MATCH_RADIUS_DEGREES),
    }


def sample_insar_raster(points: pd.DataFrame) -> pd.DataFrame:
    raster_path = find_insar_raster()
    if raster_path is None or points.empty:
        return pd.DataFrame(
            {
                "sampled_insar_displacement": [0.0] * len(points),
                "sampled_insar_abs_displacement": [0.0] * len(points),
                "sampled_insar_available": [False] * len(points),
                "sampled_insar_source": [""] * len(points),
            }
        )

    sampled_values = []
    available = []

    with rasterio.open(raster_path) as src:
        xs, ys = transform_coords(
            "EPSG:4326",
            src.crs,
            points["longitude"].to_list(),
            points["latitude"].to_list(),
        )

        band = src.read(1)
        for x, y in zip(xs, ys):
            try:
                row, col = src.index(x, y)
                if row < 0 or col < 0 or row >= src.height or col >= src.width:
                    sampled_values.append(0.0)
                    available.append(False)
                    continue
                value = float(band[row, col])
                if src.nodata is not None and value == src.nodata:
                    sampled_values.append(0.0)
                    available.append(False)
                elif not np.isfinite(value):
                    sampled_values.append(0.0)
                    available.append(False)
                else:
                    sampled_values.append(value)
                    available.append(True)
            except Exception:
                sampled_values.append(0.0)
                available.append(False)

    return pd.DataFrame(
        {
            "sampled_insar_displacement": sampled_values,
            "sampled_insar_abs_displacement": np.abs(sampled_values),
            "sampled_insar_available": available,
            "sampled_insar_source": [str(raster_path)] * len(points),
        }
    )


def build_insar_grid_points() -> pd.DataFrame:
    raster_path = find_insar_raster()
    if raster_path is None:
        return pd.DataFrame()

    min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84
    records = []

    with rasterio.open(raster_path) as src:
        band = src.read(1).astype("float32")
        if src.nodata is not None:
            band = np.where(band == src.nodata, np.nan, band)

        rows = np.arange(0, src.height, INSAR_GRID_STEP_PIXELS)
        cols = np.arange(0, src.width, INSAR_GRID_STEP_PIXELS)
        sample_rows, sample_cols = np.meshgrid(rows, cols, indexing="ij")
        sample_rows = sample_rows.ravel()
        sample_cols = sample_cols.ravel()
        values = band[sample_rows, sample_cols]
        valid = np.isfinite(values)
        if not valid.any():
            return pd.DataFrame()

        sample_rows = sample_rows[valid]
        sample_cols = sample_cols[valid]
        values = values[valid]
        xs, ys = rasterio.transform.xy(src.transform, sample_rows, sample_cols)
        lon_values, lat_values = transform_coords(src.crs, "EPSG:4326", xs, ys)

        grid = pd.DataFrame(
            {
                "latitude": lat_values,
                "longitude": lon_values,
                "effective_insar_displacement": values.astype(float),
            }
        )
        grid = grid[
            (grid["longitude"] >= min_lon)
            & (grid["longitude"] <= max_lon)
            & (grid["latitude"] >= min_lat)
            & (grid["latitude"] <= max_lat)
        ].copy()
        if grid.empty:
            return pd.DataFrame()

        grid["effective_insar_abs_displacement"] = grid[
            "effective_insar_displacement"
        ].abs()
        threshold = float(
            np.nanpercentile(
                grid["effective_insar_abs_displacement"], INSAR_GRID_MIN_PERCENTILE
            )
        )
        grid = grid[grid["effective_insar_abs_displacement"] >= threshold].copy()
        grid = grid.sort_values(
            "effective_insar_abs_displacement", ascending=False
        ).head(INSAR_GRID_MAX_POINTS)

        if grid.empty:
            return pd.DataFrame()

        grid["insar_norm"] = normalize(grid["effective_insar_abs_displacement"])
        grid["source_type"] = "InSAR 산지/전지역 격자"
        grid["anomaly_score"] = 0.0
        grid["optical_component"] = 0.0
        grid["surface_component"] = 0.0
        grid["insar_component"] = 25 * grid["insar_norm"]
        grid["fusion_bonus"] = 0.0
        grid["composite_risk_score"] = (25 + 45 * grid["insar_norm"]).clip(0, 80)
        grid["composite_risk_level"] = grid["composite_risk_score"].apply(risk_level)
        grid["composite_reason"] = (
            "광학영상 이상 후보가 적은 산지/비도심 구간을 보완하기 위해 "
            "InSAR 변위 래스터를 격자로 샘플링한 후보입니다."
        )
        grid["mean_brightness"] = 0.0
        grid["brightness_std"] = 0.0
        grid["mean_reconstruction_error"] = 0.0
        grid["total_edge_strength"] = 0.0
        grid["insar_matched"] = False
        grid["insar_distance_deg"] = np.nan
        grid["sampled_insar_displacement"] = grid["effective_insar_displacement"]
        grid["sampled_insar_abs_displacement"] = grid[
            "effective_insar_abs_displacement"
        ]
        grid["sampled_insar_available"] = True
        grid["insar_displacement"] = grid["effective_insar_displacement"]
        grid["insar_abs_displacement"] = grid["effective_insar_abs_displacement"]
        grid["insar_direction"] = np.where(
            grid["effective_insar_displacement"] < 0,
            "침하 또는 하강 방향 변위",
            "융기 또는 상승 방향 변위",
        )
        grid["instability_type"] = "InSAR 기반 산지/비도심 변위 후보"
        grid["instability_reason"] = (
            "광학영상만으로는 산림·그늘·식생 때문에 표면 이상이 약하게 보일 수 있어, "
            "위성 레이더 변위값을 직접 반영했습니다."
        )
        grid["sampled_insar_source"] = str(raster_path)
        records = grid

    return records


def build_reason(row: pd.Series) -> str:
    reasons = []

    if row["fusion_bonus"] > 0:
        reasons.append("광학영상 이상과 InSAR 변위가 가까운 위치에서 함께 나타남")
    if row["optical_component"] >= 25:
        reasons.append("광학영상 이상 점수가 높음")
    if row["surface_component"] >= 12:
        reasons.append("밝기·경계·복원오차 기반 표면 변화 신호가 큼")
    if row["insar_component"] >= 18:
        reasons.append("해당 지점의 InSAR 변위값이 상대적으로 큼")
    if not bool(row["effective_insar_available"]):
        reasons.append("해당 지점에서 사용할 수 있는 InSAR 샘플이 없어 광학 근거 중심")

    return ", ".join(reasons) if reasons else "복합 지표가 낮거나 단일 근거만 확인됨"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    optical = read_csv(OUTPUT_DIR / "detected_anomalies.csv")
    insar = read_csv(OUTPUT_DIR / "insar_hotspots.csv")

    outputs = []

    if not optical.empty:
        optical = optical.copy()
        optical["source_type"] = "광학+InSAR 복합 후보"
        optical["optical_norm"] = normalize(optical["anomaly_score"])
        optical["brightness_norm"] = normalize(optical.get("mean_brightness", 0))
        optical["edge_norm"] = normalize(optical.get("total_edge_strength", 0))
        optical["error_norm"] = normalize(optical.get("mean_reconstruction_error", 0))
        optical["surface_norm"] = (
            0.4 * optical["brightness_norm"]
            + 0.3 * optical["edge_norm"]
            + 0.3 * optical["error_norm"]
        )

        match_df = pd.DataFrame([nearest_insar(row, insar) for _, row in optical.iterrows()])
        sampled_insar = sample_insar_raster(optical)
        combined = pd.concat(
            [optical.reset_index(drop=True), match_df, sampled_insar], axis=1
        )

        combined["effective_insar_abs_displacement"] = np.maximum(
            combined["insar_abs_displacement"],
            combined["sampled_insar_abs_displacement"],
        )
        combined["effective_insar_displacement"] = np.where(
            combined["insar_abs_displacement"]
            >= combined["sampled_insar_abs_displacement"],
            combined["insar_displacement"],
            combined["sampled_insar_displacement"],
        )
        combined["effective_insar_available"] = (
            combined["insar_matched"] | combined["sampled_insar_available"]
        )
        combined["insar_norm_raw"] = (
            normalize(combined["effective_insar_abs_displacement"])
            if combined["effective_insar_abs_displacement"].max() > 0
            else 0.0
        )
        combined["insar_norm"] = np.where(
            combined["effective_insar_available"], combined["insar_norm_raw"], 0.0
        )

        combined["optical_component"] = combined["optical_norm"] * 35
        combined["surface_component"] = combined["surface_norm"] * 20
        combined["insar_component"] = combined["insar_norm"] * 25
        combined["fusion_bonus"] = np.where(
            combined["insar_matched"],
            20 * np.minimum(combined["optical_norm"], combined["insar_norm"]),
            0,
        )
        combined["composite_risk_score"] = (
            combined["optical_component"]
            + combined["surface_component"]
            + combined["insar_component"]
            + combined["fusion_bonus"]
        ).clip(0, 100)
        combined["composite_risk_level"] = combined["composite_risk_score"].apply(
            risk_level
        )
        combined["composite_reason"] = combined.apply(build_reason, axis=1)
        outputs.append(combined)

    insar_grid = build_insar_grid_points()
    if not insar_grid.empty:
        outputs.append(insar_grid)

    columns = [
        "source_type",
        "latitude",
        "longitude",
        "composite_risk_score",
        "composite_risk_level",
        "composite_reason",
        "anomaly_score",
        "optical_component",
        "surface_component",
        "insar_component",
        "fusion_bonus",
        "mean_brightness",
        "brightness_std",
        "mean_reconstruction_error",
        "total_edge_strength",
        "insar_matched",
        "insar_distance_deg",
        "effective_insar_displacement",
        "effective_insar_abs_displacement",
        "sampled_insar_displacement",
        "sampled_insar_abs_displacement",
        "sampled_insar_available",
        "insar_displacement",
        "insar_abs_displacement",
        "insar_direction",
        "instability_type",
        "instability_reason",
    ]

    if outputs:
        output = pd.concat(outputs, ignore_index=True, sort=False)
        for column in columns:
            if column not in output.columns:
                output[column] = np.nan
        output = output[columns].sort_values(
            "composite_risk_score", ascending=False
        )
    else:
        output = pd.DataFrame(columns=columns)

    output.to_csv(
        OUTPUT_DIR / "composite_ground_risk.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Composite risk rows: {len(output)}")
    print(f"InSAR terrain grid rows: {len(insar_grid)}")
    print(f"Saved: {OUTPUT_DIR / 'composite_ground_risk.csv'}")


if __name__ == "__main__":
    main()
