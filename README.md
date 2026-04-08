# EvoStar 2026 - Friendly programme.

This repository contains a static GitHub Pages site that rebuilds the EvoStar 2026 programme from the public EasyChair page.

## What is included

- `site/index.html`: the static programme page served by GitHub Pages.
- `site/program.json`: the structured programme snapshot used by the page.
- `site/program_snapshot.txt`: the flattened EasyChair snapshot used for parsing.
- `scrape_evostar_easychair.py`: the scraper and site generator.
- `.github/workflows/update-programme.yml`: the GitHub Actions workflow that rebuilds and deploys the site.

## Local rebuild

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scrape_evostar_easychair.py --url https://easychair.org/smart-program/evostar2026/index.html --output-dir site --logo-file evo_logo.png
```

Then preview locally:

```bash
python -m http.server 8000 --directory site
```

Open `http://localhost:8000`.

## GitHub Pages deployment

The workflow is configured to:

- run on pushes to `main` or `master`
- run every hour
- allow a manual run from the GitHub Actions tab

The scheduled build generates fresh static files and deploys them directly to GitHub Pages.
