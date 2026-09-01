"""Portrait photo -> ASCII art.

Pipeline: load -> contrast stretch -> terminal-aspect resize ->
background suppression (low-saturation flood fill from the borders) ->
Sobel edges -> luminance-to-glyph mapping.

Run standalone to preview in the terminal while tuning config values:

    python scripts/generate_ascii.py --config config.json --theme dark
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from common import AsciiParams


def load_image(path: Path | str) -> tuple[np.ndarray, np.ndarray]:
    """Load an image as (grayscale, rgb) float32 arrays in [0, 255]."""
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        gray = rgb.convert("L")
    return (
        np.asarray(gray, dtype=np.float32),
        np.asarray(rgb, dtype=np.float32),
    )


def autocontrast(arr: np.ndarray, cutoff: float) -> np.ndarray:
    """Percentile-clip contrast stretch back to the full [0, 255] range."""
    lo, hi = np.percentile(arr, [cutoff, 100.0 - cutoff])
    if hi <= lo:
        return arr
    return np.clip((arr - lo) * (255.0 / (hi - lo)), 0.0, 255.0)


def resize_for_terminal(
    gray: np.ndarray, rgb: np.ndarray, width: int, char_aspect: float
) -> tuple[np.ndarray, np.ndarray]:
    """Resize both arrays to a character grid, compensating for tall cells."""
    h, w = gray.shape
    rows = max(1, round(h / w * width * char_aspect))
    small_gray = Image.fromarray(gray.astype(np.uint8)).resize((width, rows), Image.LANCZOS)
    small_rgb = Image.fromarray(rgb.astype(np.uint8)).resize((width, rows), Image.LANCZOS)
    return (
        np.asarray(small_gray, dtype=np.float32),
        np.asarray(small_rgb, dtype=np.float32),
    )


def _majority_filter(mask: np.ndarray) -> np.ndarray:
    """Keep a cell set only if most of its 3x3 neighborhood agrees."""
    padded = np.pad(mask.astype(np.uint8), 1)
    votes = sum(
        padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
        for dy in range(3)
        for dx in range(3)
    )
    return votes >= 5


def _flood_from_borders(candidates: np.ndarray) -> np.ndarray:
    """Subset of candidate cells reachable 4-connected from any border cell."""
    mask = np.zeros_like(candidates)
    mask[0, :] = candidates[0, :]
    mask[-1, :] = candidates[-1, :]
    mask[:, 0] |= candidates[:, 0]
    mask[:, -1] |= candidates[:, -1]
    while True:
        p = np.pad(mask, 1)
        grown = (
            p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:] | mask
        ) & candidates
        if np.array_equal(grown, mask):
            return grown
        mask = grown


def background_mask(
    gray: np.ndarray, rgb: np.ndarray, saturation: float, lum_floor: int
) -> np.ndarray:
    """True where a cell belongs to the studio background.

    A studio backdrop is desaturated while skin carries color, so a cell
    is background if it is nearly gray, not too dark (the subject's dark
    clothing and hair stay), and connected to the image border.
    """
    hi = rgb.max(axis=2)
    lo = rgb.min(axis=2)
    sat = (hi - lo) / (hi + 1e-6)
    candidates = (sat < saturation) & (gray > lum_floor)
    return _majority_filter(_flood_from_borders(candidates))


def remove_small_islands(mask: np.ndarray, min_size: int) -> np.ndarray:
    """Erase foreground blobs smaller than min_size cells (stray noise)."""
    if min_size <= 1:
        return mask
    fg = ~mask
    h, w = fg.shape
    seen = np.zeros_like(fg)
    for sy in range(h):
        for sx in range(w):
            if not fg[sy, sx] or seen[sy, sx]:
                continue
            stack, blob = [(sy, sx)], [(sy, sx)]
            seen[sy, sx] = True
            while stack:
                cy, cx = stack.pop()
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < h and 0 <= nx < w and fg[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
                        blob.append((ny, nx))
            if len(blob) < min_size:
                for cy, cx in blob:
                    mask[cy, cx] = True
    return mask


def unsharp_mask(arr: np.ndarray, amount: float, radius: int = 2) -> np.ndarray:
    """Boost local contrast: arr + amount * (arr - blur(arr))."""
    if amount <= 0:
        return arr
    blur = arr
    for axis in (0, 1):  # separable box blur, applied twice ~ gaussian
        for _ in range(2):
            p = np.pad(blur, [(radius, radius) if a == axis else (0, 0) for a in (0, 1)], mode="edge")
            windows = [np.roll(p, -k, axis=axis) for k in range(2 * radius + 1)]
            blur = np.mean(windows, axis=0)
            blur = blur[tuple(slice(0, s) for s in arr.shape)]
    return np.clip(arr + amount * (arr - blur), 0.0, 255.0)


def sobel(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """3x3 Sobel: (magnitude normalized to [0, 255], gx, gy)."""
    p = np.pad(arr, 1, mode="edge")
    gx = (
        (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:])
        - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    )
    gy = (
        (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:])
        - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    )
    mag = np.hypot(gx, gy)
    peak = float(mag.max())
    if peak > 0:
        mag = mag * (255.0 / peak)
    return mag, gx, gy


def _edge_glyph(gx: float, gy: float) -> str:
    """Stroke glyph perpendicular to the gradient direction."""
    edge_angle = (math.degrees(math.atan2(gy, gx)) + 90.0) % 180.0
    if edge_angle < 22.5 or edge_angle >= 157.5:
        return "-"
    if edge_angle < 67.5:
        return "/"
    if edge_angle < 112.5:
        return "|"
    return "\\"


def _diffuse_errors(val: np.ndarray, mask: np.ndarray, levels: int) -> np.ndarray:
    """Floyd-Steinberg error diffusion over the glyph-level grid."""
    val = val.copy()
    h, w = val.shape
    top = levels - 1
    for y in range(h):
        for x in range(w):
            if mask[y, x]:
                continue
            q = min(max(round(val[y, x]), 0), top)
            err = val[y, x] - q
            val[y, x] = q
            if x + 1 < w:
                val[y, x + 1] += err * (7 / 16)
            if y + 1 < h:
                if x > 0:
                    val[y + 1, x - 1] += err * (3 / 16)
                val[y + 1, x] += err * (5 / 16)
                if x + 1 < w:
                    val[y + 1, x + 1] += err * (1 / 16)
    return val


def map_to_chars(
    arr: np.ndarray,
    mask: np.ndarray,
    edges: tuple[np.ndarray, np.ndarray, np.ndarray],
    params: AsciiParams,
    theme: str,
) -> list[str]:
    """Turn the character-grid luminance into fixed-width ASCII rows."""
    ramp = params.ramp(theme)
    levels = len(ramp)
    mag, gx, gy = edges
    # gamma > 1 lifts midtones toward the sparse end of the ramp, keeping
    # skin near-blank so only genuinely dark features (hair, eyes, brows,
    # outlines) get ink — the classic hand-drawn ASCII-portrait look.
    lum = (arr / 255.0).clip(0.0, 1.0) ** (1.0 / params.gamma)
    val = lum * (levels - 1)
    if params.dither:
        val = _diffuse_errors(val, mask, levels)
    indices = np.round(val).astype(int).clip(0, levels - 1)
    # Directional strokes replace glyphs only on strong edges in cells that
    # are not already dark ink, so outlines (jaw, nose, collar) read as pen
    # strokes without eating into solid regions like hair.
    stroke_floor = int(levels * 0.45)
    rows: list[str] = []
    for y in range(arr.shape[0]):
        chars = []
        for x in range(arr.shape[1]):
            if mask[y, x]:
                chars.append(" ")
            elif (
                params.edge_threshold > 0
                and mag[y, x] > params.edge_threshold
                and indices[y, x] >= stroke_floor
            ):
                chars.append(_edge_glyph(gx[y, x], gy[y, x]))
            else:
                chars.append(ramp[indices[y, x]])
        rows.append("".join(chars))
    return rows


def _trim_blank_rows(rows: list[str]) -> list[str]:
    """Drop fully blank rows at the top and bottom, keeping row width."""
    start, end = 0, len(rows)
    while start < end and not rows[start].strip():
        start += 1
    while end > start and not rows[end - 1].strip():
        end -= 1
    return rows[start:end]


# --- Structural glyph matching -------------------------------------------
# Instead of mapping each cell's mean luminance to a density ramp, render
# every candidate glyph as a small bitmap and pick, per cell, the glyph
# whose drawn SHAPE best matches the image patch it will replace. This is
# the technique from structure-based ASCII-art research and is what makes
# eyes, nostrils, and hair strands land as the right characters.

_GLYPH_RASTER = (6, 12)  # (w, h) pixels per cell, matches the 1:2 cell aspect
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _glyph_bitmaps(chars: str) -> tuple[str, np.ndarray]:
    """Render candidate glyphs -> (chars, coverage array [n, gh*gw] in 0..1)."""
    from PIL import ImageDraw

    gw, gh = _GLYPH_RASTER
    scale = 4
    font = _load_font(gh * scale)
    bitmaps = []
    kept = []
    for ch in chars:
        img = Image.new("L", (gw * scale, gh * scale), 0)
        draw = ImageDraw.Draw(img)
        left, top, right, bottom = draw.textbbox((0, 0), ch, font=font)
        dx = (gw * scale - (right - left)) / 2 - left
        dy = (gh * scale - (bottom - top)) / 2 - top
        draw.text((dx, dy), ch, fill=255, font=font)
        small = img.resize((gw, gh), Image.LANCZOS)
        bitmaps.append(np.asarray(small, dtype=np.float32).ravel() / 255.0)
        kept.append(ch)
    return "".join(kept), np.stack(bitmaps)


_GLYPH_POOL = "".join(chr(c) for c in range(32, 127))  # all printable ASCII


def glyph_set() -> tuple[str, np.ndarray]:
    """The full candidate pool rendered to bitmaps (cached per process)."""
    global _GLYPH_CACHE
    try:
        return _GLYPH_CACHE
    except NameError:
        _GLYPH_CACHE = _glyph_bitmaps(_GLYPH_POOL)
        return _GLYPH_CACHE


def structural_choose(
    darkness: np.ndarray, rows: int, width: int, density_weight: float
) -> np.ndarray:
    """Best glyph index per cell from shape + density scores.

    darkness: hi-res array (rows*gh, width*gw) in [0, 1], 1 = full ink.
    """
    gw, gh = _GLYPH_RASTER
    _, glyphs = glyph_set()
    densities = glyphs.mean(axis=1)
    dens_scale = float(densities.max()) or 1.0
    densities = densities / dens_scale

    patches = (
        darkness.reshape(rows, gh, width, gw).transpose(0, 2, 1, 3).reshape(-1, gh * gw)
    )
    target_density = patches.mean(axis=1)

    # Shape term: normalized cross-correlation, faded out on near-flat
    # patches so featureless skin is chosen by tone alone.
    p_centered = patches - patches.mean(axis=1, keepdims=True)
    p_norm = np.linalg.norm(p_centered, axis=1, keepdims=True)
    g_centered = glyphs - glyphs.mean(axis=1, keepdims=True)
    g_norm = np.linalg.norm(g_centered, axis=1, keepdims=True)
    g_norm[g_norm == 0] = 1.0
    safe_p_norm = np.where(p_norm == 0, 1.0, p_norm)
    ncc = (p_centered / safe_p_norm) @ (g_centered / g_norm).T
    ncc *= np.clip(patches.std(axis=1, keepdims=True) / 0.12, 0.0, 1.0)

    density_diff = np.abs(target_density[:, None] - densities[None, :])
    score = (1.0 - ncc) + density_weight * density_diff
    return score.argmin(axis=1).reshape(rows, width)


def structural_map(
    darkness: np.ndarray,
    mask: np.ndarray,
    rows: int,
    width: int,
    density_weight: float = 2.5,
) -> list[str]:
    """Glyph indices -> masked, fixed-width ASCII rows."""
    chars, _ = glyph_set()
    best = structural_choose(darkness, rows, width, density_weight)
    return [
        "".join(" " if mask[y, x] else chars[best[y, x]] for x in range(width))
        for y in range(rows)
    ]


def load_static_art(path: Path) -> list[str]:
    """Load hand-made ASCII art, normalized to equal-width printable rows."""
    rows = [
        "".join(ch if " " <= ch <= "~" else " " for ch in line.rstrip("\n").replace("\t", "    "))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    rows = _trim_blank_rows(rows)
    if not rows:
        raise SystemExit(f"static art file is empty: {path}")
    width = max(len(r) for r in rows)
    return [r.ljust(width) for r in rows]


def generate_ascii(params: AsciiParams, theme: str, base_dir: Path | str = ".") -> list[str]:
    """Full pipeline: portrait file -> list of equal-width ASCII rows.

    If `static_art` is configured and the file exists, it wins over the
    generated portrait — for hand-made or externally sourced art.
    """
    if params.static_art:
        art_path = Path(base_dir) / params.static_art
        if art_path.is_file():
            return load_static_art(art_path)
    portrait = Path(base_dir) / params.portrait
    if not portrait.is_file():
        raise SystemExit(f"portrait not found: {portrait}")
    gray, rgb = load_image(portrait)
    gray = autocontrast(gray, params.contrast_cutoff)
    cell_gray, cell_rgb = resize_for_terminal(gray, rgb, params.width, params.char_aspect)
    mask = background_mask(cell_gray, cell_rgb, params.bg_saturation, params.bg_lum_floor)
    mask = remove_small_islands(mask, params.min_region)

    if params.structural:
        gw, gh = _GLYPH_RASTER
        rows_n, width = mask.shape
        hi = Image.fromarray(gray.astype(np.uint8)).resize(
            (width * gw, rows_n * gh), Image.LANCZOS
        )
        hi_arr = unsharp_mask(np.asarray(hi, dtype=np.float32), params.sharpen, radius=gw)
        darkness = 1.0 - (hi_arr / 255.0).clip(0.0, 1.0) ** (1.0 / params.gamma)
        art = structural_map(darkness, mask, rows_n, width)
        return _trim_blank_rows(art)

    cell_gray = unsharp_mask(cell_gray, params.sharpen)
    edges = sobel(cell_gray)
    return _trim_blank_rows(map_to_chars(cell_gray, mask, edges, params, theme))


if __name__ == "__main__":
    import argparse

    from common import load_config

    parser = argparse.ArgumentParser(description="Preview the ASCII portrait")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    args = parser.parse_args()

    config = load_config(args.config)
    base = Path(args.config).resolve().parent
    for line in generate_ascii(config.ascii, args.theme, base):
        print(line)
