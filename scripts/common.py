"""Shared types, configuration loading, and formatting helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class ThemeColors:
    """Hex colors for one theme (dark or light)."""

    bg: str
    border: str
    titlebar: str
    title_text: str
    text: str
    accent: str
    key: str
    value: str
    dots: str
    ascii_fg: str
    cursor: str
    muted: str
    add: str
    delete: str
    # Contribution-heatmap ramp, empty -> busiest (defaults match the dark
    # theme; the light theme overrides these in config.json).
    heat: list[str] = field(
        default_factory=lambda: ["#161b22", "#1c2f4e", "#2c4a7c", "#4a76bd", "#70a5fd"]
    )


@dataclass(frozen=True)
class AsciiParams:
    """Knobs for the image -> ASCII pipeline."""

    portrait: str
    width: int
    char_aspect: float
    ramp_dark: str
    ramp_light: str | None
    bg_saturation: float
    bg_lum_floor: int
    min_region: int
    gamma: float
    edge_threshold: int
    edge_char: str
    contrast_cutoff: float
    sharpen: float = 0.0  # unsharp-mask strength; 0 disables
    dither: bool = False  # Floyd-Steinberg error diffusion
    structural: bool = False  # per-cell glyph SHAPE matching (best fidelity)
    static_art: str | None = None

    def ramp(self, theme: str) -> str:
        """Character ramp for a theme, sparse -> dense as luminance rises.

        On a dark background bright pixels should be dense glyphs; on a
        light background the mapping inverts (dense glyphs = dark ink).
        """
        if theme == "dark":
            return self.ramp_dark
        return self.ramp_light or self.ramp_dark[::-1]


@dataclass(frozen=True)
class SvgParams:
    """Geometry and typography of the rendered terminal."""

    canvas_width: int
    font_size: int
    line_height: float
    char_width: float  # advance width as a fraction of font_size
    padding: int
    column_gap: int
    font_stack: str
    cursor_blink: bool
    ascii_font_size: int | None = None  # smaller font = finer portrait grid

    @property
    def char_w(self) -> float:
        return self.font_size * self.char_width

    @property
    def line_h(self) -> float:
        return self.font_size * self.line_height

    @property
    def ascii_fs(self) -> int:
        return self.ascii_font_size or self.font_size

    @property
    def ascii_char_w(self) -> float:
        return self.ascii_fs * self.char_width

    @property
    def ascii_line_h(self) -> float:
        return self.ascii_fs * self.line_height


@dataclass
class Stats:
    """Everything dynamic that ends up in the right-hand column."""

    name: str = ""
    username: str = ""
    created_at: str = ""  # ISO datetime of account creation
    repos: int = 0
    contributed: int = 0
    stars: int = 0
    commits: int = 0
    followers: int = 0
    contributions_year: int = 0
    loc_added: int = 0
    loc_deleted: int = 0
    fetched_at: str = ""
    partial: bool = False

    @property
    def loc_net(self) -> int:
        return self.loc_added - self.loc_deleted


@dataclass(frozen=True)
class Config:
    """Parsed view of config.json."""

    username: str
    display_name: str
    birthdate: str | None
    terminal_title: str
    fields: dict[str, Any]
    ascii: AsciiParams
    svg: SvgParams
    themes: dict[str, ThemeColors]
    quotes: list[str] = field(default_factory=list)
    loc: dict[str, Any] = field(default_factory=dict)
    projects: list[dict[str, str]] = field(default_factory=list)
    languages: dict[str, Any] = field(default_factory=dict)


def load_config(path: Path | str) -> Config:
    """Load and validate config.json into typed dataclasses."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        themes = {name: ThemeColors(**colors) for name, colors in raw["themes"].items()}
        for name, theme in themes.items():
            if len(theme.heat) != 5:
                raise SystemExit(
                    f"config.json is invalid: themes.{name}.heat needs exactly 5 colors "
                    f"(got {len(theme.heat)})"
                )
        projects = raw.get("projects", [])
        for project in projects:
            project["name"]  # required; a KeyError here becomes the clean exit below
        return Config(
            username=raw["username"],
            display_name=raw["display_name"],
            birthdate=raw.get("birthdate"),
            terminal_title=raw.get("terminal_title", f"{raw['username']}@github: ~"),
            fields=raw.get("fields", {}),
            ascii=AsciiParams(**raw["ascii"]),
            svg=SvgParams(**raw["svg"]),
            themes=themes,
            quotes=raw.get("quotes", []),
            loc=raw.get("loc", {}),
            projects=projects,
            languages=raw.get("languages", {}),
        )
    except (KeyError, TypeError) as exc:
        raise SystemExit(f"config.json is invalid: {exc}") from exc


def esc(text: str) -> str:
    """XML-escape text destined for an SVG (content or attribute value)."""
    return escape(text, {'"': "&quot;"})


def format_int(n: int) -> str:
    """12345 -> '12,345'."""
    return f"{n:,}"


def ymd_diff(start: date, end: date) -> tuple[int, int, int]:
    """Calendar-accurate (years, months, days) between two dates."""
    years = end.year - start.year
    months = end.month - start.month
    days = end.day - start.day
    if days < 0:
        months -= 1
        last_of_prev = date(end.year, end.month, 1) - timedelta(days=1)
        days += last_of_prev.day
    if months < 0:
        years -= 1
        months += 12
    return years, months, days


def uptime_string(birthdate: str | None, created_at: str, today: date | None = None) -> str:
    """Human uptime line: real age if a birthdate is set, else account age."""
    today = today or date.today()
    if birthdate:
        start = date.fromisoformat(birthdate)
    elif created_at:
        start = date.fromisoformat(created_at[:10])
    else:
        return "unknown"
    years, months, days = ymd_diff(start, today)

    def plural(n: int, unit: str) -> str:
        return f"{n} {unit}{'' if n == 1 else 's'}"

    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}"
