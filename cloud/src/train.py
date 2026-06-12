from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


TILE_SIZE = 64
INPUT_SIZE = TILE_SIZE * TILE_SIZE


class AutoEncoder(nn.Module):
    def __init__(self) -> None:
        super().__init__()

        self.encoder = nn.Sequential(
            nn.Linear(INPUT_SIZE, 512),
            nn.ReLU(),
            nn.Linear(512, 128),
            nn.ReLU(),
        )

        self.decoder = nn.Sequential(
            nn.Linear(128, 512),
            nn.ReLU(),
            nn.Linear(512, INPUT_SIZE),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(x)
        return self.decoder(encoded)


def main() -> None:
    tiles_path = Path("data/tiles/tiles.npy")

    if not tiles_path.exists():
        print("No tiles found at data/tiles/tiles.npy.")
        print("Run src/tile_generator.py after placing a GeoTIFF in data/raw.")
        return

    tiles = np.load(tiles_path).astype(np.float32)
    tiles = tiles.reshape(len(tiles), -1)

    dataset = TensorDataset(torch.from_numpy(tiles))
    loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model = AutoEncoder()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    epochs = 10
    for epoch in range(epochs):
        total_loss = 0.0

        for (batch,) in loader:
            reconstruction = model(batch)
            loss = criterion(reconstruction, batch)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * len(batch)

        average_loss = total_loss / len(dataset)
        print(f"Epoch {epoch + 1}/{epochs} - loss: {average_loss:.6f}")

    output_path = Path("models/autoencoder.pt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), output_path)
    print(f"Saved model: {output_path}")


if __name__ == "__main__":
    main()
