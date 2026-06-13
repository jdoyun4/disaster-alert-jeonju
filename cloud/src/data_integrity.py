from pathlib import Path
import json

import numpy as np
import pandas as pd

from spatial_filter import contains_jeonju


CLOUD_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = CLOUD_DIR / "outputs"


def read_csv(name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(OUTPUT_DIR / name, encoding="utf-8-sig")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> None:
    errors: list[str] = []
    integrated = read_csv("integrated_ground_flood_risk.csv")
    lowland = read_csv("lowland_flood_risk.csv")
    composite = read_csv("composite_ground_risk.csv")
    rainfall = read_csv("rainfall_alerts.csv")
    hotspots = read_csv("insar_hotspots.csv")

    for name, data in (
        ("integrated", integrated),
        ("lowland", lowland),
        ("composite", composite),
        ("rainfall", rainfall),
        ("hotspots", hotspots),
    ):
        check(not data.empty, f"{name}: data is empty", errors)
        if {"latitude", "longitude"}.issubset(data.columns):
            check(
                all(
                    contains_jeonju(float(lon), float(lat))
                    for lon, lat in zip(data["longitude"], data["latitude"])
                ),
                f"{name}: point outside Jeonju boundary",
                errors,
            )
            check(
                not data.duplicated(["latitude", "longitude"]).any(),
                f"{name}: duplicate coordinates",
                errors,
            )
        numeric = data.select_dtypes(include="number")
        check(not np.isinf(numeric).any().any(), f"{name}: infinite value", errors)

    if not integrated.empty:
        ground = integrated["risk_type"] == "지반 약화"
        flood = integrated["risk_type"] == "저지대 침수"
        check(
            (
                integrated.loc[ground, "ground_risk_score"]
                - integrated.loc[ground, "integrated_score"]
            ).abs().lt(1e-6).all(),
            "integrated: ground score mismatch",
            errors,
        )
        check(
            (
                integrated.loc[flood, "flood_risk_score"]
                - integrated.loc[flood, "integrated_score"]
            ).abs().lt(1e-6).all(),
            "integrated: flood score mismatch",
            errors,
        )

    if not composite.empty:
        formula = (
            composite["optical_component"].fillna(0)
            + composite["surface_component"].fillna(0)
            + composite["insar_component"].fillna(0)
            + composite.get("insar_baseline_component", 0)
            + composite["fusion_bonus"].fillna(0)
        ).clip(0, 100)
        check(
            (formula - composite["composite_risk_score"]).abs().lt(1e-5).all(),
            "composite: component sum mismatch",
            errors,
        )

    if not rainfall.empty:
        check(
            rainfall["forecast_status"].eq("지점 격자 예보").all(),
            "rainfall: forecast lookup failure",
            errors,
        )
        check(
            (
                (rainfall["forecast_max_3h_mm"] >= rainfall["forecast_max_1h_mm"])
                & (
                    rainfall["forecast_max_12h_mm"]
                    >= rainfall["forecast_max_3h_mm"]
                )
            ).all(),
            "rainfall: rolling rainfall hierarchy mismatch",
            errors,
        )

    quality_path = OUTPUT_DIR / "data_quality.json"
    quality = (
        json.loads(quality_path.read_text(encoding="utf-8-sig"))
        if quality_path.exists()
        else {}
    )
    check(
        quality.get("insar", {}).get("status_matches_raster") is True,
        "insar: job status does not match active raster",
        errors,
    )

    payload = {
        "status": "ok" if not errors else "error",
        "error_count": len(errors),
        "errors": errors,
        "counts": {
            "integrated": len(integrated),
            "lowland": len(lowland),
            "composite": len(composite),
            "rainfall": len(rainfall),
            "insar_hotspots": len(hotspots),
        },
    }
    (OUTPUT_DIR / "data_integrity.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if errors:
        raise SystemExit("; ".join(errors))
    print("Data integrity: ok")


if __name__ == "__main__":
    main()
