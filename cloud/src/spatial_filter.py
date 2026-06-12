from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BOUNDARY_PATH = Path("data/boundaries/jeonju_boundary.geojson")


def _rings() -> list[list[list[float]]]:
    if not BOUNDARY_PATH.exists():
        return []
    geometry = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8-sig"))["geometry"]
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    if geometry["type"] == "MultiPolygon":
        return [ring for polygon in geometry["coordinates"] for ring in polygon]
    return []


def _inside_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses:
            boundary_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < boundary_x:
                inside = not inside
        previous = current
    return inside


def contains_jeonju(longitude: float, latitude: float) -> bool:
    rings = _rings()
    if not rings:
        return True
    return any(_inside_ring(longitude, latitude, ring) for ring in rings)


def filter_jeonju(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty or not {"longitude", "latitude"}.issubset(data.columns):
        return data.copy()
    mask = [
        contains_jeonju(float(lon), float(lat))
        for lon, lat in zip(data["longitude"], data["latitude"])
    ]
    return data.loc[mask].copy()
