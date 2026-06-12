from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse
import json
import sys
import urllib.request

import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds


STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"

# Broader area around Jeonju, South Korea.
BBOX_WGS84 = [126.95, 35.72, 127.25, 35.95]
COLLECTIONS = ["sentinel-2-l2a", "sentinel-2-c1-l2a"]
FALLBACK_DATE_RANGE = "2024-05-01T00:00:00Z/2024-05-29T23:59:59Z"
MAX_CLOUD_COVER = 40


def recent_date_range(days: int = 45) -> str:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}"


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def find_items(date_range: str) -> list[dict]:
    items = []
    last_error = None

    for collection in COLLECTIONS:
        payload = {
            "collections": [collection],
            "bbox": BBOX_WGS84,
            "datetime": date_range,
            "limit": 20,
        }

        try:
            result = post_json(STAC_SEARCH_URL, payload)
        except Exception as exc:
            last_error = exc
            continue

        items.extend(result.get("features", []))

    if not items and last_error:
        raise RuntimeError(f"STAC search failed: {last_error}") from last_error

    return items


def item_datetime(item: dict) -> str:
    return item.get("properties", {}).get("datetime", "")


def item_cloud_cover(item: dict) -> float:
    return float(item.get("properties", {}).get("eo:cloud_cover", 100) or 100)


def find_latest_item(date_range: str) -> dict:
    items = find_items(date_range)
    if not items:
        raise RuntimeError(
            f"No Sentinel-2 item found for the selected area and date range: {date_range}"
        )

    low_cloud_items = [
        item for item in items if item_cloud_cover(item) <= MAX_CLOUD_COVER
    ]
    candidates = low_cloud_items if low_cloud_items else items
    return sorted(candidates, key=item_datetime, reverse=True)[0]


def choose_asset(item: dict) -> tuple[str, str]:
    assets = item.get("assets", {})

    for name in ("red", "B04", "visual"):
        asset = assets.get(name)
        if asset and asset.get("href"):
            return name, asset["href"]

    available = ", ".join(sorted(assets.keys()))
    raise RuntimeError(f"No usable image asset found. Available assets: {available}")


def find_asset_href(item: dict, names: tuple[str, ...]) -> tuple[str, str] | None:
    assets = item.get("assets", {})

    for name in names:
        asset = assets.get(name)
        if asset and asset.get("href"):
            return name, asset["href"]

    return None


def save_bbox_crop(asset_href: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(asset_href) as src:
        left, bottom, right, top = transform_bounds(
            "EPSG:4326", src.crs, *BBOX_WGS84, densify_pts=21
        )
        window = from_bounds(left, bottom, right, top, transform=src.transform)
        window = window.round_offsets().round_lengths()

        image = src.read(1, window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(
            {
                "driver": "GTiff",
                "height": image.shape[0],
                "width": image.shape[1],
                "count": 1,
                "transform": transform,
                "compress": "deflate",
            }
        )

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(image, 1)


def read_previous_item_id(metadata_path: Path) -> str | None:
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8")).get("id")
    except (json.JSONDecodeError, OSError):
        return None


def write_update_status(status: str, item: dict, metadata_path: Path) -> None:
    status_path = Path("outputs/sentinel2_server_update_status.json")
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(
            {
                "status": status,
                "id": item.get("id"),
                "datetime": item.get("properties", {}).get("datetime"),
                "cloud_cover": item.get("properties", {}).get("eo:cloud_cover"),
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "metadata_path": str(metadata_path),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-if-same",
        action="store_true",
        help="Do not download or rerun analysis if the latest server item was already used.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=45,
        help="How far back to search for new Sentinel-2 scenes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    date_range = recent_date_range()
    metadata_path = Path("data/raw/sentinel2_active_sample_metadata.json")

    try:
        item = find_latest_item(recent_date_range(args.days))
    except RuntimeError:
        date_range = FALLBACK_DATE_RANGE
        item = find_latest_item(date_range)

    previous_item_id = read_previous_item_id(metadata_path)
    current_item_id = item.get("id")

    if args.skip_if_same and previous_item_id == current_item_id:
        write_update_status("no_new_data", item, metadata_path)
        print("No new Sentinel-2 data found on the server.")
        print(f"Latest item is already analyzed: {current_item_id}")
        sys.exit(0)

    asset_name, asset_href = choose_asset(item)

    output_path = Path("data/raw/sentinel2_active_sample.tif")
    save_bbox_crop(asset_href, output_path)

    nir_asset = find_asset_href(item, ("nir", "nir08", "B08"))
    nir_output_path = None
    if nir_asset is not None:
        nir_name, nir_href = nir_asset
        nir_output_path = Path("data/raw/sentinel2_active_sample_nir.tif")
        save_bbox_crop(nir_href, nir_output_path)
    else:
        nir_name, nir_href = None, None

    metadata_path.write_text(
        json.dumps(
            {
                "id": item.get("id"),
                "collection": item.get("collection"),
                "datetime": item.get("properties", {}).get("datetime"),
                "cloud_cover": item.get("properties", {}).get("eo:cloud_cover"),
                "asset": asset_name,
                "asset_href": asset_href,
                "nir_asset": nir_name,
                "nir_asset_href": nir_href,
                "bbox_wgs84": BBOX_WGS84,
                "search_date_range": date_range,
                "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_update_status("updated", item, metadata_path)

    print(f"Downloaded crop: {output_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Item: {item.get('id')}")
    print(f"Date: {item.get('properties', {}).get('datetime')}")
    print(f"Cloud cover: {item.get('properties', {}).get('eo:cloud_cover')}")
    print(f"Asset: {asset_name}")
    if nir_output_path is not None:
        print(f"Downloaded NIR crop: {nir_output_path}")
        print(f"NIR asset: {nir_name}")


if __name__ == "__main__":
    main()
