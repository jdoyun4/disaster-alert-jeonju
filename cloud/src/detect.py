from pathlib import Path
import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import torch
from rasterio.warp import transform

from train import AutoEncoder, TILE_SIZE


def iter_tiles(image: np.ndarray, tile_size: int = TILE_SIZE):
    height, width = image.shape

    for row in range(0, height - tile_size + 1, tile_size):
        for col in range(0, width - tile_size + 1, tile_size):
            tile = image[row : row + tile_size, col : col + tile_size]
            yield row, col, tile


def normalize_band(band: np.ndarray) -> np.ndarray:
    band = band.astype(np.float32)
    valid = np.isfinite(band)

    if not valid.any():
        return np.zeros_like(band, dtype=np.float32)

    min_value = band[valid].min()
    max_value = band[valid].max()

    if max_value == min_value:
        return np.zeros_like(band, dtype=np.float32)

    normalized = (band - min_value) / (max_value - min_value)
    normalized[~valid] = 0
    return normalized


def save_heatmap(records: list[dict], output_path: Path) -> None:
    rows = sorted({record["tile_row"] for record in records})
    cols = sorted({record["tile_col"] for record in records})
    row_index = {value: index for index, value in enumerate(rows)}
    col_index = {value: index for index, value in enumerate(cols)}

    heatmap = np.zeros((len(rows), len(cols)), dtype=np.float32)
    for record in records:
        heatmap[row_index[record["tile_row"]], col_index[record["tile_col"]]] = record[
            "anomaly_score"
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(7, 6))
    plt.imshow(heatmap, cmap="inferno")
    plt.colorbar(label="Anomaly score")
    plt.title("Tile anomaly heatmap")
    plt.xlabel("Tile column")
    plt.ylabel("Tile row")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def classify_instability(score: float, q75: float, q90: float, q97: float) -> tuple[str, str]:
    if score >= q97:
        return (
            "매우 높음",
            "주변 타일보다 반사 특성이 크게 달라 지형 변화, 인공 구조물, 그림자, 수계 경계 같은 원인 확인이 필요합니다.",
        )

    if score >= q90:
        return (
            "높음",
            "정상 패턴과 차이가 큰 편이라 QGIS나 지도에서 실제 지형을 확인하는 것이 좋습니다.",
        )

    if score >= q75:
        return (
            "주의",
            "약한 이상 신호가 있어 주변 지역과 비교 확인이 필요합니다.",
        )

    return (
        "낮음",
        "현재 모델 기준으로는 주변 타일과 큰 차이가 적습니다.",
    )


def infer_instability_type(
    tile: np.ndarray, reconstruction: np.ndarray, score: float
) -> tuple[str, str, dict]:
    tile_mean = float(np.mean(tile))
    tile_std = float(np.std(tile))
    recon_mean = float(np.mean(reconstruction))
    mean_delta = tile_mean - recon_mean
    error = np.abs(tile - reconstruction)
    error_mean = float(np.mean(error))
    error_std = float(np.std(error))
    error_threshold = float(np.percentile(error, 90))
    high_error_ratio = float(np.mean(error >= error_threshold))
    vertical_edge = float(np.mean(np.abs(np.diff(tile, axis=1))))
    horizontal_edge = float(np.mean(np.abs(np.diff(tile, axis=0))))
    edge_strength = vertical_edge + horizontal_edge
    edge_direction = (
        "세로 방향 경계가 더 강합니다"
        if vertical_edge > horizontal_edge * 1.2
        else "가로 방향 경계가 더 강합니다"
        if horizontal_edge > vertical_edge * 1.2
        else "여러 방향의 경계가 섞여 있습니다"
    )
    center_error = float(np.mean(error[16:48, 16:48]))
    border_error = float(
        np.mean(
            np.concatenate(
                [
                    error[:16, :].ravel(),
                    error[48:, :].ravel(),
                    error[:, :16].ravel(),
                    error[:, 48:].ravel(),
                ]
            )
        )
    )
    error_location = (
        "오차가 타일 중심부에 집중되어 국소적인 표면 변화 가능성이 큽니다."
        if center_error > border_error * 1.15
        else "오차가 가장자리 쪽에 많아 지형/토지피복 경계일 가능성이 있습니다."
        if border_error > center_error * 1.15
        else "오차가 타일 전반에 퍼져 있어 넓은 면적의 표면 차이 가능성이 있습니다."
    )

    if edge_strength >= 0.08 and tile_std >= 0.16:
        instability_type = (
            "경계/급변 패턴",
            f"밝기 변화가 큰 경계가 포함되어 절개지, 도로 경계, 하천 경계, 건물 밀집 경계 가능성을 확인해야 합니다. {edge_direction}. {error_location}",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    if mean_delta >= 0.08 and tile_std < 0.12:
        instability_type = (
            "넓은 밝은 노출면 가능성",
            f"타일 전체가 주변보다 밝게 반사되어 나지, 마른 토양, 콘크리트, 암반 노출 같은 표면 변화 가능성이 있습니다. {error_location}",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    if mean_delta >= 0.05:
        instability_type = (
            "국소 밝은 반사체 가능성",
            f"일부 영역이 주변보다 밝게 나타나 건물 지붕, 도로, 공사장 일부, 노출 토양 가능성을 확인해야 합니다. 고오차 픽셀 비율은 약 {high_error_ratio:.0%}입니다. {error_location}",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    if mean_delta <= -0.08 and tile_std < 0.12:
        instability_type = (
            "넓은 어두운 저반사면 가능성",
            f"타일 전체가 주변보다 어둡게 나타나 물, 습윤 지표, 산지 음영, 그림자 가능성을 확인해야 합니다. {error_location}",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    if mean_delta <= -0.05:
        instability_type = (
            "국소 어두운 음영/수계 가능성",
            f"일부 영역이 주변보다 어둡게 나타나 그림자, 수계, 습윤 지표, 급경사 음영 가능성이 있습니다. {error_location}",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    if tile_std >= 0.14 and error_std >= error_mean:
        instability_type = (
            "혼합 지형 패턴",
            f"한 타일 안에서 여러 표면 특성이 섞여 있어 농경지 경계, 건물-도로 혼합, 하천 주변부 같은 토지피복 변화 가능성이 있습니다. {edge_direction}.",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    if edge_strength >= 0.05:
        instability_type = (
            "약한 선형 경계 패턴",
            f"강하지는 않지만 선형 밝기 변화가 보여 도로, 수로, 필지 경계, 지형 사면 경계를 확인할 필요가 있습니다. {edge_direction}.",
        )
        return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))

    instability_type = (
        "비정상 반사 패턴",
        f"학습된 주변 패턴과 복원 차이가 커서 영상상 이상 후보로 분류되었습니다. 평균 밝기 차이는 {mean_delta:+.3f}, 대비는 {tile_std:.3f}입니다.",
    )
    return (*instability_type, build_metrics(tile_mean, tile_std, recon_mean, mean_delta, error_mean, error_std, high_error_ratio, vertical_edge, horizontal_edge, edge_strength, center_error, border_error))


def build_metrics(
    tile_mean: float,
    tile_std: float,
    recon_mean: float,
    mean_delta: float,
    error_mean: float,
    error_std: float,
    high_error_ratio: float,
    vertical_edge: float,
    horizontal_edge: float,
    edge_strength: float,
    center_error: float,
    border_error: float,
) -> dict:
    return {
        "mean_brightness": tile_mean,
        "brightness_std": tile_std,
        "reconstruction_mean": recon_mean,
        "brightness_delta": mean_delta,
        "mean_reconstruction_error": error_mean,
        "error_std": error_std,
        "high_error_pixel_ratio": high_error_ratio,
        "vertical_edge_strength": vertical_edge,
        "horizontal_edge_strength": horizontal_edge,
        "total_edge_strength": edge_strength,
        "center_error": center_error,
        "border_error": border_error,
        "center_border_error_ratio": center_error / border_error
        if border_error != 0
        else 0,
    }


def main() -> None:
    raw_dir = Path("data/raw")
    candidates = (
        sorted(raw_dir.glob("sentinel2_active_sample.tif"))
        + sorted(raw_dir.glob("sentinel2*.tif"))
        + sorted(raw_dir.glob("*.tif"))
        + sorted(raw_dir.glob("*.tiff"))
    )
    model_path = Path("models/autoencoder.pt")

    if not candidates:
        print("No GeoTIFF file found in data/raw.")
        return

    if not model_path.exists():
        print("No trained model found at models/autoencoder.pt.")
        print("Run src/train.py first.")
        return

    source_path = candidates[0]
    with rasterio.open(source_path) as src:
        image = normalize_band(src.read(1))
        raster_transform = src.transform
        crs = src.crs

    model = AutoEncoder()
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    model.eval()

    records = []
    with torch.no_grad():
        for tile_row, tile_col, tile in iter_tiles(image):
            x = torch.from_numpy(tile.reshape(1, -1).astype(np.float32))
            reconstruction = model(x).numpy().reshape(TILE_SIZE, TILE_SIZE)
            anomaly_score = float(np.mean((tile - reconstruction) ** 2))
            instability_type, instability_reason, metrics = infer_instability_type(
                tile, reconstruction, anomaly_score
            )

            center_row = tile_row + TILE_SIZE / 2
            center_col = tile_col + TILE_SIZE / 2
            x_coord, y_coord = rasterio.transform.xy(
                raster_transform, center_row, center_col
            )
            lon_values, lat_values = transform(crs, "EPSG:4326", [x_coord], [y_coord])
            lon = lon_values[0]
            lat = lat_values[0]

            records.append(
                {
                    "source": str(source_path),
                    "tile_row": tile_row,
                    "tile_col": tile_col,
                    "latitude": lat,
                    "longitude": lon,
                    "anomaly_score": anomaly_score,
                    "instability_type": instability_type,
                    "instability_reason": instability_reason,
                    **metrics,
                }
            )

    scores = np.array([record["anomaly_score"] for record in records])
    q75 = float(np.percentile(scores, 75))
    threshold = float(np.percentile(scores, 90))
    q97 = float(np.percentile(scores, 97))

    for record in records:
        level, description = classify_instability(
            record["anomaly_score"], q75, threshold, q97
        )
        record["is_anomaly"] = record["anomaly_score"] >= threshold
        record["instability_level"] = level
        record["instability_description"] = description

    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results_path = output_dir / "anomaly_scores.csv"
    anomaly_results_path = output_dir / "detected_anomalies.csv"
    heatmap_path = output_dir / "anomaly_heatmap.png"

    results = pd.DataFrame(records).sort_values("anomaly_score", ascending=False)
    results.to_csv(all_results_path, index=False, encoding="utf-8-sig")
    results[results["is_anomaly"]].to_csv(
        anomaly_results_path, index=False, encoding="utf-8-sig"
    )
    save_heatmap(records, heatmap_path)

    print(f"Source: {source_path}")
    print(f"CRS: {crs}")
    print(f"Tiles scored: {len(records)}")
    print(f"Anomaly threshold: {threshold:.6f}")
    print(f"Detected anomalies: {int(results['is_anomaly'].sum())}")
    print(f"Saved: {all_results_path}")
    print(f"Saved: {anomaly_results_path}")
    print(f"Saved: {heatmap_path}")


if __name__ == "__main__":
    main()
