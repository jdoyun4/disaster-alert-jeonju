# Disaster Alert Cloud

This directory runs the Jeonju natural-disaster risk analysis without a laptop.

- Sentinel-2 optical scenes are checked automatically.
- Open-Meteo rainfall forecasts are refreshed.
- HyP3 InSAR jobs are submitted and monitored when `HYP3_TOKEN` is configured.
- Updated maps and JSON files are published through GitHub Pages.

The Android app reads the published files over either Wi-Fi or mobile data.
