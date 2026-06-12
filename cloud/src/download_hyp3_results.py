from pathlib import Path
import json
import os
import urllib.error
import urllib.request
import zipfile


STATUS_PATH = Path("outputs/jeonju_hyp3_job_status.json")
INSAR_DIR = Path("data/insar")
DOWNLOAD_DIR = Path("data/insar_downloads")


def get_token() -> str:
    token = os.environ.get("HYP3_TOKEN", "").strip()
    token_path = Path("hyp3_token.txt")
    if not token and token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
    return token


def load_status() -> dict:
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def download_file(url: str, output_path: Path, token: str) -> None:
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=300) as response:
        output_path.write_bytes(response.read())


def extract_displacement_files(zip_path: Path) -> list[Path]:
    extracted = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            lower = member.lower()
            if lower.endswith(("_vert_disp.tif", "_los_disp.tif")):
                target = INSAR_DIR / Path(member).name
                target.write_bytes(archive.read(member))
                extracted.append(target)
    return extracted


def main() -> None:
    INSAR_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if not STATUS_PATH.exists():
        print("No HyP3 job status file found. Run src/check_hyp3_job.py first.")
        return

    status = load_status()
    status_code = status.get("status_code")
    print(f"HyP3 status: {status_code}")

    if status_code != "SUCCEEDED":
        print("Job is not complete yet. No files downloaded.")
        return

    files = status.get("files", [])
    if not files:
        print("Job succeeded, but no downloadable files were listed.")
        return

    token = get_token()
    downloaded = []
    extracted = []

    for file_info in files:
        url = file_info.get("url")
        filename = file_info.get("filename") or Path(url).name
        if not url or not filename.lower().endswith(".zip"):
            continue

        zip_path = DOWNLOAD_DIR / filename
        if not zip_path.exists():
            print(f"Downloading: {filename}")
            download_file(url, zip_path, token)
        downloaded.append(zip_path)
        extracted.extend(extract_displacement_files(zip_path))

    print(f"Downloaded zip files: {len(downloaded)}")
    print(f"Extracted displacement GeoTIFFs: {len(extracted)}")
    for path in extracted:
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
