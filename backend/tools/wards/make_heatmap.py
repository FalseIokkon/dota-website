#!/usr/bin/env python3
"""
make_heatmaps_by_patch.py

Generate one transparent heatmap PNG per patch from ward CSV.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from scipy.ndimage import gaussian_filter
except ImportError:
    gaussian_filter = None

# Make backend/ importable
BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(BACKEND_ROOT))

from app.config import PROJECT_ROOT  # noqa: E402

INPUT_CSV = PROJECT_ROOT / "data" / "exports" / "wards" / "extract_observer_wards.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "derived" / "heatmaps"

BINS = 128
SMOOTH_SIGMA = 1.5

FIGSIZE = (1800 / 100, 1800 / 100)
DPI = 100

# Visibility tuning
BRIGHTNESS_POWER = 0.5   # lower than 1 = brighter
ALPHA_MULTIPLIER = 1.8   # higher = more visible
MIN_VISIBLE_ALPHA = 0.12 # ensures faint areas still show


def generate_heatmap(df: pd.DataFrame, output_path: Path, title: str) -> None:
    x = df["x"].to_numpy()
    y = df["y"].to_numpy()

    heatmap, _, _ = np.histogram2d(x, y, bins=BINS)

    if gaussian_filter is not None:
        heatmap = gaussian_filter(heatmap, sigma=SMOOTH_SIGMA)

    max_value = heatmap.max()
    if max_value > 0:
        heatmap = heatmap / max_value
        heatmap = np.power(heatmap, BRIGHTNESS_POWER)

    alpha = np.clip(heatmap.T * ALPHA_MULTIPLIER, 0, 1)
    alpha[alpha > 0] = np.maximum(alpha[alpha > 0], MIN_VISIBLE_ALPHA)

    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])

    ax.imshow(
        heatmap.T,
        origin="lower",
        cmap="inferno",
        alpha=alpha,
        interpolation="bilinear",
    )

    ax.set_axis_off()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        output_path,
        dpi=DPI,
        transparent=True,
        pad_inches=0,
    )
    plt.close(fig)


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Missing CSV: {INPUT_CSV}")

    df = pd.read_csv(INPUT_CSV)

    required = {"x", "y", "patch"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    df = df[["x", "y", "patch"]].dropna()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    grouped = df.groupby("patch")
    print(f"Found {len(grouped)} patches")

    for patch, group in grouped:
        if len(group) < 10:
            continue

        output_path = OUTPUT_DIR / f"observer_patch_{patch}.png"
        title = f"Observer Ward Heatmap (Patch {patch})"

        generate_heatmap(group, output_path, title)
        print(f"Saved: {output_path} ({len(group)} points)")


if __name__ == "__main__":
    main()