from pathlib import Path
import json
import os
import urllib.error
import urllib.request


HYP3_JOBS_URL = "https://hyp3-api.asf.alaska.edu/jobs"

REFERENCE_GRANULE = (
    "S1A_IW_SLC__1SDV_20240518T093202_20240518T093216_053924_068DFA_C856"
)
SECONDARY_GRANULE = (
    "S1A_IW_SLC__1SDV_20240506T093203_20240506T093230_053749_0687E1_8AEF"
)


def build_job_payload() -> dict:
    return {
        "jobs": [
            {
                "name": "jeonju-insar-20240506-20240518",
                "job_type": "INSAR_GAMMA",
                "job_parameters": {
                    "granules": [REFERENCE_GRANULE, SECONDARY_GRANULE],
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


def main() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_job_payload()
    payload_path = output_dir / "jeonju_hyp3_insar_job_payload.json"
    payload_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    request = urllib.request.Request(
        HYP3_JOBS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    token = os.environ.get("HYP3_TOKEN", "").strip()

    token_path = Path("hyp3_token.txt")
    if not token and token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()

    if token:
        request.add_header("Authorization", f"Bearer {token}")
    else:
        print("No HYP3_TOKEN env var or hyp3_token.txt file found.")
        print("Submitting without token to check authentication status.")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        error_path = output_dir / "jeonju_hyp3_submit_error.txt"
        error_path.write_text(
            f"HTTP {exc.code} {exc.reason}\n\n{error_body}", encoding="utf-8"
        )

        print(f"Saved job payload: {payload_path}")
        print(f"HyP3 submit failed: HTTP {exc.code} {exc.reason}")
        print(f"Saved error details: {error_path}")
        return

    response_path = output_dir / "jeonju_hyp3_submit_response.json"
    response_path.write_text(body, encoding="utf-8")
    print(f"Saved job payload: {payload_path}")
    print(f"Saved HyP3 response: {response_path}")


if __name__ == "__main__":
    main()
