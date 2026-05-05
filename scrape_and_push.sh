#!/bin/bash
# Scrape UCSB baseball stats and push to GitHub

cd /Users/christopherproctor/Desktop/GitHub

# Run the scraper
python3 scripts/scrape_ucsb_stats.py

# Commit and push if there are changes
git config user.email "action@github.com"
git config user.name "UCSB Stats Scraper"
git add UCSBbaseballstats/stats*.json
git diff --quiet && git diff --staged --quiet || (git commit -m "Update UCSB baseball stats" && git push)

echo "Scrape completed at $(date)" >> ~/scrape_log.txt
