from pathlib import Path

import folium
import pandas as pd


OUTPUT_DIR = Path("outputs")
INTEGRATED_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
HISTORICAL_PATH = OUTPUT_DIR / "historical_flood_validation.csv"


def read_csv_if_present(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def color_for(row: pd.Series) -> str:
    risk_type = str(row.get("risk_type", ""))
    level = str(row.get("integrated_level", ""))

    if risk_type == "저지대 침수":
        if level == "매우 높음":
            return "#075985"
        if level == "높음":
            return "#0284c7"
        if level == "주의":
            return "#38bdf8"
        return "#67e8f9"

    if level == "매우 높음":
        return "#7f1d1d"
    if level == "높음":
        return "#dc2626"
    if level == "주의":
        return "#f97316"
    return "#f59e0b"


def badge_style(row: pd.Series) -> str:
    color = color_for(row)
    text_color = "white" if color not in {"#67e8f9", "#f59e0b", "#38bdf8"} else "#111827"
    return f"background:{color};color:{text_color};"


def metric_row(name: str, value: str) -> str:
    return f"""
    <tr>
      <td style="padding:4px 5px; border-bottom:1px solid #e5e7eb;">{name}</td>
      <td style="padding:4px 5px; border-bottom:1px solid #e5e7eb; text-align:right;">{value}</td>
    </tr>
    """


def popup_html(row: pd.Series) -> str:
    risk_type = str(row.get("risk_type", "위험 후보"))
    level = str(row.get("integrated_level", "확인 필요"))
    score = safe_float(row.get("integrated_score", 0))
    latitude = safe_float(row.get("latitude", 0))
    longitude = safe_float(row.get("longitude", 0))

    rows = ""
    rows += metric_row("구분", risk_type)
    rows += metric_row("통합 점수", f"{score:.1f} / 100")
    rows += metric_row("지반 약화 점수", f"{safe_float(row.get('ground_risk_score', 0)):.1f} / 100")
    rows += metric_row("침수 우려 점수", f"{safe_float(row.get('flood_risk_score', 0)):.1f} / 100")

    if risk_type == "저지대 침수":
        rows += metric_row("고도", f"{safe_float(row.get('elevation_m', 0)):.1f} m")
        rows += metric_row("주변보다 낮은 정도", f"{safe_float(row.get('relative_depression_m', 0)):.1f} m")
    else:
        rows += metric_row("InSAR 변위 절댓값", f"{safe_float(row.get('insar_displacement_abs', 0)):.6f}")
        rows += metric_row("광학 영상 기여", f"{safe_float(row.get('optical_component', 0)):.1f}")
        rows += metric_row("표면 지형 기여", f"{safe_float(row.get('surface_component', 0)):.1f}")
        rows += metric_row("InSAR 기여", f"{safe_float(row.get('insar_component', 0)):.1f}")

    return f"""
    <div style="width:380px; font-family:'Malgun Gothic',Arial,sans-serif; color:#111827; line-height:1.45;">
      <div style="font-size:16px; font-weight:700; margin-bottom:8px; border-bottom:1px solid #e5e7eb; padding-bottom:6px;">
        통합 위험 후보 분석
      </div>
      <div style="margin-bottom:10px;">
        <span style="display:inline-block; padding:4px 9px; border-radius:999px; font-weight:700; {badge_style(row)}">{risk_type} · {level}</span>
        <span style="font-size:12px; color:#6b7280; margin-left:6px;">{score:.1f} / 100</span>
      </div>
      <div style="margin-bottom:8px;">
        <div style="font-size:12px; color:#6b7280; font-weight:700;">판단 요약</div>
        <div style="font-size:13px;">{row.get('summary', '')}</div>
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:12px; margin-top:4px;">
        {rows}
      </table>
      <div style="font-size:12px; color:#374151; margin:8px 0;">{row.get('detail', '')}</div>
      <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:6px; padding:7px; font-size:12px; color:#374151;">
        <b>좌표</b><br>위도 {latitude:.6f}<br>경도 {longitude:.6f}
      </div>
      <div style="font-size:11px; color:#6b7280; margin-top:8px;">
        이 표시는 우선 확인용 후보입니다. 실제 위험 확정에는 현장 조사, 배수 시설, 하천 수위, 지질 자료 확인이 필요합니다.
      </div>
    </div>
    """


def historical_popup(row: pd.Series) -> str:
    distance = safe_float(row.get("nearest_distance_m", 0))
    score = safe_float(row.get("nearest_score", 0))
    return f"""
    <div style="width:390px; font-family:'Malgun Gothic',Arial,sans-serif; color:#111827; line-height:1.45;">
      <div style="font-size:16px; font-weight:800; margin-bottom:8px;">과거 침수 이력 검증</div>
      <div style="display:inline-block; padding:4px 9px; border-radius:999px; background:#581c87; color:white; font-weight:800; margin-bottom:8px;">
        {row.get('match_level', '검증 필요')}
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:12px;">
        {metric_row("과거 지점", str(row.get("name", "")))}
        {metric_row("이력 시기", str(row.get("event_period", "")))}
        {metric_row("피해 유형", str(row.get("damage_type", "")))}
        {metric_row("가장 가까운 우리 후보", str(row.get("nearest_type", "")))}
        {metric_row("후보와 거리", f"{distance:.0f} m")}
        {metric_row("후보 점수", f"{score:.1f} / 100")}
        {metric_row("후보 등급", str(row.get("nearest_level", "")))}
      </table>
      <div style="background:#faf5ff; border:1px solid #e9d5ff; border-radius:6px; padding:8px; margin-top:8px; font-size:12px;">
        {row.get("source_note", "")}<br>
        기사·공개자료 기반 추정 좌표라 실제 시설물 위치와 약간 다를 수 있습니다.
      </div>
    </div>
    """


def add_integrated_layer(
    map_view: folium.Map,
    data: pd.DataFrame,
    risk_type: str,
    show: bool,
) -> list[list[float]]:
    layer = folium.FeatureGroup(name=risk_type, show=show)
    bounds = []
    filtered = data[data["risk_type"] == risk_type].copy()
    if filtered.empty:
        return bounds

    max_score = filtered["integrated_score"].max()
    for _, row in filtered.iterrows():
        score = safe_float(row.get("integrated_score", 0))
        radius = 10 + 14 * (score / max_score if max_score else 0)
        location = [safe_float(row["latitude"]), safe_float(row["longitude"])]
        folium.CircleMarker(
            location=location,
            radius=radius,
            popup=folium.Popup(popup_html(row), max_width=430),
            color=color_for(row),
            fill=True,
            fill_opacity=0.62,
            weight=2,
        ).add_to(layer)
        bounds.append(location)

    layer.add_to(map_view)
    return bounds


def add_historical_layer(map_view: folium.Map, data: pd.DataFrame) -> list[list[float]]:
    layer = folium.FeatureGroup(name="과거 침수 이력 검증", show=True)
    bounds = []
    if data.empty:
        return bounds

    for _, row in data.iterrows():
        location = [safe_float(row["latitude"]), safe_float(row["longitude"])]
        folium.CircleMarker(
            location=location,
            radius=11,
            popup=folium.Popup(historical_popup(row), max_width=430),
            color="#111827",
            fill=True,
            fill_color="#9333ea",
            fill_opacity=0.85,
            weight=3,
        ).add_to(layer)
        folium.map.Marker(
            location,
            icon=folium.DivIcon(
                html='<div style="font-size:18px; color:white; text-shadow:0 0 3px #111827; font-weight:900;">!</div>'
            ),
        ).add_to(layer)
        bounds.append(location)

    layer.add_to(map_view)
    return bounds


def add_legend(map_view: folium.Map) -> None:
    html = """
    <div style="
        position: fixed;
        bottom: 24px;
        left: 24px;
        z-index: 9999;
        background: white;
        padding: 12px 14px;
        border: 1px solid #999;
        border-radius: 6px;
        font-size: 13px;
        line-height: 1.55;
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    ">
      <b>통합 위험 정보</b><br>
      <span style="color:#dc2626;">●</span> 지반 약화 후보<br>
      <span style="color:#0284c7;">●</span> 저지대 침수 후보<br>
      <span style="color:#9333ea;">●</span> 과거 침수 이력 검증 지점<br>
      <hr style="margin:6px 0;">
      보라색 지점은 과거 침수·통제 이력과 현재 위험좌표를 비교한 검증 레이어입니다.
    </div>
    """
    map_view.get_root().html.add_child(folium.Element(html))


def main() -> None:
    integrated = read_csv_if_present(INTEGRATED_PATH)
    historical = read_csv_if_present(HISTORICAL_PATH)

    if not integrated.empty:
        center = [
            float(integrated["latitude"].mean()),
            float(integrated["longitude"].mean()),
        ]
    elif not historical.empty:
        center = [
            float(historical["latitude"].mean()),
            float(historical["longitude"].mean()),
        ]
    else:
        center = [35.8242, 127.1480]

    map_view = folium.Map(location=center, zoom_start=12)
    bounds = []

    if not integrated.empty:
        bounds.extend(add_integrated_layer(map_view, integrated, "지반 약화", True))
        bounds.extend(add_integrated_layer(map_view, integrated, "저지대 침수", True))

    if not historical.empty:
        bounds.extend(add_historical_layer(map_view, historical))

    folium.LayerControl().add_to(map_view)
    add_legend(map_view)
    if bounds:
        map_view.fit_bounds(bounds)

    output_path = OUTPUT_DIR / "map.html"
    map_view.save(output_path)
    print(f"Saved map: {output_path}")


if __name__ == "__main__":
    main()
