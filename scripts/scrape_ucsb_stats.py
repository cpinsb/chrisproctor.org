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

    # Try multiple patterns for overall record
    # Patterns: "27-12", "27–12", "Overall: 27-12", etc.
    overall_patterns = [
        r'Overall\s*[:\-]?\s*(\d+)[–\-](\d+)',
        r'Record\s*[:\-]?\s*(\d+)[–\-](\d+)',
        r'(\d+)[–\-](\d+)\s*(?:overall|record)',
    ]
    for pattern in overall_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            records['record_overall'] = f"{match.group(1)}-{match.group(2)}"
            break

    # Try multiple patterns for Big West record
    bw_patterns = [
        r'Big\s+West\s*[:\-]?\s*(\d+)[–\-](\d+)',
        r'Conference\s*[:\-]?\s*(\d+)[–\-](\d+)',
        r'(\d+)[–\-](\d+)\s*(?:big\s+west|conference)',
    ]
    for pattern in bw_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            records['record_league'] = f"{match.group(1)}-{match.group(2)}"
            break

    # Try to find standing (more flexible)
    standing_patterns = [
        r'(\d+)(?:st|nd|rd|th)\s+(?:place|standing)',
        r'Standing\s*[:\-]?\s*(\d+)(?:st|nd|rd|th)?',
        r'Rank\s*[:\-]?\s*(\d+)(?:st|nd|rd|th)?',
    ]
    for pattern in standing_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            rank = int(match.group(1))
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
            records['league_standing'] = f"{rank}{suffix}"
            break

    if records:
        print(f"[scrape] extracted records: {records}", flush=True)

    return records


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
            records = extract_records(html)
            print(f"[scrape] season={season} tables={len(tables)}", flush=True)

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
