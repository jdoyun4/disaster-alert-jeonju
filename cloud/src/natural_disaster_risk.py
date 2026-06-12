from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT_DIR = Path("outputs")
INPUT_PATH = OUTPUT_DIR / "composite_ground_risk.csv"
OUTPUT_PATH = OUTPUT_DIR / "natural_disaster_vulnerability.csv"


def read_input() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def normalize(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    min_value = values.min()
    max_value = values.max()
    if max_value == min_value:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return (values - min_value) / (max_value - min_value)


def level(score: float) -> str:
    if score >= 80:
        return "매우 취약"
    if score >= 60:
        return "취약"
    if score >= 40:
        return "주의"
    return "낮음"


def dominant_hazard(row: pd.Series) -> str:
    scores = {
        "폭우 취약": float(row["heavy_rain_vulnerability"]),
        "산사태 취약": float(row["landslide_vulnerability"]),
        "지진 취약": float(row["earthquake_vulnerability"]),
    }
    return max(scores, key=scores.get)


def reason(row: pd.Series) -> str:
    parts = []
    if row["heavy_rain_vulnerability"] >= 60:
        parts.append("폭우 시 배수 불량·토사 유실에 민감할 수 있는 표면 변화 신호가 큼")
    if row["landslide_vulnerability"] >= 60:
        parts.append("산지/비도심 또는 경계 강도와 InSAR 변위가 커 사면 불안정 후보로 분류됨")
    if row["earthquake_vulnerability"] >= 60:
        parts.append("기존 지반 약화 점수와 변위값이 커 지진 흔들림에 취약할 가능성이 있음")
    if not parts:
        parts.append("현재 자료 기준으로는 재해 취약 신호가 상대적으로 낮음")
    return ", ".join(parts)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = read_input()

    if data.empty:
        pd.DataFrame().to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
        print("No composite ground risk data found.")
        return

    data = data.copy()
    source = data.get("source_type", "").astype(str)
    mountain_or_insar = source.str.contains("InSAR", na=False).astype(float)

    ground = normalize(data.get("composite_risk_score", 0))
    surface = normalize(data.get("surface_component", 0))
    optical = normalize(data.get("optical_component", 0))
    edge = normalize(data.get("total_edge_strength", 0))
    insar = normalize(data.get("effective_insar_abs_displacement", 0))
    reconstruction = normalize(data.get("mean_reconstruction_error", 0))

    data["heavy_rain_vulnerability"] = (
        100 * (0.35 * ground + 0.30 * surface + 0.20 * insar + 0.15 * reconstruction)
    ).clip(0, 100)
    data["landslide_vulnerability"] = (
        100 * (0.30 * ground + 0.30 * insar + 0.20 * edge + 0.20 * mountain_or_insar)
    ).clip(0, 100)
    data["earthquake_vulnerability"] = (
        100 * (0.45 * ground + 0.35 * insar + 0.10 * surface + 0.10 * optical)
    ).clip(0, 100)
    data["natural_disaster_vulnerability_score"] = (
        0.38 * data["heavy_rain_vulnerability"]
        + 0.37 * data["landslide_vulnerability"]
        + 0.25 * data["earthquake_vulnerability"]
    ).clip(0, 100)

    data["natural_disaster_level"] = data[
        "natural_disaster_vulnerability_score"
    ].apply(level)
    data["dominant_hazard"] = data.apply(dominant_hazard, axis=1)
    data["natural_disaster_reason"] = data.apply(reason, axis=1)

    columns = [
        "latitude",
        "longitude",
        "natural_disaster_vulnerability_score",
        "natural_disaster_level",
        "dominant_hazard",
        "heavy_rain_vulnerability",
        "landslide_vulnerability",
        "earthquake_vulnerability",
        "natural_disaster_reason",
        "composite_risk_score",
        "composite_risk_level",
        "source_type",
        "effective_insar_displacement",
        "effective_insar_abs_displacement",
        "optical_component",
        "surface_component",
        "insar_component",
        "fusion_bonus",
        "instability_type",
        "instability_reason",
    ]
    existing = [column for column in columns if column in data.columns]
    output = data[existing].sort_values(
        "natural_disaster_vulnerability_score", ascending=False
    )
    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"Natural disaster vulnerability rows: {len(output)}")
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
