from pathlib import Path
from math import asin, cos, radians, sin, sqrt

import pandas as pd


OUTPUT_DIR = Path("outputs")
INTEGRATED_PATH = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
LOWLAND_PATH = OUTPUT_DIR / "lowland_flood_risk.csv"
OUTPUT_PATH = OUTPUT_DIR / "historical_flood_validation.csv"


HISTORICAL_POINTS = [
    {
        "name": "월평 자연재해위험개선지구 전미동 일대",
        "latitude": 35.9189,
        "longitude": 126.9884,
        "event_period": "상습 침수 취약지구",
        "damage_type": "호우 시 침수 우려",
        "source_note": "전주시 자연재해위험개선지구 공개 보도 기반 추정 좌표",
    },
    {
        "name": "월평 자연재해위험개선지구 송천동 일대",
        "latitude": 35.8956,
        "longitude": 127.0461,
        "event_period": "상습 침수 취약지구",
        "damage_type": "호우 시 침수 우려",
        "source_note": "전주시 자연재해위험개선지구 공개 보도 기반 추정 좌표",
    },
    {
        "name": "마전교 언더패스 일대",
        "latitude": 35.8180,
        "longitude": 127.0960,
        "event_period": "2023년 5월 호우",
        "damage_type": "차량 침수·통제 보도 지점",
        "source_note": "언론 보도 기반 추정 좌표",
    },
    {
        "name": "진북터널 입구 일대",
        "latitude": 35.8290,
        "longitude": 127.1280,
        "event_period": "2023년 5월 호우",
        "damage_type": "도로 장애·통제 보도 지점",
        "source_note": "언론 보도 기반 추정 좌표",
    },
    {
        "name": "삼천 둔치·하상도로 일대",
        "latitude": 35.8100,
        "longitude": 127.1000,
        "event_period": "2023년 7월 호우",
        "damage_type": "하천 수위 상승·도로 통제 지점",
        "source_note": "언론 보도 기반 추정 좌표",
    },
]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * earth_radius_m * asin(sqrt(a))


def nearest(row: dict, candidates: pd.DataFrame, score_col: str) -> dict:
    if candidates.empty:
        return {
            "nearest_latitude": "",
            "nearest_longitude": "",
            "nearest_distance_m": "",
            "nearest_score": "",
            "nearest_level": "",
            "nearest_type": "",
        }

    distances = candidates.apply(
        lambda cand: distance_m(
            float(row["latitude"]),
            float(row["longitude"]),
            float(cand["latitude"]),
            float(cand["longitude"]),
        ),
        axis=1,
    )
    idx = distances.idxmin()
    hit = candidates.loc[idx]
    return {
        "nearest_latitude": float(hit.get("latitude", 0)),
        "nearest_longitude": float(hit.get("longitude", 0)),
        "nearest_distance_m": float(distances.loc[idx]),
        "nearest_score": float(hit.get(score_col, hit.get("integrated_score", 0)) or 0),
        "nearest_level": str(
            hit.get("integrated_level", hit.get("lowland_flood_level", ""))
        ),
        "nearest_type": str(hit.get("risk_type", "저지대 침수 후보")),
    }


def match_level(distance: float) -> str:
    if distance <= 100:
        return "매우 잘 겹침"
    if distance <= 500:
        return "가까움"
    if distance <= 1000:
        return "근처 후보 있음"
    if distance <= 2000:
        return "간접 참고"
    return "현재 후보와 거리 있음"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    integrated = read_csv(INTEGRATED_PATH)
    lowland = read_csv(LOWLAND_PATH)

    rows = []
    for point in HISTORICAL_POINTS:
        integrated_hit = nearest(point, integrated, "integrated_score")
        lowland_hit = nearest(point, lowland, "lowland_flood_score")

        integrated_distance = integrated_hit["nearest_distance_m"]
        lowland_distance = lowland_hit["nearest_distance_m"]
        best_hit = (
            integrated_hit
            if integrated_distance != "" and integrated_distance <= lowland_distance
            else lowland_hit
        )

        rows.append(
            {
                **point,
                "nearest_latitude": best_hit["nearest_latitude"],
                "nearest_longitude": best_hit["nearest_longitude"],
                "nearest_distance_m": best_hit["nearest_distance_m"],
                "nearest_score": best_hit["nearest_score"],
                "nearest_level": best_hit["nearest_level"],
                "nearest_type": best_hit["nearest_type"],
                "match_level": match_level(float(best_hit["nearest_distance_m"])),
                "integrated_nearest_distance_m": integrated_hit["nearest_distance_m"],
                "lowland_nearest_distance_m": lowland_hit["nearest_distance_m"],
            }
        )

    output = pd.DataFrame(rows)
    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
