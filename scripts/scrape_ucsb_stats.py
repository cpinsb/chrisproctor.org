#!/usr/bin/env python3
"""Scrape UCSB Gauchos baseball stats and write a normalized stats.json.

Output schema:
{
  "season": "2026",
  "scraped_at": "2026-04-29T12:00:00Z",
  "source_url": "https://ucsbgauchos.com/sports/baseball/stats/2026",
  "tables": [
    {"heading": "Hitting", "headers": ["#","Player",...], "rows": [["1","Doe, John",...], ...]},
    ...
  ]
}
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DEFAULT_SEASONS = ["2026", "2025"]
BASE_URL = "https://ucsbgauchos.com/sports/baseball/stats"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "UCSBbaseballstats"))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (chrisproctor.org stats bot) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def find_heading(table) -> str:
    """Walk backward from the table to find the nearest heading-ish text."""
    # caption inside the table
    cap = table.find("caption")
    if cap and cap.get_text(strip=True):
        return cap.get_text(strip=True)

    node = table
    for _ in range(8):  # walk up at most 8 levels
        prev = node.find_previous(["h1", "h2", "h3", "h4", "h5", "h6", "caption", "legend"])
        if prev:
            text = prev.get_text(" ", strip=True)
            if text:
                return text
        # also try aria-label / data attributes on ancestors
        if node.parent is None:
            break
        if node.parent.get("aria-label"):
            return node.parent.get("aria-label").strip()
        node = node.parent
    return "Statistics"


def extract_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tables = []
    for t in soup.find_all("table"):
        # headers: prefer thead th, fall back to first row th
        header_cells = t.select("thead th")
        if not header_cells:
            first_row = t.find("tr")
            if first_row:
                header_cells = first_row.find_all(["th", "td"])
        headers = [c.get_text(" ", strip=True) for c in header_cells]
        if len(headers) < 3:
            continue

        body_rows = t.select("tbody tr") or t.find_all("tr")[1:]
        rows = []
        for tr in body_rows:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) != len(headers):
                continue
            if not any(cells):
                continue
            rows.append(cells)
        if not rows:
            continue

        tables.append(
            {
                "heading": find_heading(t),
                "headers": headers,
                "rows": rows,
            }
        )
    return tables


def extract_records(html: str) -> dict:
    """Try to extract overall record, league record, and standing from the page."""
    soup = BeautifulSoup(html, "html.parser")
    records = {}
    text = soup.get_text()

    # Print a snippet around "Baseball Cumulative" to see the actual format
    if "Baseball Cumulative" in text:
        idx = text.find("Baseball Cumulative")
        snippet = text[idx:idx+200]
        print(f"[scrape] Text around 'Baseball Cumulative': {repr(snippet)}", flush=True)

    # Look for pattern like (30-15, 16-8) which is (overall, big west)
    # Be more flexible with whitespace and dash types
    record_pair_patterns = [
        r'\((\d+)\s*[-–−]\s*(\d+)\s*,\s*(\d+)\s*[-–−]\s*(\d+)\)',
        r'\((\d+)-(\d+),\s*(\d+)-(\d+)\)',
        r'\((\d+)[–\-](\d+)\s*,\s*(\d+)[–\-](\d+)\)',
    ]

    for pattern in record_pair_patterns:
        record_match = re.search(pattern, text)
        if record_match:
            overall_w = record_match.group(1)
            overall_l = record_match.group(2)
            league_w = record_match.group(3)
            league_l = record_match.group(4)
            records['record_overall'] = f"{overall_w}-{overall_l}"
            records['record_league'] = f"{league_w}-{league_l}"
            print(f"[scrape] found record pair: overall={overall_w}-{overall_l}, league={league_w}-{league_l}", flush=True)
            break

    if records:
        print(f"[scrape] extracted records: {records}", flush=True)
    else:
        print(f"[scrape] no records found in page text", flush=True)

    return records


def get_bigwest_standing(season: str) -> dict:
    """Fetch UCSB's Big West standing from the official Big West standings page."""
    standings_url = "https://bigwest.org/standings.aspx?path=baseball"
    try:
        print(f"[scrape] GET {standings_url} for Big West standing", flush=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(standings_url, timeout=60000, wait_until="networkidle")
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Find the standings table and count rows to determine UCSB's rank
        rank = 0
        row_count = 0
        for row in soup.find_all('tr'):
            row_text = row.get_text().strip()
            # Skip header rows and empty rows
            if not row_text or 'School' in row_text or 'Conf' in row_text:
                continue

            row_count += 1
            # Check if this row is UCSB
            if 'UC Santa Barbara' in row_text or 'UCSB' in row_text:
                rank = row_count
                break

        if rank > 0 and 1 <= rank <= 12:
            # Proper ordinal suffix
            if rank % 100 in (11, 12, 13):
                suffix = 'th'
            elif rank % 10 == 1:
                suffix = 'st'
            elif rank % 10 == 2:
                suffix = 'nd'
            elif rank % 10 == 3:
                suffix = 'rd'
            else:
                suffix = 'th'
            print(f"[scrape] found UCSB standing from Big West page: {rank}{suffix}", flush=True)
            return {'league_standing': f"{rank}{suffix}"}

        print(f"[scrape] could not find UCSB standing on Big West page", flush=True)
        return {}
    except Exception as e:
        print(f"[scrape] Failed to fetch Big West standings: {e}", flush=True)
        return {}


def scrape_season(season: str) -> dict:
    url = f"{BASE_URL}/{season}"
    max_retries = 3

    for attempt in range(max_retries):
        try:
            print(f"[scrape] GET {url} (attempt {attempt + 1}/{max_retries})", flush=True)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page(user_agent=HEADERS["User-Agent"])
                page.goto(url, timeout=60000, wait_until="networkidle")
                html = page.content()
                browser.close()

            tables = extract_tables(html)
            # Extract records (overall and Big West W-L) from UCSB stats page
            records = extract_records(html)

            # Get standing from Big West official standings page
            bw_standing = get_bigwest_standing(season)
            records.update(bw_standing)

            print(f"[scrape] season={season} tables={len(tables)} records={records}", flush=True)

            result = {
                "season": season,
                "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source_url": url,
                "tables": tables,
            }
            # Add records if found
            result.update(records)
            return result
        except Exception as e:
            print(f"[scrape] Attempt {attempt + 1} failed: {e}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise


def main() -> int:
    seasons = sys.argv[1:] or DEFAULT_SEASONS
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_seasons = []
    for season in seasons:
        try:
            data = scrape_season(season)
        except Exception as e:
            print(f"[scrape] season {season} failed: {e}", file=sys.stderr)
            continue
        if data["tables"]:
            all_seasons.append(data)

    if not all_seasons:
        print("[scrape] no stats scraped from any season", file=sys.stderr)
        return 1

    # Primary file: most recent season with content
    primary = all_seasons[0]
    (OUTPUT_DIR / "stats.json").write_text(json.dumps(primary, indent=2) + "\n")
    print(f"[scrape] wrote {OUTPUT_DIR / 'stats.json'}", flush=True)

    # Per-season files for the season selector
    for season_data in all_seasons:
        season = re.sub(r"[^0-9]", "", season_data["season"]) or season_data["season"]
        (OUTPUT_DIR / f"stats-{season}.json").write_text(
            json.dumps(season_data, indent=2) + "\n"
        )
        print(f"[scrape] wrote {OUTPUT_DIR / f'stats-{season}.json'}", flush=True)

    # Index of available seasons
    index = {
        "default_season": primary["season"],
        "seasons": [s["season"] for s in all_seasons],
        "scraped_at": primary["scraped_at"],
    }
    (OUTPUT_DIR / "stats-index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"[scrape] wrote {OUTPUT_DIR / 'stats-index.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
