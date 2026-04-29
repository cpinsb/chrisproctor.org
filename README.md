# chrisproctor.org

A simple frontend-only website hosted on GitHub Pages.

## Pages

- `/` — Landing page with two links
- `/UCSBbaseballstats/` — Live UCSB Gauchos baseball stats (scraped client-side via CORS proxy)
- `/realestate/` — Property listings with map links and region filters

## Deploy to GitHub Pages

1. Create a new repo on GitHub (e.g. `chrisproctor.github.io` or any name).
2. Copy all files from this folder into the repo root and push to `main`.
3. In the repo, go to **Settings → Pages**:
   - Source: **Deploy from a branch**
   - Branch: **main** / root
4. The `CNAME` file already contains `chrisproctor.org`, so GitHub will configure the custom domain automatically.
5. At your DNS provider, point `chrisproctor.org` to GitHub Pages:
   - Add **A records** for the apex domain pointing to:
     - `185.199.108.153`
     - `185.199.109.153`
     - `185.199.110.153`
     - `185.199.111.153`
   - (Optional) Add a **CNAME record** for `www` pointing to `<your-username>.github.io`.
6. Back in **Settings → Pages**, check **Enforce HTTPS** once the certificate is ready.

## Notes on the baseball stats page

The page loads stats in this order:

1. **`UCSBbaseballstats/stats-{season}.json`** — committed nightly by the GitHub Action (preferred, fast, reliable).
2. **`UCSBbaseballstats/stats.json`** — the most-recent-season snapshot, also committed by the action.
3. **Live client-side scrape** through public CORS proxies — used only if neither JSON is available for the requested season.
4. **Direct link** to ucsbgauchos.com — final fallback if everything above fails.

### Nightly scraper (GitHub Action)

`.github/workflows/scrape-stats.yml` runs every night at 09:00 UTC (≈ 02:00 PT). It:

1. Installs `requests` + `beautifulsoup4`.
2. Runs `scripts/scrape_ucsb_stats.py` with default seasons (2026, 2025).
3. Writes `UCSBbaseballstats/stats.json`, per-season files (`stats-2026.json`, `stats-2025.json`), and `stats-index.json`.
4. Commits the changes back to `main` if anything changed.

The workflow already has `permissions: contents: write`, but make sure your repo allows Actions to push:
**Settings → Actions → General → Workflow permissions → Read and write permissions**.

You can also run it manually from the **Actions** tab via the **Run workflow** button, optionally passing a custom space-separated list of seasons (e.g. `2024 2023`).

## Editing real estate listings

Open `realestate/index.html` and edit the `properties` array near the bottom of the file. Each entry supports `name`, `city`, `region`, `state`, `description`, `photo` (URL), and `mapQuery`. Replace the Unsplash placeholder photos with your own as desired.
