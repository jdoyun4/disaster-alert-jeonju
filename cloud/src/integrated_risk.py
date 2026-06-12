from pathlib import Path

import pandas as pd


OUTPUT_DIR = Path("outputs")
GROUND_PATH = OUTPUT_DIR / "composite_ground_risk.csv"
FLOOD_PATH = OUTPUT_DIR / "lowland_flood_risk.csv"
OUTPUT_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def risk_level(score: float) -> str:
    if score >= 80:
        return "매우 높음"
    if score >= 60:
        return "높음"
    if score >= 40:
        return "주의"
    return "낮음"


def build_ground_rows(ground: pd.DataFrame) -> pd.DataFrame:
    if ground.empty:
        return pd.DataFrame()

    score = pd.to_numeric(ground["composite_risk_score"], errors="coerce").fillna(0)
    selected = ground[score >= 55].copy()
    if selected.empty:
        selected = ground.sort_values("composite_risk_score", ascending=False).head(10)
    selected = selected.sort_values("composite_risk_score", ascending=False).head(20)

    output = pd.DataFrame(
        {
            "risk_type": "지반 약화",
            "latitude": selected["latitude"],
            "longitude": selected["longitude"],
            "integrated_score": selected["composite_risk_score"],
            "integrated_level": selected["composite_risk_score"].apply(risk_level),
            "summary": selected.get("composite_reason", ""),
            "ground_risk_score": selected["composite_risk_score"],
            "flood_risk_score": 0.0,
            "elevation_m": "",
            "relative_depression_m": "",
            "insar_displacement_abs": selected.get(
                "effective_insar_abs_displacement", 0
            ),
            "optical_component": selected.get("optical_component", 0),
            "surface_component": selected.get("surface_component", 0),
            "insar_component": selected.get("insar_component", 0),
            "detail": selected.get("instability_reason", ""),
        }
    )
    return output


def build_flood_rows(flood: pd.DataFrame) -> pd.DataFrame:
    if flood.empty:
        return pd.DataFrame()

    score = pd.to_numeric(flood["lowland_flood_score"], errors="coerce").fillna(0)
    level = flood.get("lowland_flood_level", pd.Series("", index=flood.index)).astype(str)
    selected = flood[(level == "매우 높음") | (score >= 78)].copy()
    if selected.empty:
        selected = flood.sort_values("lowland_flood_score", ascending=False).head(15)
    selected = selected.sort_values("lowland_flood_score", ascending=False).head(25)

    output = pd.DataFrame(
        {
            "risk_type": "저지대 침수",
            "latitude": selected["latitude"],
            "longitude": selected["longitude"],
            "integrated_score": selected["lowland_flood_score"],
            "integrated_level": selected["lowland_flood_level"],
            "summary": selected.get("lowland_flood_reason", ""),
            "ground_risk_score": 0.0,
            "flood_risk_score": selected["lowland_flood_score"],
            "elevation_m": selected.get("elevation_m", ""),
            "relative_depression_m": selected.get("relative_depression_m", ""),
            "insar_displacement_abs": 0.0,
            "optical_component": 0.0,
            "surface_component": 0.0,
            "insar_component": 0.0,
            "detail": (
                "DEM 고도 분석에서 주변보다 낮고 완만한 지형으로 분류된 "
                "폭우 시 침수 우려 후보입니다."
            ),
        }
    )
    return output


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ground = read_csv(GROUND_PATH)
    flood = read_csv(FLOOD_PATH)

    rows = [build_ground_rows(ground), build_flood_rows(flood)]
    rows = [row for row in rows if not row.empty]

    if rows:
        output = pd.concat(rows, ignore_index=True)
        output = output.sort_values(
            ["risk_type", "integrated_score"], ascending=[True, False]
        )
    else:
        output = pd.DataFrame(
            columns=[
                "risk_type",
                "latitude",
                "longitude",
                "integrated_score",
                "integrated_level",
                "summary",
                "ground_risk_score",
                "flood_risk_score",
                "elevation_m",
                "relative_depression_m",
                "insar_displacement_abs",
                "optical_component",
                "surface_component",
                "insar_component",
                "detail",
            ]
        )

    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Integrated risk rows: {len(output)}")
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
