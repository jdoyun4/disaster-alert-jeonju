from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import urllib.parse
import urllib.request

import pandas as pd


OUTPUT_DIR = Path("outputs")
INTEGRATED_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
ALERT_CSV_PATH = OUTPUT_DIR / "rainfall_alerts.csv"
ALERT_HTML_PATH = OUTPUT_DIR / "rainfall_alert.html"
ALERT_STATUS_PATH = OUTPUT_DIR / "rainfall_alert_status.json"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_LATITUDE = 35.8242
DEFAULT_LONGITUDE = 127.1480

# KMA heavy-rain special-weather thresholds:
# advisory 3h 60 mm or 12h 110 mm, warning 3h 90 mm or 12h 180 mm.
KMA_ADVISORY_3H_MM = 60.0
KMA_ADVISORY_12H_MM = 110.0
KMA_WARNING_3H_MM = 90.0
KMA_WARNING_12H_MM = 180.0


def read_integrated() -> pd.DataFrame:
    if not INTEGRATED_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(INTEGRATED_PATH, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def forecast_center(data: pd.DataFrame) -> tuple[float, float]:
    flood = data[data.get("risk_type", "") == "저지대 침수"].copy()
    source = flood if not flood.empty else data
    if source.empty:
        return DEFAULT_LATITUDE, DEFAULT_LONGITUDE
    return float(source["latitude"].mean()), float(source["longitude"].mean())


def fetch_hourly_rainfall(latitude: float, longitude: float) -> pd.DataFrame:
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "precipitation",
            "forecast_days": 3,
            "timezone": "Asia/Seoul",
        }
    )
    url = f"{FORECAST_URL}?{query}"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    hourly = payload.get("hourly", {})
    return pd.DataFrame(
        {
            "time": hourly.get("time", []),
            "precipitation_mm": hourly.get("precipitation", []),
        }
    )


def max_rolling(values: pd.Series, window: int) -> float:
    if values.empty:
        return 0.0
    return float(values.rolling(window=window, min_periods=1).sum().max())


def local_thresholds(row: pd.Series) -> tuple[float, float, float, float]:
    flood_score = float(row.get("flood_risk_score", 0) or 0)
    depression = float(row.get("relative_depression_m", 0) or 0)

    vulnerability = min(1.0, max(0.0, flood_score / 100.0))
    depression_factor = min(1.0, max(0.0, depression / 10.0))
    reduction = min(0.48, 0.34 * vulnerability + 0.14 * depression_factor)

    advisory_3h = KMA_ADVISORY_3H_MM * (1 - reduction)
    advisory_12h = KMA_ADVISORY_12H_MM * (1 - reduction)
    warning_3h = KMA_WARNING_3H_MM * (1 - reduction)
    warning_12h = KMA_WARNING_12H_MM * (1 - reduction)
    return advisory_3h, advisory_12h, warning_3h, warning_12h


def alert_level(max_3h: float, max_12h: float, row: pd.Series) -> str:
    advisory_3h, advisory_12h, warning_3h, warning_12h = local_thresholds(row)

    if max_3h >= warning_3h or max_12h >= warning_12h:
        return "긴급 경고"
    if max_3h >= advisory_3h or max_12h >= advisory_12h:
        return "주의 경고"
    return "정상"


def build_alerts(integrated: pd.DataFrame, rainfall: pd.DataFrame) -> pd.DataFrame:
    flood = integrated[integrated["risk_type"] == "저지대 침수"].copy()
    if flood.empty:
        return pd.DataFrame()

    rain_values = pd.to_numeric(rainfall["precipitation_mm"], errors="coerce").fillna(0)
    max_1h = float(rain_values.max()) if not rain_values.empty else 0.0
    max_3h = max_rolling(rain_values, 3)
    max_12h = max_rolling(rain_values, 12)

    rows = []
    for _, row in flood.iterrows():
        advisory_3h, advisory_12h, warning_3h, warning_12h = local_thresholds(row)
        level = alert_level(max_3h, max_12h, row)
        flood_score = float(row.get("flood_risk_score", 0) or 0)
        rows.append(
            {
                "alert_level": level,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "flood_risk_score": flood_score,
                "elevation_m": row.get("elevation_m", ""),
                "relative_depression_m": row.get("relative_depression_m", ""),
                "forecast_max_1h_mm": max_1h,
                "forecast_max_3h_mm": max_3h,
                "forecast_max_12h_mm": max_12h,
                "local_advisory_3h_mm": advisory_3h,
                "local_advisory_12h_mm": advisory_12h,
                "local_warning_3h_mm": warning_3h,
                "local_warning_12h_mm": warning_12h,
                "message": build_message(
                    level, row, max_1h, max_3h, max_12h, advisory_3h, advisory_12h
                ),
            }
        )

    order = {"긴급 경고": 0, "주의 경고": 1, "정상": 2}
    output = pd.DataFrame(rows)
    output["sort_key"] = output["alert_level"].map(order).fillna(9)
    output = output.sort_values(["sort_key", "flood_risk_score"], ascending=[True, False])
    return output.drop(columns=["sort_key"])


def build_message(
    level: str,
    row: pd.Series,
    max_1h: float,
    max_3h: float,
    max_12h: float,
    advisory_3h: float,
    advisory_12h: float,
) -> str:
    return (
        f"[{level}] 저지대 침수 후보 지점입니다. "
        f"예보 최대 강수량: 1시간 {max_1h:.1f}mm, 3시간 {max_3h:.1f}mm, "
        f"12시간 {max_12h:.1f}mm. "
        f"이 지점의 주의 기준은 3시간 {advisory_3h:.1f}mm 또는 "
        f"12시간 {advisory_12h:.1f}mm입니다. "
        f"고도 {float(row.get('elevation_m', 0) or 0):.1f}m, "
        f"주변보다 낮은 정도 {float(row.get('relative_depression_m', 0) or 0):.1f}m."
    )


def write_html(alerts: pd.DataFrame) -> None:
    if alerts.empty:
        body = "<p>침수 경고 대상 데이터가 없습니다.</p>"
    else:
        rows = []
        for _, row in alerts.head(25).iterrows():
            color = "#991b1b" if row["alert_level"] == "긴급 경고" else "#c2410c" if row["alert_level"] == "주의 경고" else "#166534"
            rows.append(
                f"""
                <tr>
                  <td style="color:{color};font-weight:700;">{row['alert_level']}</td>
                  <td>{float(row['latitude']):.6f}, {float(row['longitude']):.6f}</td>
                  <td>{float(row['flood_risk_score']):.1f}</td>
                  <td>{float(row['forecast_max_3h_mm']):.1f} / {float(row['local_advisory_3h_mm']):.1f}</td>
                  <td>{float(row['forecast_max_12h_mm']):.1f} / {float(row['local_advisory_12h_mm']):.1f}</td>
                  <td>{row['message']}</td>
                </tr>
                """
            )
        body = f"""
        <table>
          <thead>
            <tr>
              <th>상태</th><th>좌표</th><th>침수점수</th>
              <th>3시간 예보/기준(mm)</th><th>12시간 예보/기준(mm)</th><th>메시지</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        """

    ALERT_HTML_PATH.write_text(
        f"""
        <!doctype html>
        <html lang="ko">
        <head>
          <meta charset="utf-8">
          <title>강우 침수 경고</title>
          <style>
            body {{ font-family: 'Malgun Gothic', Arial, sans-serif; margin: 24px; color: #111827; }}
            table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
            th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }}
            th {{ background: #f3f4f6; }}
          </style>
        </head>
        <body>
          <h1>강우량 기반 침수 경고</h1>
          <p>기준: 공식 호우특보 강수량 기준을 바탕으로, 저지대 침수 점수와 주변보다 낮은 정도에 따라 지역 기준을 낮춰 계산했습니다.</p>
          {body}
        </body>
        </html>
        """,
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    integrated = read_integrated()
    if integrated.empty:
        pd.DataFrame().to_csv(ALERT_CSV_PATH, index=False, encoding="utf-8-sig")
        write_html(pd.DataFrame())
        print("No integrated risk data found.")
        return

    latitude, longitude = forecast_center(integrated)
    rainfall = fetch_hourly_rainfall(latitude, longitude)
    alerts = build_alerts(integrated, rainfall)
    alerts.to_csv(ALERT_CSV_PATH, index=False, encoding="utf-8-sig")
    write_html(alerts)

    counts = alerts["alert_level"].value_counts().to_dict() if not alerts.empty else {}
    warning_count = sum(
        int(value)
        for key, value in counts.items()
        if "주의" in str(key) or "二쇱쓽" in str(key)
    )
    emergency_count = sum(
        int(value)
        for key, value in counts.items()
        if "긴급" in str(key) or "湲닿툒" in str(key)
    )
    ALERT_STATUS_PATH.write_text(
        json.dumps(
            {
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "forecast_center": {"latitude": latitude, "longitude": longitude},
                "alert_counts": counts,
                "warning_count": warning_count,
                "emergency_count": emergency_count,
                "alert_csv": str(ALERT_CSV_PATH),
                "alert_html": str(ALERT_HTML_PATH),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Rainfall alerts: {counts}")
    print(f"Saved: {ALERT_CSV_PATH}")
    print(f"Saved: {ALERT_HTML_PATH}")


if __name__ == "__main__":
    main()
