"""Auto-tune the ASCII pipeline against the source photo.

For every parameter combination this renders the candidate art back into
an image (placing the real glyph bitmaps into their cells) and scores it
against the photo's own darkness map:

    score = 0.6 * corr(all foreground pixels)
          + 0.4 * corr(pixels of high-detail cells)   # eyes, brows, mouth

Pearson correlation is scale/shift invariant, so the metric measures how
faithfully the character mosaic reproduces the photo's structure rather
than its absolute brightness. Run:

    python scripts/tune.py [--config config.json] [--top 5]

and copy the winning values into config.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_ascii as ga
from common import load_config

GAMMAS = (1.4, 1.7, 2.0, 2.3)
SHARPENS = (0.4, 0.8, 1.2)
DENSITY_WEIGHTS = (1.5, 2.5, 3.5)
CUTOFFS = (5.0, 8.0)


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / denom if denom > 0 else 0.0


def reconstruct(best: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Paint chosen glyph bitmaps back into a hi-res ink image."""
    gw, gh = ga._GLYPH_RASTER
    _, glyphs = ga.glyph_set()
    rows, width = best.shape
    space = 0  # glyph pool starts at chr(32) == ' ' with zero coverage
    indices = np.where(mask, space, best)
    return (
        glyphs[indices.ravel()]
        .reshape(rows, width, gh, gw)
        .transpose(0, 2, 1, 3)
        .reshape(rows * gh, width * gw)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    config = load_config(args.config)
    base = Path(args.config).resolve().parent
    p = config.ascii
    gw, gh = ga._GLYPH_RASTER

    gray_full, rgb_full = ga.load_image(base / p.portrait)
    results = []
    combos = list(itertools.product(CUTOFFS, SHARPENS, GAMMAS, DENSITY_WEIGHTS))
    for i, (cutoff, sharpen, gamma, dweight) in enumerate(combos, 1):
        gray = ga.autocontrast(gray_full, cutoff)
        cell_gray, cell_rgb = ga.resize_for_terminal(gray, rgb_full, p.width, p.char_aspect)
        mask = ga.remove_small_islands(
            ga.background_mask(cell_gray, cell_rgb, p.bg_saturation, p.bg_lum_floor),
            p.min_region,
        )
        rows_n, width = mask.shape
        hi = Image.fromarray(gray.astype(np.uint8)).resize(
            (width * gw, rows_n * gh), Image.LANCZOS
        )
        hi_arr = ga.unsharp_mask(np.asarray(hi, dtype=np.float32), sharpen, radius=gw)
        darkness = 1.0 - (hi_arr / 255.0).clip(0.0, 1.0) ** (1.0 / gamma)
        best = ga.structural_choose(darkness, rows_n, width, dweight)
        recon = reconstruct(best, mask)

        # Photo-true target (no gamma): what the mosaic should resemble.
        target = 1.0 - (hi_arr / 255.0).clip(0.0, 1.0)
        cell_mask_px = np.kron(mask, np.ones((gh, gw), dtype=bool))
        fg = ~cell_mask_px
        detail = (
            target.reshape(rows_n, gh, width, gw).std(axis=(1, 3)) > 0.10
        )  # high-detail cells: feature regions
        detail_px = np.kron(detail & ~mask, np.ones((gh, gw), dtype=bool))

        global_corr = _pearson(recon[fg], target[fg])
        detail_corr = (
            _pearson(recon[detail_px], target[detail_px]) if detail_px.any() else 0.0
        )
        score = 0.6 * global_corr + 0.4 * detail_corr
        results.append((score, global_corr, detail_corr, cutoff, sharpen, gamma, dweight))
        print(
            f"[{i:2d}/{len(combos)}] cutoff={cutoff} sharpen={sharpen} "
            f"gamma={gamma} dweight={dweight} -> {score:.4f} "
            f"(global {global_corr:.4f}, detail {detail_corr:.4f})",
            file=sys.stderr,
        )

    results.sort(reverse=True)
    print("\nTop candidates:")
    for score, g, d, cutoff, sharpen, gamma, dweight in results[: args.top]:
        print(
            f"  score={score:.4f}  contrast_cutoff={cutoff}  sharpen={sharpen}  "
            f"gamma={gamma}  density_weight={dweight}  (global {g:.4f} / detail {d:.4f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
