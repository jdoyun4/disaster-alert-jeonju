from pathlib import Path
import os

import matplotlib.pyplot as plt
import numpy as np
import rasterio


def normalize_band(band: np.ndarray) -> np.ndarray:
    band = band.astype(np.float32)
    valid = np.isfinite(band)

    if not valid.any():
        return np.zeros_like(band, dtype=np.float32)

    min_value = band[valid].min()
    max_value = band[valid].max()

    if max_value == min_value:
        return np.zeros_like(band, dtype=np.float32)

    normalized = (band - min_value) / (max_value - min_value)
    normalized[~valid] = 0
    return normalized


def load_first_band(path: str | Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        band = src.read(1)
        profile = src.profile.copy()

    return normalize_band(band), profile


def save_preview(image: np.ndarray, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(8, 8))
    plt.imshow(image, cmap="gray")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close()


def main() -> None:
    raw_dir = Path("data/raw")
    candidates = (
        sorted(raw_dir.glob("sentinel2_active_sample.tif"))
        + sorted(raw_dir.glob("sentinel2*.tif"))
        + sorted(raw_dir.glob("*.tif"))
        + sorted(raw_dir.glob("*.tiff"))
    )

    if not candidates:
        print("No GeoTIFF file found in data/raw.")
        print("Put a .tif or .tiff file in data/raw, then run this script again.")
        return

    image, profile = load_first_band(candidates[0])
    if os.environ.get("SKIP_PLOTS") != "1":
        save_preview(image, "outputs/first_band_preview.png")

    print(f"Loaded: {candidates[0]}")
    print(f"Shape: {image.shape}")
    print(f"CRS: {profile.get('crs')}")
    print("Saved preview: outputs/first_band_preview.png")


if __name__ == "__main__":
    main()
