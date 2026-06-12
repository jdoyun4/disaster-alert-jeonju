from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
DOCS_DIR = ROOT / "docs"


def run(*args: str, required: bool = True) -> int:
    print("$", " ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, check=False)
    if required and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def python(script: str, *args: str, required: bool = True) -> int:
    return run(sys.executable, script, *args, required=required)


def sentinel_updated() -> bool:
    path = OUTPUT_DIR / "sentinel2_server_update_status.json"
    if not path.exists():
        return False
    return json.loads(path.read_text(encoding="utf-8")).get("status") == "updated"


def refresh_optical() -> None:
    python("src/preprocess.py")
    python("src/tile_generator.py")
    python("src/train.py")
    python("src/detect.py")


def refresh_insar() -> bool:
    token = os.environ.get("HYP3_TOKEN", "").strip()
    if not token:
        print("No HYP3_TOKEN; retaining the bundled baseline InSAR raster.")
        python("src/insar_analysis.py")
        return False

    python("auto_insar_submit.py", required=False)
    python("src/monitor_jeonju_hyp3_insar.py", required=False)
    status_path = OUTPUT_DIR / "jeonju_hyp3_job_status.json"
    if not status_path.exists():
        python("src/insar_analysis.py")
        return False

    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("status_code") != "SUCCEEDED":
        print("Newest HyP3 job is not complete; retaining the baseline InSAR raster.")
        python("src/insar_analysis.py")
        return False

    insar_dir = ROOT / "data" / "insar"
    for path in insar_dir.glob("*.tif"):
        path.unlink()
    python("src/download_hyp3_results.py")
    for path in insar_dir.glob("*los_disp.tif"):
        path.unlink()
    python("src/insar_analysis.py")
    return True


def rebuild_risk() -> None:
    python("src/composite_risk.py")
    python("src/natural_disaster_risk.py")
    python("src/lowland_flood_risk.py")
    python("src/integrated_risk.py")


def publish() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    names = [
        "index.html",
        "map.html",
        "rainfall_alert.html",
        "rainfall_alerts.csv",
        "rainfall_alert_status.json",
        "sentinel2_server_update_status.json",
        "integrated_ground_flood_risk.csv",
        "historical_flood_validation.csv",
        "insar_displacement_summary.csv",
        "jeonju_hyp3_job_status.json",
    ]
    for name in names:
        source = OUTPUT_DIR / name
        if source.exists():
            shutil.copy2(source, DOCS_DIR / name)

    risk_points = []
    risk_path = OUTPUT_DIR / "integrated_ground_flood_risk.csv"
    if risk_path.exists():
        with risk_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                risk_points.append(
                    {
                        "risk_type": row.get("risk_type", ""),
                        "level": row.get("integrated_level", ""),
                        "score": float(row.get("integrated_score", 0) or 0),
                        "latitude": float(row.get("latitude", 0) or 0),
                        "longitude": float(row.get("longitude", 0) or 0),
                        "summary": row.get("summary", ""),
                    }
                )
    (DOCS_DIR / "risk_points.json").write_text(
        json.dumps(
            {
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "count": len(risk_points),
                "points": risk_points,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (DOCS_DIR / "sync_status.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "source": "GitHub Actions",
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    os.environ["SKIP_PLOTS"] = "1"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    python("src/download_sentinel2_sample.py", "--skip-if-same", required=False)
    optical_changed = sentinel_updated()
    if optical_changed:
        refresh_optical()
    elif not (OUTPUT_DIR / "detected_anomalies.csv").exists():
        refresh_optical()

    insar_changed = refresh_insar()
    if optical_changed or insar_changed or not (OUTPUT_DIR / "integrated_ground_flood_risk.csv").exists():
        rebuild_risk()

    python("src/rainfall_alert.py")
    python("src/historical_flood_validation.py")
    python("src/visualize.py")
    python("src/unified_app.py")
    publish()


if __name__ == "__main__":
    main()
