"""Render the terminal-window SVG from ASCII art + stats.

The SVG is assembled from scratch on every build (no templates, no DOM
surgery). Everything is plain <text>/<tspan> in a monospace stack with
colors baked in per theme, because GitHub serves README images through
its camo proxy: no JavaScript, no external fonts, no SMIL. The only
animation is a CSS-keyframe cursor blink, which degrades to a solid
block wherever animations are not honored.
"""

from __future__ import annotations

import math
from datetime import date

from common import Config, Stats, SvgParams, ThemeColors, esc, format_int, uptime_string

# A span is (text, css_class): t=text p=accent k=key d=dots/muted-frame
# m=muted b=bold-accent a=additions r=deletions
Span = tuple[str, str]
Line = list[Span]

BAR_HEIGHT = 36
TRAFFIC_LIGHTS = ("#ff5f56", "#ffbd2e", "#27c93f")


def line_len(line: Line) -> int:
    return sum(len(text) for text, _ in line)


def _fit(value: str, budget: int) -> str:
    """Trim a value to its character budget with an ellipsis."""
    if len(value) <= budget:
        return value
    return value[: max(0, budget - 1)] + "…"


def kv(key: str, value: str, width: int, prefix: str = ". ") -> Line:
    """`. Key: ····· value` padded with dot leaders to exactly `width`."""
    fixed = len(prefix) + len(key) + 1 + 2  # prefix + "Key:" + spaces around dots
    value = _fit(value, width - fixed - 2)
    dots = "." * max(2, width - fixed - len(value))
    return [
        (prefix, "d"),
        (f"{key}:", "k"),
        (f" {dots} ", "d"),
        (value, "t"),
    ]


def kv_pair(k1: str, v1: str, k2: str, v2: str, width: int) -> Line:
    """Two dot-leader fields sharing one row, split by ` | `."""
    left_width = (width - 3) // 2
    right_width = width - 3 - left_width
    return [
        *kv(k1, v1, left_width),
        (" | ", "d"),
        *kv(k2, v2, right_width, prefix=""),
    ]


def section(label: str, width: int) -> Line:
    """`- Label ───────` divider row."""
    rule = "─" * max(0, width - len(label) - 3)
    return [("- ", "d"), (f"{label} ", "b"), (rule, "d")]


def loc_line(stats: Stats, width: int) -> Line:
    """Lines-of-code row with colored +additions / -deletions."""
    net = format_int(stats.loc_net)
    added = f"+{format_int(stats.loc_added)}"
    deleted = f"-{format_int(stats.loc_deleted)}"
    tail_len = len(net) + 2 + len(added) + 2 + len(deleted) + 2
    fixed = 2 + len("Lines of Code:") + 2
    dots = "." * max(2, width - fixed - tail_len)
    return [
        (". ", "d"),
        ("Lines of Code:", "k"),
        (f" {dots} ", "d"),
        (net, "t"),
        (" (", "d"),
        (added, "a"),
        (", ", "d"),
        (deleted, "r"),
        (")", "d"),
    ]


def stat_lines(stats: Stats, config: Config, width: int) -> list[Line]:
    """The full right-hand column as a list of span rows."""
    fields = config.fields
    host = f"{config.username}@github"
    lines: list[Line] = [
        [("$ ", "p"), ("neofetch", "t")],
        [],
        [(f"{host} ", "b"), ("─" * max(0, width - len(host) - 1), "d")],
    ]
    info_rows = [
        ("OS", fields.get("os")),
        ("Host", fields.get("host")),
        ("Kernel", fields.get("kernel")),
        ("Uptime", uptime_string(config.birthdate, stats.created_at)),
        ("Languages", fields.get("languages")),
        ("Stack", fields.get("stack")),
        ("Learning", fields.get("learning")),
        ("Interests", fields.get("interests")),
    ]
    lines += [kv(key, value, width) for key, value in info_rows if value]
    contact = fields.get("contact", [])
    if contact:
        lines += [[], section("Contact", width)]
        lines += [kv(c["key"], c["value"], width) for c in contact]
    lines += [
        [],
        section("GitHub Stats", width),
        kv_pair("Repos", format_int(stats.repos), "Stars", format_int(stats.stars), width),
        kv_pair(
            "Commits", format_int(stats.commits), "Followers", format_int(stats.followers), width
        ),
        kv("Contributed To", f"{format_int(stats.contributed)} repos", width),
        kv("Contributions", f"{format_int(stats.contributions_year)} (past year)", width),
        loc_line(stats, width),
        [],
        [("$ ", "p")],  # the blinking cursor is drawn after this prompt
    ]
    return lines


def _style(colors: ThemeColors, config: Config) -> str:
    svg = config.svg
    blink = (
        f".cursor {{ animation: blink 1.2s steps(1) infinite; }}\n"
        f"@keyframes blink {{ 0%, 49% {{ opacity: 1; }} 50%, 100% {{ opacity: 0; }} }}\n"
        f"@media (prefers-reduced-motion: reduce) {{ .cursor {{ animation: none; }} }}"
        if svg.cursor_blink
        else ""
    )
    return f"""text {{ font-family: {svg.font_stack}; font-size: {svg.font_size}px; }}
.title {{ font-size: {svg.font_size - 2}px; fill: {colors.title_text}; }}
.ascii {{ fill: {colors.ascii_fg}; font-size: {svg.ascii_fs}px; }}
.t {{ fill: {colors.text}; }}
.p {{ fill: {colors.accent}; }}
.k {{ fill: {colors.key}; }}
.d {{ fill: {colors.dots}; }}
.m {{ fill: {colors.muted}; font-style: italic; }}
.b {{ fill: {colors.accent}; font-weight: 600; }}
.a {{ fill: {colors.add}; }}
.r {{ fill: {colors.delete}; }}
.cursor {{ fill: {colors.cursor}; }}
{blink}"""


def _daily_quote(quotes: list[str]) -> str:
    if not quotes:
        return ""
    return quotes[date.today().toordinal() % len(quotes)]


def window_frame(
    colors: ThemeColors, config: Config, width: int, height: int, title: str, aria: str
) -> list[str]:
    """The terminal-window chrome: root svg, style, background, titlebar."""
    pad = config.svg.padding
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(aria)}">',
        f"<style>{_style(colors, config)}</style>",
        f'<defs><clipPath id="frame"><rect x="0.5" y="0.5" width="{width - 1}" '
        f'height="{height - 1}" rx="10"/></clipPath></defs>',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" '
        f'fill="{colors.bg}" stroke="{colors.border}"/>',
        f'<rect clip-path="url(#frame)" x="0" y="0" width="{width}" '
        f'height="{BAR_HEIGHT}" fill="{colors.titlebar}"/>',
        f'<line x1="0.5" y1="{BAR_HEIGHT + 0.5}" x2="{width - 0.5}" '
        f'y2="{BAR_HEIGHT + 0.5}" stroke="{colors.border}"/>',
    ]
    for i, light in enumerate(TRAFFIC_LIGHTS):
        parts.append(
            f'<circle cx="{pad + i * 22}" cy="{BAR_HEIGHT / 2}" r="6" fill="{light}"/>'
        )
    parts.append(
        f'<text class="title" x="{width / 2}" y="{BAR_HEIGHT / 2 + 4}" '
        f'text-anchor="middle">{esc(title)}</text>'
    )
    return parts


def render_lines(lines: list[Line], x: float, body_top: float, svg: SvgParams) -> list[str]:
    """Each Line becomes one <text> of <tspan>s at a fixed character grid."""
    parts: list[str] = []
    for row, line in enumerate(lines):
        if not line:
            continue
        tspans = "".join(f'<tspan class="{cls}">{esc(text)}</tspan>' for text, cls in line)
        length = round(line_len(line) * svg.char_w, 1)
        y = body_top + svg.font_size + row * svg.line_h
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" xml:space="preserve" '
            f'textLength="{length}" lengthAdjust="spacing">{tspans}</text>'
        )
    return parts


def cursor_rect(x: float, baseline: float, svg: SvgParams) -> str:
    """The blinking block cursor, positioned at a text baseline."""
    return (
        f'<rect class="cursor" x="{x:.1f}" y="{baseline - svg.font_size + 2:.1f}" '
        f'width="{svg.char_w:.1f}" height="{svg.font_size + 2}"/>'
    )


def render_svg(ascii_rows: list[str], stats: Stats, config: Config, theme: str) -> str:
    """Compose the complete SVG document for one theme."""
    colors = config.themes[theme]
    svg = config.svg
    char_w, line_h, pad = svg.char_w, svg.line_h, svg.padding
    width = svg.canvas_width

    art_width = max((len(r) for r in ascii_rows), default=config.ascii.width)
    col2_x = pad + art_width * svg.ascii_char_w + svg.column_gap
    col2_chars = int((width - col2_x - pad) // char_w)
    if col2_chars < 40:
        raise SystemExit(
            f"ASCII art is too wide ({art_width} chars at {svg.ascii_fs}px) — "
            f"the stats column needs at least 40 characters"
        )
    lines = stat_lines(stats, config, col2_chars)
    quote = _daily_quote(config.quotes)

    body_h = max(len(ascii_rows) * svg.ascii_line_h, len(lines) * line_h)
    quote_h = 2 * line_h if quote else 0
    height = math.ceil(BAR_HEIGHT + pad + body_h + quote_h + pad)
    body_top = BAR_HEIGHT + pad

    def baseline(row: int) -> float:
        return body_top + svg.font_size + row * line_h

    def ascii_baseline(row: int) -> float:
        return body_top + svg.ascii_fs + row * svg.ascii_line_h

    parts = window_frame(
        colors, config, width, height, config.terminal_title,
        f"{config.display_name} terminal profile",
    )

    ascii_length = round(art_width * svg.ascii_char_w, 1)
    for row, text in enumerate(ascii_rows):
        parts.append(
            f'<text class="ascii" x="{pad}" y="{ascii_baseline(row):.1f}" xml:space="preserve" '
            f'textLength="{ascii_length}" lengthAdjust="spacing">{esc(text)}</text>'
        )

    parts += render_lines(lines, col2_x, body_top, svg)

    cursor_row = len(lines) - 1
    parts.append(cursor_rect(col2_x + 2 * char_w, baseline(cursor_row), svg))

    if quote:
        quote_y = body_top + body_h + 1.2 * line_h
        parts.append(
            f'<text class="m" x="{width / 2}" y="{quote_y:.1f}" '
            f'text-anchor="middle">{esc(f"// {quote}")}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
