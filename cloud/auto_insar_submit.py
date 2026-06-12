from __future__ import annotations

from datetime import datetime, timedelta, timezone
import csv
import io
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request


ASF_SEARCH_URL = "https://api.daac.asf.alaska.edu/services/search/param"
HYP3_JOBS_URL = "https://hyp3-api.asf.alaska.edu/jobs"
AOI = "POLYGON((127.02 35.78,127.17 35.78,127.17 35.90,127.02 35.90,127.02 35.78))"
OUTPUT_DIR = Path("outputs")


def request_json(url: str, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def search_recent_slc() -> list[dict]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    query = urllib.parse.urlencode(
        {
            "platform": "Sentinel-1",
            "processingLevel": "SLC",
            "beamMode": "IW",
            "intersectsWith": AOI,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "output": "csv",
        }
    )
    with urllib.request.urlopen(f"{ASF_SEARCH_URL}?{query}", timeout=90) as response:
        text = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def parsed_time(row: dict) -> datetime:
    value = row.get("Start Time") or row.get("Acquisition Date") or ""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def choose_pair(rows: list[dict]) -> tuple[dict, dict] | None:
    candidates = [
        row
        for row in rows
        if row.get("Path Number") == "127"
        and row.get("Frame Number") == "115"
        and row.get("Ascending or Descending?") == "ASCENDING"
    ]
    candidates.sort(key=parsed_time, reverse=True)

    for reference in candidates:
        reference_time = parsed_time(reference)
        for secondary in candidates:
            secondary_time = parsed_time(secondary)
            days = (reference_time - secondary_time).days
            if 6 <= days <= 24:
                return reference, secondary
    return None


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("HYP3_TOKEN", "").strip()
    if not token:
        print("HYP3_TOKEN is not configured; skipping automatic InSAR submission.")
        return

    rows = search_recent_slc()
    pair = choose_pair(rows)
    if pair is None:
        print("No compatible recent Sentinel-1 pair found.")
        return

    reference, secondary = pair
    reference_name = reference["Granule Name"]
    secondary_name = secondary["Granule Name"]
    reference_date = parsed_time(reference).strftime("%Y%m%d")
    secondary_date = parsed_time(secondary).strftime("%Y%m%d")
    job_name = f"jeonju-insar-{secondary_date}-{reference_date}"

    recent = request_json(f"{HYP3_JOBS_URL}?limit=100", token)
    existing = [job for job in recent.get("jobs", []) if job.get("name") == job_name]
    if existing:
        print(f"HyP3 job already exists: {job_name}")
        return

    payload = {
        "jobs": [
            {
                "name": job_name,
                "job_type": "INSAR_GAMMA",
                "job_parameters": {
                    "granules": [reference_name, secondary_name],
                    "looks": "20x4",
                    "include_displacement_maps": True,
                    "include_los_displacement": True,
                    "include_inc_map": True,
                    "include_dem": False,
                    "include_wrapped_phase": False,
                    "apply_water_mask": True,
                    "phase_filter_parameter": 0.6,
                },
            }
        ]
    }
    response = request_json(HYP3_JOBS_URL, token, method="POST", payload=payload)
    (OUTPUT_DIR / "latest_hyp3_submit.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Submitted HyP3 job: {job_name}")


if __name__ == "__main__":
    main()
