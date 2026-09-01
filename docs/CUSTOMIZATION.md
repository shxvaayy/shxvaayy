# Customization

Everything is driven by `config.json` — no code changes needed for the
common tweaks.

## Identity

| Key | Meaning |
| --- | --- |
| `username` | GitHub login used for all API queries |
| `display_name` | Fallback name if the API is unreachable |
| `birthdate` | `YYYY-MM-DD` for the `Uptime` line; `null` → GitHub account age |
| `terminal_title` | Text in the terminal title bar |

## `fields` — the neofetch column

`os`, `host`, `kernel`, `languages`, `stack`, `learning`, `interests` are
free-form strings; omit any of them to drop the row. `contact` is a list of
`{ "key": ..., "value": ... }` rows. Values that don't fit the column are
truncated with an ellipsis, so keep them under ~35 characters.

## `ascii` — the portrait pipeline

| Key | Meaning | Tuning hint |
| --- | --- | --- |
| `portrait` | Path to the source photo | Square photos work best |
| `width` | Portrait width in characters | 45–65; higher = more detail, wider column |
| `char_aspect` | Height/width ratio of a terminal cell | 0.5 for most monospace fonts |
| `ramp_dark` | Glyphs from sparse → dense (dark theme) | Longer ramp = smoother shading |
| `ramp_light` | Same for light theme; `null` = reversed `ramp_dark` | |
| `bg_saturation` | Max color saturation to count as backdrop | Raise if backdrop survives |
| `bg_lum_floor` | Min luminance to count as backdrop | Lower it to eat dark backdrops; raise it if clothing develops holes |
| `min_region` | Erase foreground islands smaller than this | Kills stray specks |
| `gamma` | Midtone rolloff; higher = more blank skin | 1.8–2.4 |
| `sharpen` | Unsharp-mask strength; boosts facial features | 0.5–1.2; 0 disables |
| `structural` | Pick glyphs by drawn **shape**, not just density | Best fidelity; the flags below only apply when it's off |
| `dither` | Floyd–Steinberg shading (non-structural mode) | |
| `edge_threshold` | Directional stroke overlay (non-structural mode); `0` disables | 60–120 |
| `edge_char` | Legacy fixed edge glyph | unused when strokes are directional |
| `contrast_cutoff` | Percentile clipped on each end | 2–8 |

Preview loop while tuning: `python scripts/generate_ascii.py --theme dark`.

Automatic tuning: `python scripts/tune.py` grid-searches `contrast_cutoff`,
`sharpen`, `gamma`, and the shape/tone weight, scoring each candidate by
reconstructing the character mosaic and correlating it against the photo
itself. Copy the winning values into `config.json` — but always eye-check
the top candidates: past a point the metric rewards over-sharpening that
looks noisy to a human.

### Hand-made art override

If `ascii.static_art` points to an existing file (default
`assets/portrait_ascii.txt`), its contents replace the generated portrait
entirely — use this for hand-drawn or externally sourced ASCII art. Plain
ASCII only (non-ASCII characters become spaces), up to ~60 characters
wide; lines are padded to equal width automatically and the layout adapts.
Delete the file to go back to the generated portrait.

The background remover assumes a studio-style photo: a desaturated,
reasonably bright backdrop that touches the image borders. For busy
backgrounds, pre-cut the photo (e.g. macOS "Remove Background" quick
action) and export it on a plain white backdrop.

## `svg` — geometry & typography

`canvas_width`, `font_size`, `line_height`, `char_width` (advance width as
a fraction of font size — 0.6 fits every common monospace), `padding`,
`column_gap`, `font_stack` (keep it self-contained: GitHub's image proxy
blocks external fonts), and `cursor_blink` (set `false` for a static block).

## `themes` — colors

`themes.dark` and `themes.light` each define every color in the render:
`bg`, `border`, `titlebar`, `title_text`, `text`, `accent` (prompt, name,
section headers), `key`, `value`, `dots` (leader dots and frame glyphs),
`ascii_fg` (the portrait), `cursor`, `muted` (quote), `add`/`delete`
(the LOC `+/-` counters). Add more themes by extending the object and
calling `build.py --theme <name>` — the workflow builds `dark` and `light`.

## `quotes`

A local list; one is picked deterministically per day
(`day_ordinal % len(quotes)`). No external quote API involved.

## `loc` — lines-of-code scan

`include_forks` (default `false`), `exclude_repos` (list of
`owner/name` to skip), `max_pages_per_repo` (100 commits per page;
protects the API budget on huge repos).

## Optional extras

Want the contribution snake or other animated widgets under the terminal?
Add any external widget as a normal line in `README.md` below the
`<picture>` block — the generator never touches the README. For example
[Platane/snk](https://github.com/Platane/snk) can run as a second,
independent workflow.
