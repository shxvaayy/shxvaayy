# Troubleshooting

## The profile shows stale numbers

GitHub serves README images through its **camo** caching proxy, which can
cache aggressively (minutes to hours). The SVGs in the repo are already
updated; the proxy just hasn't refreshed. Force it:

```bash
# Copy the camo URL (right-click the image on your profile → Copy Image Address)
curl -X PURGE https://camo.githubusercontent.com/<hash>
```

Or simply wait — it clears on its own.

## The Action ran but didn't commit

That's the no-op guard: if the regenerated SVGs are byte-identical
(stats unchanged), nothing is committed. The run log prints
`No changes to commit.` The `Uptime` line changes daily, so scheduled
runs normally always commit.

## `Uptime`, `Commits`, or `Lines of Code` look wrong

- **Commits / LOC** only count commits *you authored* on the **default
  branch** of repos you own (forks excluded by default). Work on other
  branches or squash-merged under a different author email won't count.
- Commits with no linked GitHub account (wrong git email) are skipped —
  add the email at Settings → Emails.
- To force a full rescan, delete `generated/loc_cache.json`.
- **Contributions** includes private activity only with the optional
  `ACCESS_TOKEN` PAT (see [SETUP.md](SETUP.md)).

## API rate limits

GraphQL allows ~5,000 points/hour. The expensive part is the first-ever
LOC scan (it walks every commit); afterwards only repos with new pushes
are rescanned. If a scheduled run hits the limit mid-scan, it logs the
failure, reuses cached values, and repairs itself on the next run. Big
repos are capped by `loc.max_pages_per_repo` (default 30 pages = 3,000
commits) and log a `truncated` warning.

## The ASCII portrait looks bad

Tune and preview locally (instant feedback):

```bash
python scripts/generate_ascii.py --theme dark
```

| Symptom | Fix |
| --- | --- |
| Backdrop noise around the head | Raise `ascii.bg_saturation` (e.g. 0.20) or lower `bg_lum_floor` |
| Holes inside clothing/hair | Raise `bg_lum_floor` (backdrop must stay brighter than clothes) |
| Stray specks in corners | Raise `min_region` |
| Face too flat | Raise `contrast_cutoff` to 3–5, or use a longer character ramp |
| Portrait too small/large | Change `ascii.width` (the layout adapts automatically) |

## Columns misaligned / text overflows in some viewer

Every row carries `textLength`, so browsers that honor it (Chrome,
Firefox, Safari) render a perfect grid even when the font falls back.
Quick-look style previewers may ignore it — judge alignment in a real
browser. Keep `svg.char_width` at `0.6` unless you know your font stack.

## The blinking cursor doesn't blink

Some renderers strip or ignore CSS animation inside `<img>`-embedded
SVGs, and `prefers-reduced-motion` disables it on purpose. It degrades
to a solid block — that's expected behavior, not a bug.
