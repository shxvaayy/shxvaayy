# Setup

This repo is fully self-contained: after cloning, the profile builds with
one command and the GitHub Action keeps it fresh with **zero manual steps**.

## Requirements

- Python 3.10+ (CI uses 3.12)
- `pip install -r requirements.txt` (Pillow + NumPy — the only dependencies)

## Local build

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Full build (needs a token for live stats — any of these works):
GH_TOKEN=$(gh auth token) python scripts/build.py

# Or without network access — reuses generated/stats_cache.json:
python scripts/build.py --offline
```

Outputs land in `generated/dark_mode.svg` and `generated/light_mode.svg`.
Open them in a browser to preview. To preview only the ASCII portrait in
your terminal (fast tuning loop):

```bash
python scripts/generate_ascii.py --theme dark
```

## GitHub Actions (automatic)

`.github/workflows/build.yml` runs:

- daily at 04:00 UTC,
- on every push to `main` (except pushes that only touch `generated/`),
- on demand via **Actions → Build profile terminal → Run workflow**.

It regenerates both SVGs and commits them only when something changed.
The default `GITHUB_TOKEN` is enough for all public statistics.

### Optional: private contribution counts

Public data needs no setup. If you want `Contributions` to include
private-repo activity:

1. Create a **classic PAT** with `repo` + `read:user` scopes.
2. Save it as a repo secret named `ACCESS_TOKEN`
   (Settings → Secrets and variables → Actions).
3. Also enable *Settings → Profile → Include private contributions*.

The workflow automatically prefers `ACCESS_TOKEN` when it exists.

## Using this for your own profile

1. Fork/copy this repo to `<your-username>/<your-username>`.
2. Replace `assets/portrait.jpg` with your photo (square, ~800×800 works best).
3. Edit `config.json` — at minimum `username`, `display_name`, `birthdate`
   (or set it to `null` to show GitHub account age), `fields`, and the two
   raw URLs in `README.md`.
4. Delete `generated/loc_cache.json` and `generated/stats_cache.json` so
   the first Action run scans your repositories.
5. Push. Done.

See [CUSTOMIZATION.md](CUSTOMIZATION.md) for every knob and
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) if anything looks off.
