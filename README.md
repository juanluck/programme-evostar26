# EvoStar 2026 Friendly programme

Static GitHub Pages site for a friendlier public view of the EvoStar 2026 EasyChair programme.

Source URL:
- https://easychair.org/smart-program/evostar2026/index.html

## What this repo contains

- `scrape_evostar_easychair.py`: scraper + static site generator
- `site/`: generated GitHub Pages output
- `.github/workflows/update-programme.yml`: hourly and on-push rebuild + deploy workflow

## Local rebuild

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scrape_evostar_easychair.py \
  --url https://easychair.org/smart-program/evostar2026/index.html \
  --output-dir site \
  --logo-file evo_logo.png \
  --min-sessions 40 \
  --min-talks 100
```

## GitHub Pages setup

1. Create or open your GitHub repository.
2. Upload all files from this project to the repository root.
3. Go to **Settings → Pages**.
4. Under **Build and deployment**, set **Source** to **GitHub Actions**.
5. Push to `main` or `master`.
6. Open the **Actions** tab and check that the workflow `Update and deploy friendly programme` succeeds.
7. Once deployed, the site will be available at:
   - `https://YOUR-USER.github.io/YOUR-REPO/`

## Update policy

The workflow runs:
- on every push to `main` or `master`
- every hour at minute 17 (UTC)
- manually from the **Actions** tab

## Why the workflow uploads a tar.gz artifact

GitHub Pages accepts an Actions artifact named `github-pages` that is a single gzip archive containing a single tar file. This repo packages the site explicitly and uploads it with `actions/upload-artifact@v6`.

That avoids the Node 20 deprecation warning caused by older artifact-upload actions and keeps the workflow aligned with the current Node 24-compatible action releases.

## Safety guard

The scraper fails intentionally if it parses fewer than:
- 40 sessions
- 100 talks

This prevents an empty or broken scrape from being deployed over a working site.
