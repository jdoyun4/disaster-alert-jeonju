from pathlib import Path
import json

import pandas as pd


OUTPUT_DIR = Path("outputs")
INPUT_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
OUTPUT_PATH = OUTPUT_DIR / "personal_location_alert.html"

ALERT_RADIUS_M = 900
WARNING_RADIUS_M = 1500


def read_risk_data() -> pd.DataFrame:
    if not INPUT_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = read_risk_data()
    points = []

    for _, row in data.iterrows():
        points.append(
            {
                "risk_type": str(row.get("risk_type", "")),
                "level": str(row.get("integrated_level", "")),
                "score": float(row.get("integrated_score", 0) or 0),
                "lat": float(row.get("latitude", 0) or 0),
                "lon": float(row.get("longitude", 0) or 0),
                "summary": str(row.get("summary", "")),
            }
        )

    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>개인 위치 위험 알림</title>
  <style>
    body {{ font-family: 'Malgun Gothic', Arial, sans-serif; margin: 0; color: #111827; background: #f8fafc; }}
    main {{ max-width: 860px; margin: 0 auto; padding: 22px; }}
    h1 {{ font-size: 24px; margin: 0 0 10px; }}
    .panel {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-top: 14px; }}
    button {{ border: 0; border-radius: 6px; padding: 12px 14px; background: #111827; color: white; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #2563eb; }}
    .status {{ font-size: 20px; font-weight: 800; margin-top: 8px; }}
    .safe {{ color: #166534; }}
    .warn {{ color: #c2410c; }}
    .danger {{ color: #991b1b; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .small {{ color: #6b7280; font-size: 12px; line-height: 1.5; }}
  </style>
</head>
<body>
<main>
  <h1>개인 위치 위험 알림</h1>
  <div class="small">
    위치 권한을 허용하면 현재 위치와 통합 위험 후보군을 비교합니다.
    {ALERT_RADIUS_M}m 이내는 경고, {WARNING_RADIUS_M}m 이내는 주의로 판단합니다.
  </div>

  <div class="panel">
    <button onclick="checkLocation()">내 위치로 위험 확인</button>
    <button class="secondary" onclick="startWatch()">위치 계속 감시</button>
    <button class="secondary" onclick="stopWatch()">감시 중지</button>
    <div id="status" class="status">대기 중</div>
    <div id="location" class="small"></div>
  </div>

  <div class="panel">
    <b>가까운 위험 후보</b>
    <div id="nearest"></div>
  </div>

  <div class="panel small">
    이 기능은 개인 보조 알림입니다. 실제 대피·통제 판단은 기상청, 지자체, 현장 안내를 우선하세요.
    브라우저 위치 정확도는 기기, Wi-Fi, GPS 상태에 따라 달라질 수 있습니다.
  </div>
</main>

<script>
const riskPoints = {json.dumps(points, ensure_ascii=False)};
const alertRadiusM = {ALERT_RADIUS_M};
const warningRadiusM = {WARNING_RADIUS_M};
let watchId = null;
let audioCtx = null;

function distanceM(lat1, lon1, lat2, lon2) {{
  const R = 6371000;
  const toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon/2) ** 2;
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
  const sorted = riskPoints
    .map(p => ({{...p, distance: distanceM(lat, lon, p.lat, p.lon)}}))
    .sort((a, b) => a.distance - b.distance);
  const nearest = sorted.slice(0, 8);
  const closest = nearest[0];
  const status = document.getElementById('status');
  const location = document.getElementById('location');
  location.textContent = `현재 위치: 위도 ${{lat.toFixed(6)}}, 경도 ${{lon.toFixed(6)}}`;

  if (!closest) {{
    status.textContent = '위험 후보 데이터 없음';
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

  document.getElementById('nearest').innerHTML = `
    <table>
      <thead><tr><th>거리</th><th>구분</th><th>등급</th><th>점수</th><th>요약</th></tr></thead>
      <tbody>
        ${{nearest.map(p => `
          <tr>
            <td>${{Math.round(p.distance)}}m</td>
            <td>${{p.risk_type}}</td>
            <td>${{p.level}}</td>
            <td>${{p.score.toFixed(1)}}</td>
            <td>${{p.summary}}</td>
          </tr>`).join('')}}
      </tbody>
    </table>`;
}}

function onError(err) {{
  const status = document.getElementById('status');
  status.textContent = '위치 확인 실패: 브라우저 위치 권한을 허용해야 합니다';
  status.className = 'status warn';
}}

function checkLocation() {{
  if (!navigator.geolocation) {{
    onError();
    return;
  }}
  navigator.geolocation.getCurrentPosition(
    pos => evaluate(pos.coords.latitude, pos.coords.longitude),
    onError,
    {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }}
  );
}}

function startWatch() {{
  if (!navigator.geolocation) {{
    onError();
    return;
  }}
  if (watchId !== null) return;
  watchId = navigator.geolocation.watchPosition(
    pos => evaluate(pos.coords.latitude, pos.coords.longitude),
    onError,
    {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }}
  );
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

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Saved: {OUTPUT_PATH}")
    print(f"Risk points embedded: {len(points)}")


if __name__ == "__main__":
    main()
