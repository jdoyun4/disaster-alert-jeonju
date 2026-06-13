from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import time
import urllib.parse
import urllib.request

import pandas as pd


OUTPUT_DIR = Path("outputs")
INTEGRATED_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
ALERT_CSV_PATH = OUTPUT_DIR / "rainfall_alerts.csv"
ALERT_STATUS_PATH = OUTPUT_DIR / "rainfall_alert_status.json"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_TYPE = "저지대 침수"


def fetch_rainfall(latitude: float, longitude: float, attempts: int = 3) -> pd.Series:
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "precipitation",
            "forecast_days": 3,
            "timezone": "Asia/Seoul",
        }
    )
    request = urllib.request.Request(
        f"{FORECAST_URL}?{query}",
        headers={"User-Agent": "JeonjuDisasterAlert/2.1"},
    )
    last_error = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                hourly = json.loads(response.read().decode("utf-8")).get("hourly", {})
            values = pd.to_numeric(
                pd.Series(hourly.get("precipitation", [])), errors="coerce"
            ).fillna(0)
            if values.empty:
                raise ValueError("Empty precipitation forecast")
            return values
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError("Rainfall forecast unavailable") from last_error


def rolling_max(values: pd.Series, hours: int) -> float:
    return float(values.rolling(hours, min_periods=1).sum().max()) if not values.empty else 0.0


def thresholds(row: pd.Series) -> tuple[float, float, float, float]:
    score = float(row.get("flood_risk_score", 0) or 0) / 100
    depression = min(1.0, float(row.get("relative_depression_m", 0) or 0) / 10)
    evidence = min(1.0, float(row.get("terrain_evidence_count", 0) or 0) / 3)
    reduction = min(0.45, 0.20 * score + 0.12 * depression + 0.13 * evidence)
    return tuple(base * (1 - reduction) for base in (60.0, 110.0, 90.0, 180.0))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        integrated = pd.read_csv(INTEGRATED_PATH, encoding="utf-8-sig")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        integrated = pd.DataFrame()
    flood = integrated[integrated.get("risk_type", "") == FLOOD_TYPE].copy()
    cache: dict[tuple[float, float], pd.Series | None] = {}
    rows = []

    for _, row in flood.iterrows():
        key = (round(float(row.latitude), 2), round(float(row.longitude), 2))
        if key not in cache:
            try:
                cache[key] = fetch_rainfall(*key)
            except Exception:
                cache[key] = None

        rain = cache[key]
        if rain is not None:
            source_status = "지점 격자 예보"
        else:
            rain = pd.Series(dtype=float)
            source_status = "예보 조회 실패"
        max_1h = float(rain.max()) if not rain.empty else float("nan")
        max_3h = rolling_max(rain, 3) if not rain.empty else float("nan")
        max_12h = rolling_max(rain, 12) if not rain.empty else float("nan")
        advisory_3h, advisory_12h, warning_3h, warning_12h = thresholds(row)
        level = (
            "예보 확인 필요"
            if rain.empty
            else "긴급 경고"
            if max_3h >= warning_3h or max_12h >= warning_12h
            else "주의 경고"
            if max_3h >= advisory_3h or max_12h >= advisory_12h
            else "정상"
        )
        rows.append(
            {
                "alert_level": level,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "flood_risk_score": row.flood_risk_score,
                "elevation_m": row.get("elevation_m", ""),
                "relative_depression_m": row.get("relative_depression_m", ""),
                "terrain_evidence_count": row.get("terrain_evidence_count", ""),
                "forecast_max_1h_mm": max_1h,
                "forecast_max_3h_mm": max_3h,
                "forecast_max_12h_mm": max_12h,
                "local_advisory_3h_mm": advisory_3h,
                "local_advisory_12h_mm": advisory_12h,
                "local_warning_3h_mm": warning_3h,
                "local_warning_12h_mm": warning_12h,
                "forecast_source_latitude": key[0],
                "forecast_source_longitude": key[1],
                "forecast_status": source_status,
                "message": (
                    "강우 예보를 일시적으로 가져오지 못했습니다. 다음 자동 갱신에서 재시도합니다."
                    if rain.empty
                    else
                    f"[{level}] 3시간 최대 {max_3h:.1f}mm / 지역 주의기준 {advisory_3h:.1f}mm, "
                    f"12시간 최대 {max_12h:.1f}mm / 지역 주의기준 {advisory_12h:.1f}mm."
                ),
            }
        )

    alerts = pd.DataFrame(rows)
    if not alerts.empty:
        order = {"긴급 경고": 0, "주의 경고": 1, "예보 확인 필요": 2, "정상": 3}
        alerts["_order"] = alerts.alert_level.map(order)
        alerts = alerts.sort_values(
            ["_order", "flood_risk_score"], ascending=[True, False]
        ).drop(columns="_order")
    alerts.to_csv(ALERT_CSV_PATH, index=False, encoding="utf-8-sig")
    counts = alerts.alert_level.value_counts().to_dict() if not alerts.empty else {}
    failures = sum(value is None for value in cache.values())
    ALERT_STATUS_PATH.write_text(
        json.dumps(
            {
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "forecast_source": "Open-Meteo",
                "forecast_grid_count": len(cache),
                "forecast_failure_count": failures,
                "alert_counts": counts,
                "warning_count": int(counts.get("주의 경고", 0)),
                "emergency_count": int(counts.get("긴급 경고", 0)),
                "unknown_count": int(counts.get("예보 확인 필요", 0)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Rainfall alerts: {counts}; forecast grids: {len(cache)}")


if __name__ == "__main__":
    main()
