import sqlite3
import json
from datetime import datetime
from seven_seas.parser import extract_series_data
from seven_seas.utils import extract_volume_number, is_fuzzy_match
from .scraper import scrape_seven_seas_filtered


CACHE_FILE = "seven_seas_series_cache.json"


def cache_series():
    data = extract_series_data()
    print(f"✅ Found {len(data)} series.")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

