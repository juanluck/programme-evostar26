# EvoStar 2026 friendly programme

Static GitHub Pages site for a friendlier public programme view of the EasyChair schedule.

## What changed in this version

- More robust session parsing: it now accepts session headers even when EasyChair does not expose them as clickable links.
- Safety guard in CI: if a scheduled scrape returns suspiciously few sessions or talks, the workflow fails instead of publishing an empty programme.
- Rebuilds on every push and once per hour.

## Local build

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scrape_evostar_easychair.py   --url https://easychair.org/smart-program/evostar2026/index.html   --output-dir site   --logo-file evo_logo.png   --min-sessions 40   --min-talks 100
```

## Deploy on GitHub Pages

1. Create a GitHub repository.
2. Upload all files from this folder to the repository root.
3. In GitHub, open **Settings → Pages**.
4. Under **Build and deployment**, choose **GitHub Actions** as the source.
5. Push to `main` or `master`.
6. Open the **Actions** tab and wait for **Update and deploy friendly programme** to finish.
7. Your site will be published at:
   `https://YOUR-USER.github.io/YOUR-REPOSITORY/`

## Updating an existing broken repo

1. Delete the old workflow in `.github/workflows/`.
2. Replace `scrape_evostar_easychair.py` with the one in this package.
3. Replace the whole `site/` folder with the one in this package.
4. Add `requirements.txt` if it is missing.
5. Commit and push.
6. In GitHub, run the workflow manually once from **Actions → Update and deploy friendly programme → Run workflow**.

## Notes

- The workflow runs every hour at minute 17 (UTC-based cron in GitHub Actions).
- The safety thresholds are set to 40 sessions and 100 talks to avoid publishing an empty page if EasyChair changes or temporarily serves incomplete HTML.
