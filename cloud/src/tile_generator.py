from pathlib import Path

import numpy as np

from preprocess import load_first_band


TILE_SIZE = 64


def generate_tiles(image: np.ndarray, tile_size: int = TILE_SIZE) -> np.ndarray:
    tiles = []
    height, width = image.shape

    for row in range(0, height - tile_size + 1, tile_size):
        for col in range(0, width - tile_size + 1, tile_size):
            tile = image[row : row + tile_size, col : col + tile_size]
            tiles.append(tile)

    return np.array(tiles, dtype=np.float32)


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

    image, _ = load_first_band(candidates[0])
    tiles = generate_tiles(image)

    output_path = Path("data/tiles/tiles.npy")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, tiles)

    print(f"Loaded: {candidates[0]}")
    print(f"Tile size: {TILE_SIZE}x{TILE_SIZE}")
    print(f"Tiles: {tiles.shape}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
