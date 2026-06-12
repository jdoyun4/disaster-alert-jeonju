from pathlib import Path
import json
import os
import urllib.error
import urllib.request


HYP3_JOBS_URL = "https://hyp3-api.asf.alaska.edu/jobs"
JOB_PREFIX = "jeonju-insar"
OUTPUT_DIR = Path("outputs")


def get_token() -> str:
    token = os.environ.get("HYP3_TOKEN", "").strip()
    token_path = Path("hyp3_token.txt")
    if not token and token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
    return token


def request_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_job(jobs: list[dict]) -> dict | None:
    matching = [
        job for job in jobs
        if str(job.get("name", "")).lower().startswith(JOB_PREFIX)
    ]
    if not matching:
        return None

    return sorted(matching, key=lambda job: job.get("request_time", ""), reverse=True)[0]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    token = get_token()

    if not token:
        print("No hyp3_token.txt found. Cannot check HyP3 job status.")
        return

    try:
        recent = request_json(f"{HYP3_JOBS_URL}?limit=20", token)
    except urllib.error.HTTPError as exc:
        print(f"HyP3 job list check failed: HTTP {exc.code} {exc.reason}")
        print(exc.read().decode("utf-8", errors="replace"))
        return

    jobs = recent.get("jobs", [])
    chosen = choose_job(jobs)
    (OUTPUT_DIR / "hyp3_recent_jobs.json").write_text(
        json.dumps(recent, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if chosen is None:
        print(f"No HyP3 job starting with {JOB_PREFIX} found.")
        return

    job_id = chosen["job_id"]
    status = request_json(f"{HYP3_JOBS_URL}/{job_id}", token)
    (OUTPUT_DIR / "jeonju_hyp3_job_status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    status_code = status.get("status_code")
    print(f"Selected job: {job_id}")
    print(f"Status: {status_code}")

    marker = OUTPUT_DIR / "JEONJU_INSAR_READY.txt"
    if status_code == "SUCCEEDED":
        marker.write_text(
            f"{job_id}\n",
            encoding="utf-8",
        )
    elif marker.exists():
        marker.unlink()


if __name__ == "__main__":
    main()
