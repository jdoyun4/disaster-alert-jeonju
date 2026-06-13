from pathlib import Path
import json

import pandas as pd


OUTPUT_DIR = Path("outputs")
APP_PATH = OUTPUT_DIR / "index.html"
INTEGRATED_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
RAINFALL_PATH = OUTPUT_DIR / "rainfall_alerts.csv"
HISTORICAL_PATH = OUTPUT_DIR / "historical_flood_validation.csv"
SENTINEL_STATUS_PATH = OUTPUT_DIR / "sentinel2_server_update_status.json"

ALERT_RADIUS_M = 500
WARNING_RADIUS_M = 1500


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def number(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def risk_points_json(data: pd.DataFrame) -> str:
    points = []
    for _, row in data.iterrows():
        points.append(
            {
                "risk_type": str(row.get("risk_type", "")),
                "level": str(row.get("integrated_level", "")),
                "score": number(row.get("integrated_score", 0)),
                "lat": number(row.get("latitude", 0)),
                "lon": number(row.get("longitude", 0)),
                "summary": str(row.get("summary", "")),
            }
        )
    return json.dumps(points, ensure_ascii=False)


def rainfall_rows(alerts: pd.DataFrame) -> str:
    if alerts.empty:
        return '<tr><td colspan="6">강우 경고 데이터가 없습니다.</td></tr>'

    rows = []
    for _, row in alerts.head(25).iterrows():
        rows.append(
            f"""
            <tr>
              <td>{row.get('alert_level', '')}</td>
              <td>{number(row.get('flood_risk_score', 0)):.1f}</td>
              <td>{number(row.get('forecast_max_3h_mm', 0)):.1f} mm</td>
              <td>{number(row.get('local_advisory_3h_mm', 0)):.1f} mm</td>
              <td>{number(row.get('forecast_max_12h_mm', 0)):.1f} mm</td>
              <td>{number(row.get('local_advisory_12h_mm', 0)):.1f} mm</td>
            </tr>
            """
        )
    return "\n".join(rows)


def integrated_rows(integrated: pd.DataFrame) -> str:
    if integrated.empty:
        return '<tr><td colspan="5">통합 위험 후보 데이터가 없습니다.</td></tr>'

    rows = []
    for _, row in integrated.iterrows():
        rows.append(
            f"""
            <tr>
              <td>{row.get('risk_type', '')}</td>
              <td>{row.get('integrated_level', '')}</td>
              <td>{number(row.get('integrated_score', 0)):.1f}</td>
              <td>{number(row.get('latitude', 0)):.6f}, {number(row.get('longitude', 0)):.6f}</td>
              <td>{row.get('summary', '')}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def historical_rows(historical: pd.DataFrame) -> str:
    if historical.empty:
        return '<tr><td colspan="7">과거 침수 이력 검증 데이터가 없습니다.</td></tr>'

    rows = []
    for _, row in historical.iterrows():
        rows.append(
            f"""
            <tr>
              <td>{row.get('name', '')}</td>
              <td>{row.get('event_period', '')}</td>
              <td>{row.get('damage_type', '')}</td>
              <td>{row.get('nearest_type', '')}</td>
              <td>{number(row.get('nearest_distance_m', 0)):.0f} m</td>
              <td>{number(row.get('nearest_score', 0)):.1f}</td>
              <td>{row.get('match_level', '')}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def summary_cards(integrated: pd.DataFrame, rainfall: pd.DataFrame, historical: pd.DataFrame) -> str:
    ground_count = int((integrated.get("risk_type", "") == "지반 약화").sum()) if not integrated.empty else 0
    flood_count = int((integrated.get("risk_type", "") == "저지대 침수").sum()) if not integrated.empty else 0
    alert_counts = rainfall.get("alert_level", pd.Series(dtype=str)).value_counts().to_dict()
    warning_count = int(alert_counts.get("주의 경고", 0) + alert_counts.get("긴급 경고", 0))
    strong_matches = int(
        historical.get("match_level", pd.Series(dtype=str)).isin(["매우 잘 겹침", "가까움"]).sum()
    ) if not historical.empty else 0
    return f"""
      <div class="card"><span>지반 약화 후보</span><b>{ground_count}</b></div>
      <div class="card"><span>저지대 침수 후보</span><b>{flood_count}</b></div>
      <div class="card"><span>강우 경고 후보</span><b>{warning_count}</b></div>
      <div class="card"><span>과거 이력 일치</span><b>{strong_matches}</b></div>
    """


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    integrated = read_csv(INTEGRATED_PATH)
    rainfall = read_csv(RAINFALL_PATH)
    historical = read_csv(HISTORICAL_PATH)
    sentinel_status = read_json(SENTINEL_STATUS_PATH)

    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>전주 지반·침수 통합 위험 앱</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: 'Malgun Gothic', Arial, sans-serif; background: #f8fafc; color: #111827; }}
    header {{ padding: 16px 20px; background: #111827; color: white; display: flex; justify-content: space-between; gap: 14px; align-items: center; }}
    header h1 {{ margin: 0; font-size: 20px; }}
    header .meta {{ font-size: 12px; color: #d1d5db; }}
    nav {{ display: flex; gap: 8px; padding: 10px 14px; background: white; border-bottom: 1px solid #e5e7eb; position: sticky; top: 0; z-index: 5; }}
    nav button {{ border: 1px solid #d1d5db; background: white; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-weight: 700; white-space: nowrap; }}
    nav button.active {{ background: #111827; color: white; border-color: #111827; }}
    main {{ padding: 14px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }}
    .card span {{ display: block; font-size: 12px; color: #6b7280; }}
    .card b {{ font-size: 26px; }}
    section {{ display: none; }}
    section.active {{ display: block; }}
    iframe {{ width: 100%; height: calc(100vh - 190px); border: 1px solid #d1d5db; border-radius: 8px; background: white; }}
    .panel {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; margin-bottom: 12px; }}
    .actions button {{ border: 0; border-radius: 6px; padding: 11px 13px; background: #111827; color: white; font-weight: 700; cursor: pointer; margin-right: 8px; margin-bottom: 8px; }}
    .actions button.secondary {{ background: #2563eb; }}
    .status {{ font-size: 20px; font-weight: 800; margin-top: 8px; }}
    .safe {{ color: #166534; }}
    .warn {{ color: #c2410c; }}
    .danger {{ color: #991b1b; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; background: white; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .small {{ color: #6b7280; font-size: 12px; line-height: 1.5; }}
    @media (max-width: 800px) {{
      header {{ display: block; }}
      .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      iframe {{ height: calc(100vh - 240px); }}
      nav {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
<header>
  <h1>전주 지반·침수 통합 위험 앱</h1>
  <div class="meta">위성 갱신 상태: {sentinel_status.get('status', '확인 필요')} · 최근 장면: {sentinel_status.get('id', '')}</div>
</header>
<nav>
  <button class="active" onclick="showTab('map', this)">통합 위험 지도</button>
  <button onclick="showTab('rain', this)">강우 경고</button>
  <button onclick="showTab('location', this)">내 위치 알림</button>
  <button onclick="showTab('history', this)">과거 침수 검증</button>
  <button onclick="showTab('data', this)">데이터 요약</button>
</nav>
<main>
  <div class="cards">{summary_cards(integrated, rainfall, historical)}</div>

  <section id="map" class="active">
    <iframe src="map.html"></iframe>
  </section>

  <section id="rain">
    <div class="panel">
      <b>강수량 기반 침수 경고</b>
      <div class="small">최신 예보를 위험 지점별 기준과 비교합니다. 저지대일수록 더 낮은 강수량에서도 주의로 표시될 수 있습니다.</div>
    </div>
    <table>
      <thead><tr><th>상태</th><th>침수점수</th><th>예보 3시간</th><th>지역 3시간 기준</th><th>예보 12시간</th><th>지역 12시간 기준</th></tr></thead>
      <tbody>{rainfall_rows(rainfall)}</tbody>
    </table>
  </section>

  <section id="location">
    <div class="panel">
      <b>내 위치 기반 위험 알림</b>
      <div class="small">{ALERT_RADIUS_M}m 이내는 경고, {WARNING_RADIUS_M}m 이내는 주의로 판단합니다. 브라우저 위치 권한을 허용해야 합니다.</div>
      <div class="actions">
        <button onclick="checkLocation()">내 위치로 위험 확인</button>
        <button class="secondary" onclick="startWatch()">위치 계속 감시</button>
        <button class="secondary" onclick="stopWatch()">감시 중지</button>
      </div>
      <div id="status" class="status">대기 중</div>
      <div id="locationText" class="small"></div>
    </div>
    <div class="panel">
      <b>가까운 위험 후보</b>
      <div id="nearest"></div>
    </div>
  </section>

  <section id="history">
    <div class="panel">
      <b>과거 침수 이력 검증</b>
      <div class="small">기사와 공개자료에서 확인된 침수·통제 지점을 추정 좌표로 만든 뒤, 우리가 만든 위험좌표와 얼마나 가까운지 비교한 표입니다.</div>
    </div>
    <table>
      <thead><tr><th>과거 지점</th><th>시기</th><th>피해 유형</th><th>가장 가까운 우리 후보</th><th>거리</th><th>후보 점수</th><th>판정</th></tr></thead>
      <tbody>{historical_rows(historical)}</tbody>
    </table>
  </section>

  <section id="data">
    <div class="panel">
      <b>통합 위험 후보 데이터</b>
      <div class="small">붉은 계열은 지반 약화, 푸른 계열은 저지대 침수 우려입니다. 지도에서는 보라색으로 과거 침수 이력을 따로 표시합니다.</div>
    </div>
    <table>
      <thead><tr><th>구분</th><th>등급</th><th>점수</th><th>좌표</th><th>요약</th></tr></thead>
      <tbody>{integrated_rows(integrated)}</tbody>
    </table>
  </section>
</main>

<script>
const riskPoints = {risk_points_json(integrated)};
const alertRadiusM = {ALERT_RADIUS_M};
const warningRadiusM = {WARNING_RADIUS_M};
let watchId = null;
let audioCtx = null;

function showTab(id, button) {{
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  button.classList.add('active');
}}

function distanceM(lat1, lon1, lat2, lon2) {{
  const R = 6371000;
  const toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon/2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}}

function beep() {{
  try {{
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.18;
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    setTimeout(() => osc.stop(), 700);
  }} catch (e) {{}}
}}

function evaluate(lat, lon) {{
  const sorted = riskPoints.map(p => ({{...p, distance: distanceM(lat, lon, p.lat, p.lon)}})).sort((a, b) => a.distance - b.distance);
  const nearest = sorted.slice(0, 8);
  const closest = nearest[0];
  const status = document.getElementById('status');
  document.getElementById('locationText').textContent = `현재 위치: 위도 ${{lat.toFixed(6)}}, 경도 ${{lon.toFixed(6)}}`;
  if (!closest) {{
    status.textContent = '위험 후보 데이터가 없음';
    status.className = 'status warn';
    return;
  }}
  if (closest.distance <= alertRadiusM) {{
    status.textContent = `경고: ${{Math.round(closest.distance)}}m 근처에 ${{closest.risk_type}} 후보가 있습니다`;
    status.className = 'status danger';
    beep();
  }} else if (closest.distance <= warningRadiusM) {{
    status.textContent = `주의: ${{Math.round(closest.distance)}}m 근처에 위험 후보가 있습니다`;
    status.className = 'status warn';
  }} else {{
    status.textContent = `정상: 가장 가까운 위험 후보까지 ${{Math.round(closest.distance)}}m`;
    status.className = 'status safe';
  }}
  document.getElementById('nearest').innerHTML = `<table><thead><tr><th>거리</th><th>구분</th><th>등급</th><th>점수</th><th>요약</th></tr></thead><tbody>${{nearest.map(p => `<tr><td>${{Math.round(p.distance)}}m</td><td>${{p.risk_type}}</td><td>${{p.level}}</td><td>${{p.score.toFixed(1)}}</td><td>${{p.summary}}</td></tr>`).join('')}}</tbody></table>`;
}}

function onError() {{
  const status = document.getElementById('status');
  status.textContent = '위치 확인 실패: 브라우저 위치 권한을 허용해야 합니다.';
  status.className = 'status warn';
}}

function checkLocation() {{
  if (!navigator.geolocation) return onError();
  navigator.geolocation.getCurrentPosition(pos => evaluate(pos.coords.latitude, pos.coords.longitude), onError, {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }});
}}

function startWatch() {{
  if (!navigator.geolocation) return onError();
  if (watchId !== null) return;
  watchId = navigator.geolocation.watchPosition(pos => evaluate(pos.coords.latitude, pos.coords.longitude), onError, {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }});
  document.getElementById('status').textContent = '위치 감시 중';
}}

function stopWatch() {{
  if (watchId !== null) {{
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }}
  document.getElementById('status').textContent = '감시 중지됨';
  document.getElementById('status').className = 'status';
}}
</script>
</body>
</html>"""

    APP_PATH.write_text(html, encoding="utf-8")
    print(f"Saved: {APP_PATH}")


if __name__ == "__main__":
    main()
