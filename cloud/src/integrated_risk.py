from pathlib import Path

import pandas as pd

from spatial_filter import filter_jeonju


OUTPUT_DIR = Path("outputs")
OUTPUT_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"


def read_csv(name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(OUTPUT_DIR / name, encoding="utf-8-sig")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def level(score: float) -> str:
    return "매우 높음" if score >= 80 else "높음" if score >= 60 else "주의" if score >= 40 else "낮음"


def ground_rows(data: pd.DataFrame) -> pd.DataFrame:
    data = filter_jeonju(data)
    if data.empty:
        return pd.DataFrame()
    selected = data[pd.to_numeric(data.composite_risk_score, errors="coerce") >= 55]
    if selected.empty:
        selected = data.nlargest(10, "composite_risk_score")
    selected = selected.nlargest(20, "composite_risk_score")
    return pd.DataFrame(
        {
            "risk_type": "지반 약화",
            "latitude": selected.latitude,
            "longitude": selected.longitude,
            "integrated_score": selected.composite_risk_score,
            "integrated_level": selected.composite_risk_score.apply(level),
            "summary": selected.get("composite_reason", ""),
            "ground_risk_score": selected.composite_risk_score,
            "flood_risk_score": 0.0,
            "elevation_m": "",
            "relative_depression_m": "",
            "terrain_evidence_count": "",
            "insar_displacement_abs": selected.get("effective_insar_abs_displacement", 0),
            "optical_component": selected.get("optical_component", 0),
            "surface_component": selected.get("surface_component", 0),
            "insar_component": selected.get("insar_component", 0),
            "detail": selected.get("instability_reason", ""),
        }
    )


def flood_rows(data: pd.DataFrame) -> pd.DataFrame:
    data = filter_jeonju(data)
    if data.empty:
        return pd.DataFrame()
    selected = data[data.lowland_flood_level.isin(["매우 높음", "높음"])].copy()
    if selected.empty:
        selected = data.nlargest(12, "lowland_flood_score")
    selected = selected.sort_values(
        ["terrain_evidence_count", "lowland_flood_score"], ascending=False
    ).head(25)
    return pd.DataFrame(
        {
            "risk_type": "저지대 침수",
            "latitude": selected.latitude,
            "longitude": selected.longitude,
            "integrated_score": selected.lowland_flood_score,
            "integrated_level": selected.lowland_flood_level,
            "summary": selected.lowland_flood_reason,
            "ground_risk_score": 0.0,
            "flood_risk_score": selected.lowland_flood_score,
            "elevation_m": selected.elevation_m,
            "relative_depression_m": selected.relative_depression_m,
            "terrain_evidence_count": selected.terrain_evidence_count,
            "insar_displacement_abs": 0.0,
            "optical_component": 0.0,
            "surface_component": 0.0,
            "insar_component": 0.0,
            "detail": "DEM 기반 후보이며 배수시설·하천 수위·불투수면 자료는 아직 미반영입니다.",
        }
    )


def main() -> None:
    rows = [ground_rows(read_csv("composite_ground_risk.csv")), flood_rows(read_csv("lowland_flood_risk.csv"))]
    rows = [row for row in rows if not row.empty]
    output = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    output = filter_jeonju(output)
    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Integrated risk rows: {len(output)}")


if __name__ == "__main__":
    main()
