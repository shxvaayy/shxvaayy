"""Extra terminal windows rendered below the hero.

Two panels, same chrome and span grammar as the hero window:
- projects: `$ ls ~/projects --sort=favorite` with curated project cards
  from config.json, enriched with per-repo commit/LOC tails from the
  already-committed loc_cache.json (zero extra API calls).
- activity: `$ ./activity.sh --last-year` with a hand-drawn contribution
  heatmap (blue ramp, one <rect> per day) beside top-language share bars
  in block characters, closed by the session's final blinking cursor.

Same camo constraints as the hero: everything baked at build time, CSS
keyframes only.
"""

from __future__ import annotations

import math
from typing import Any

from common import Config, Stats, format_int
from generate_svg import (
    BAR_HEIGHT,
    Line,
    _fit,
    cursor_rect,
    kv,
    render_lines,
    window_frame,
)

# Projects panel: column budgets in characters.
NAME_COL = 18
TAG_COL = 24
MIN_COMMITS = 5  # suppress the commits/LOC tail below this (shallow caches)

# Activity panel: heatmap geometry in px.
CELL = 9
STEP = 11  # cell + gutter
WEEKS = 53
LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}
BAR_CHARS = 16
LANG_LIMIT = 5


def _compact(n: int) -> str:
    """287062 -> '287.1k'."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _project_lines(config: Config, loc_cache: dict[str, Any], width: int) -> list[Line]:
    lines: list[Line] = [
        [("$ ", "p"), ("ls ~/projects --sort=favorite", "t")],
        [],
    ]
    for project in config.projects:
        entry = loc_cache.get(project.get("repo", ""), {})
        row: Line = [
            ("  ", "d"),
            (_fit(project["name"], NAME_COL - 1).ljust(NAME_COL), "b"),
            (_fit(project.get("tag", ""), TAG_COL - 1).ljust(TAG_COL), "k"),
        ]
        if entry.get("commits", 0) >= MIN_COMMITS:
            row.append(
                (f"{entry['commits']} commits · +{_compact(entry['additions'])} LOC", "m")
            )
        lines.append(row)
        lines.append([("  └─ ", "d"), (_fit(project.get("tagline", ""), width - 5), "t")])
        lines.append([])
    return lines[:-1] if config.projects else lines


def render_projects_svg(config: Config, loc_cache: dict[str, Any], theme: str) -> str:
    """The `~/projects` window: one card per curated project."""
    colors = config.themes[theme]
    svg = config.svg
    width, pad = svg.canvas_width, svg.padding
    chars = int((width - 2 * pad) // svg.char_w)

    lines = _project_lines(config, loc_cache, chars)
    height = math.ceil(BAR_HEIGHT + pad + len(lines) * svg.line_h + pad)

    parts = window_frame(
        colors, config, width, height, f"{config.terminal_title}/projects",
        f"{config.display_name} — selected projects",
    )
    parts += render_lines(lines, pad, BAR_HEIGHT + pad, svg)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _language_lines(
    languages: dict[str, int], width: int, exclude: set[str] = frozenset()
) -> list[Line]:
    """`TypeScript  ██████████░░░░░░  38.4%` rows, top languages by bytes."""
    languages = {k: v for k, v in languages.items() if k not in exclude}
    total = sum(languages.values())
    if not total:
        return []
    top = sorted(languages.items(), key=lambda kv: -kv[1])[:LANG_LIMIT]
    label_w = width - BAR_CHARS - 8  # bar + two gaps + ' 38.4%'
    peak = top[0][1]
    lines: list[Line] = []
    for name, size in top:
        fill = max(1, round(size / peak * BAR_CHARS))
        share = 100 * size / total
        lines.append(
            [
                (_fit(name, label_w - 1).ljust(label_w), "k"),
                ("█" * fill, "p"),
                ("░" * (BAR_CHARS - fill), "d"),
                (f" {share:4.1f}%", "m"),
            ]
        )
    return lines


def render_activity_svg(
    config: Config,
    stats: Stats,
    weeks: list[dict[str, Any]],
    languages: dict[str, int],
    theme: str,
) -> str:
    """The activity window: contribution heatmap + language bars + cursor."""
    colors = config.themes[theme]
    svg = config.svg
    width, pad = svg.canvas_width, svg.padding
    line_h, font_size = svg.line_h, svg.font_size
    body_top = BAR_HEIGHT + pad
    chars = int((width - 2 * pad) // svg.char_w)

    head: list[Line] = [
        [("$ ", "p"), ("./activity.sh --last-year", "t")],
        [],
        kv("Contributions", f"{format_int(stats.contributions_year)} in the last 12 months", chars),
        [],
    ]

    # All geometry is known up front: header rows, then heatmap grid on the
    # left with its legend, language bars on the right, closing prompt.
    grid_w = WEEKS * STEP - (STEP - CELL)
    grid_top = body_top + len(head) * line_h + 2
    grid_bottom = grid_top + 7 * STEP - (STEP - CELL)
    legend_baseline = grid_bottom + line_h
    col2_x = pad + grid_w + svg.column_gap
    col2_chars = int((width - col2_x - pad) // svg.char_w)
    if col2_chars < 32:
        raise SystemExit(
            f"canvas is too narrow ({width}px) — the activity panel's language "
            f"column needs at least 32 characters next to the heatmap"
        )
    lang_lines = _language_lines(
        languages, col2_chars, set(config.languages.get("exclude", []))
    )
    lang_bottom = grid_top - 2 + len(lang_lines) * line_h
    prompt_baseline = max(legend_baseline, lang_bottom) + 1.6 * line_h
    height = math.ceil(prompt_baseline + (line_h - font_size) + pad)

    parts = window_frame(
        colors, config, width, height, config.terminal_title,
        f"{config.display_name} — contribution heatmap and top languages",
    )
    parts += render_lines(head, pad, body_top, svg)

    # Heatmap: one rounded rect per day, GitHub's own quartile bucketing.
    for w, week in enumerate(weeks[-WEEKS:]):
        for day in week.get("contributionDays", []):
            level = LEVELS.get(day.get("contributionLevel", "NONE"), 0)
            x = pad + w * STEP
            y = grid_top + day.get("weekday", 0) * STEP
            parts.append(
                f'<rect x="{x}" y="{y:.1f}" width="{CELL}" height="{CELL}" rx="2" '
                f'fill="{colors.heat[level]}"/>'
            )

    # Legend: `less ▢▢▢▢▢ more` under the grid.
    parts.append(
        f'<text class="m" x="{pad}" y="{legend_baseline:.1f}">less</text>'
    )
    swatch_x = pad + 4 * svg.char_w + 8
    for level, color in enumerate(colors.heat):
        parts.append(
            f'<rect x="{swatch_x + level * (CELL + 4):.1f}" '
            f'y="{legend_baseline - CELL:.1f}" width="{CELL}" height="{CELL}" rx="2" '
            f'fill="{color}"/>'
        )
    parts.append(
        f'<text class="m" x="{swatch_x + len(colors.heat) * (CELL + 4) + 8:.1f}" '
        f'y="{legend_baseline:.1f}">more</text>'
    )

    # Language share bars, top-aligned with the heatmap.
    parts += render_lines(lang_lines, col2_x, grid_top - 2, svg)

    # Closing prompt: the session's final blinking cursor.
    parts.append(
        f'<text x="{pad}" y="{prompt_baseline:.1f}" xml:space="preserve" '
        f'textLength="{round(2 * svg.char_w, 1)}" lengthAdjust="spacing">'
        f'<tspan class="p">$ </tspan></text>'
    )
    parts.append(cursor_rect(pad + 2 * svg.char_w, prompt_baseline, svg))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
