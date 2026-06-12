from pathlib import Path
import json
import os
import sys
import urllib.error
import urllib.request


HYP3_JOBS_URL = "https://hyp3-api.asf.alaska.edu/jobs"


def get_token() -> str:
    token = os.environ.get("HYP3_TOKEN", "").strip()
    token_path = Path("hyp3_token.txt")
    if not token and token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
    return token


def main() -> None:
    if len(sys.argv) > 1:
        job_id = sys.argv[1]
    else:
        response_path = Path("outputs/jeonju_hyp3_submit_response.json")
        data = json.loads(response_path.read_text(encoding="utf-8"))
        job_id = data["jobs"][0]["job_id"]

    request = urllib.request.Request(f"{HYP3_JOBS_URL}/{job_id}", method="GET")
    token = get_token()
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} {exc.reason}")
        print(error_body)
        return

    output_path = Path("outputs/jeonju_hyp3_job_status.json")
    output_path.write_text(body, encoding="utf-8")
    data = json.loads(body)
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
