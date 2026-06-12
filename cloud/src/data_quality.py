from datetime import datetime, timezone
from pathlib import Path
import json

import pandas as pd


OUTPUT_DIR = Path("outputs")


def read_json(name: str) -> dict:
    try:
        return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def row_count(name: str) -> int:
    try:
        return len(pd.read_csv(OUTPUT_DIR / name, encoding="utf-8-sig"))
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return 0


def main() -> None:
    optical = read_json("sentinel2_server_update_status.json")
    rainfall = read_json("rainfall_alert_status.json")
    insar = read_json("jeonju_hyp3_job_status.json")
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_scope": {
            "name": "전주시",
            "boundary_source": "OpenStreetMap relation 7619919",
            "boundary_filter_enabled": True,
        },
        "optical": {
            "scene_datetime": optical.get("datetime"),
            "cloud_cover_percent": optical.get("cloud_cover"),
            "candidate_count": row_count("detected_anomalies.csv"),
            "interpretation": "동일 영상 내부의 상대적 이상 후보이며 확정 확률이 아님",
        },
        "insar": {
            "job_status": insar.get("status_code", insar.get("status")),
            "hotspot_count": row_count("insar_hotspots.csv"),
            "interpretation": "위성 시선방향 변위 후보. 대기·식생·결맞음 품질 검증 필요",
        },
        "flood": {
            "candidate_count": row_count("lowland_flood_risk.csv"),
            "interpretation": "DEM 지형 후보. 배수시설·하천 수위·불투수면 미반영",
        },
        "rainfall": {
            "source": rainfall.get("forecast_source"),
            "forecast_grid_count": rainfall.get("forecast_grid_count", 0),
            "forecast_failure_count": rainfall.get("forecast_failure_count", 0),
        },
        "known_limits": [
            "광학 이상도는 학습 영상 내부 상대값",
            "InSAR 결과는 최신 처리쌍과 품질지표가 확보될 때 갱신",
            "침수 후보는 지형 중심이며 도시 배수망 자료가 아직 없음",
            "과거 침수 검증자료는 부분 표본이며 전체 5년 전수자료가 아님",
        ],
    }
    (OUTPUT_DIR / "data_quality.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
