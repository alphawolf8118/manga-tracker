import os
import re
import json
import sqlite3
from datetime import datetime
import unicodedata
import cloudscraper  # make sure this is imported
from bs4 import BeautifulSoup
from tqdm import tqdm  # optional
import time  # Add this at the top of your script
import random
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
from urllib.parse import urlparse

def scrape_release_dates_from_yen_press_playwright(series_url, series_type="manga"):
    print(f"Scraping Yen Press series page (Playwright): {series_url}")
    releases = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(series_url)
        page.wait_for_selector("a.hovered-shadow", timeout=10000)
        volume_links = page.query_selector_all("a.hovered-shadow")
        print(f"Found {len(volume_links)} volume links (Playwright)")

        for vol_link in volume_links:
            vol_url = vol_link.get_attribute("href")
            if not vol_url:
                continue
            if vol_url.startswith("/"):
                vol_url = "https://yenpress.com" + vol_url

            # Go to the volume page
            page.goto(vol_url)
            try:
                page.wait_for_selector("h1.title", timeout=5000)
            except:
                print(f"❌ Could not find title on {vol_url}")
                continue

            title_tag = page.query_selector("h1.title")
            date_tag = page.query_selector("b:text('Release Date')")
            if not title_tag or not date_tag:
                continue

            # The date is the next sibling text node after <b>Release Date</b>
            release_date_node = page.evaluate(
                "(el) => el.nextSibling && el.nextSibling.textContent", date_tag
            )
            if not release_date_node:
                continue

            scraped_title = title_tag.inner_text().strip()
            release_date = release_date_node.strip()
            volume = extract_volume_number(scraped_title)

            if volume is not None:
                releases.append({
                    "title": scraped_title,
                    "volume": volume,
                    "release_date": release_date
                })

            time.sleep(3)  # <-- Add this line for a 2-second delay between volume requests

        browser.close()
    return releases

DB_FILE = "manga.db"

def get_db_connection():
    return sqlite3.connect(DB_FILE)

def extract_volume_number(title):
    match = re.search(r"(Vol\.|Volume)?\s*(\d+)", title, re.IGNORECASE)
    return int(match.group(2)) if match else None

def scrape_release_dates_from_series_page(series_url, series_type="manga"):
    print(f"Scraping {series_type.capitalize()} page: {series_url}")
    scraper = cloudscraper.create_scraper()
    response = scraper.get(series_url)

    if response.status_code != 200:
        print(f"❌ Failed to fetch series page: {response.status_code}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    releases = []

    for release in soup.select(".volumes-container a.series-volume"):
        title_tag = release.find("h3")
        date_tag = release.find("b", string="Release Date")
        if not title_tag or not date_tag:
            continue

        # The date is in the next sibling text node after the <b>Release Date</b>
        release_date_node = date_tag.next_sibling
        if not release_date_node:
            continue

        scraped_title = title_tag.get_text(strip=True)
        release_date = release_date_node.strip()

        # --- ISBN extraction ---
        isbn = None
        isbn_tag = release.find("b", string=re.compile("ISBN", re.IGNORECASE))
        if isbn_tag and isbn_tag.next_sibling:
            isbn_text = isbn_tag.next_sibling.strip()
            # Remove any leading ":" or whitespace
            isbn_text = isbn_text.lstrip(": ").strip()
            # Remove dashes for consistency
            isbn = isbn_text.replace("-", "")
        # -----------------------

        # 🚫 Skip if it's an audiobook or other undesired format
        if any(term in scraped_title.lower() for term in ["audiobook", "audio book", "digital edition", "ebook"]):
            continue

        volume = extract_volume_number(scraped_title)

        if volume is not None:
            releases.append({
                "title": scraped_title,
                "volume": volume,
                "release_date": release_date,
                "isbn": isbn
            })

    return releases

def parse_date(date_str):
    import re
    from datetime import datetime
    try:
        date_str = re.sub(r"\s+", " ", date_str.strip())
        try:
            return datetime.strptime(date_str, "%B %d, %Y").date()
        except ValueError:
            try:
                return datetime.strptime(date_str, "%b %d, %Y").date()
            except ValueError:
                return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None

def update_release_dates_for_title(title, series_id, series_url, series_type="manga"):
    print(f"🔄 Updating {series_type} series: {title}")
    releases = scrape_release_dates_from_series_page(series_url, series_type)

    if not releases:
        print(f"⚠️ No releases found for: {title}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for release in releases:
        vol_number = release.get("volume")
        release_date = release.get("release_date")
        isbn = release.get("isbn")

        if vol_number is None or not release_date:
            continue

        cleaned_date = release_date.lstrip(": ").strip()
        print(f"📦 Volume {vol_number} — Date string: '{cleaned_date}' | ISBN: {isbn}")

        parsed_date = parse_date(cleaned_date)

        if parsed_date:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET release_date = ?, isbn = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (parsed_date, isbn, series_id, vol_number))
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update volume {vol_number}: {e}")
        else:
            print(f"❌ Failed to parse release date for volume {vol_number}: '{cleaned_date}'")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} volumes for {title}")

def update_all_general(progress=None):
    print("🧠 Running update_all_general...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url, type, publisher
        FROM series
        WHERE status IN ('Collecting', 'Interested', 'On Hold')
    """)
    tracked_series = cursor.fetchall()
    conn.close()

    if not tracked_series:
        print("⚠️ No matching series found.")
        return

    total = len(tracked_series)
    print(f"🔄 Updating {total} series...")

    if progress is not None:
        progress.update({"total": total, "current": 0, "done": False})

    for index, (series_id, title, series_url, series_type, publisher) in enumerate(tracked_series, start=1):
        print(f"➡️ Updating {title} ({series_type}, {publisher})...")
        try:
            update_release_dates_for_title(title, series_id, series_url, series_type)
        except Exception as e:
            print(f"❌ Error updating {title}: {e}")
        
        if progress is not None:
            progress["current"] = index

        time.sleep(2)  # Adjust as needed

    if progress is not None:
        progress["done"] = True

    print("✅ Finished general update.")

# if __name__ == "__main__":
#     update_all_general()

def update_all_seven_seas(progress=None):
    print("🧠 Running update_all_seven_seas...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url, type
        FROM series
        WHERE publisher = 'Seven Seas' AND status IN ('Collecting', 'Interested', 'On Hold')
    """)
    tracked_series = cursor.fetchall()
    conn.close()

    if not tracked_series:
        print("⚠️ No matching series found.")
        return

    total = len(tracked_series)
    print(f"🔄 Updating {total} series...")

    if progress is not None:
        progress.update({"total": total, "current": 0, "done": False})

    for index, (series_id, title, series_url, series_type) in enumerate(tracked_series, start=1):
        print(f"➡️ Updating {title} ({series_type})...")
        try:
            update_release_dates_for_title(title, series_id, series_url, series_type)
        except Exception as e:
            print(f"❌ Error updating {title}: {e}")
        
        if progress is not None:
            progress["current"] = index

                    # Add a delay to avoid spamming the server (e.g., 2 seconds delay between requests)
        time.sleep(2)  # Adjust the number of seconds as needed

    if progress is not None:
        progress["done"] = True

    print("✅ Finished Seven Seas update.")


# --- CLI Entry Point ---
# if __name__ == "__main__":
#     update_all_seven_seas()


def scrape_release_dates_from_viz(series_url, series_type="manga"):
    print(f"Scraping Viz series page: {series_url}")
    releases = []
    import cloudscraper
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    scraper = cloudscraper.create_scraper()

    def get_volume_links(soup, base_url):
        links = []
        for a in soup.select('a.color-off-black'):
            vol_url = a.get('href')
            vol_title = a.get_text(strip=True)
            if vol_url and '/product/' in vol_url:
                full_url = urljoin(base_url, vol_url)
                links.append((full_url, vol_title))
        return links

    # Scrape main page
    response = scraper.get(series_url)
    if response.status_code != 200:
        print(f"❌ Failed to fetch series page: {response.status_code}")
        return []
    soup = BeautifulSoup(response.content, "html.parser")
    volume_links = get_volume_links(soup, series_url)

    # Scrape "See all"/"More" page if it exists
    see_all_link = None
    for a in soup.find_all("a", class_="color-off-black"):
        text = a.get_text(strip=True).lower()
        if any(phrase in text for phrase in ["see all", "view all", "more", "all volumes"]):
            see_all_link = a
            break

    if see_all_link and see_all_link.get("href"):
        print(f"See all/More link found: {see_all_link.get('href')} (text: {see_all_link.get_text(strip=True)})")
        all_url = urljoin(series_url, see_all_link["href"])
        print(f"Found 'See all/More' link, scraping: {all_url}")
        response_all = scraper.get(all_url)
        if response_all.status_code == 200:
            soup_all = BeautifulSoup(response_all.content, "html.parser")
            volume_links += get_volume_links(soup_all, all_url)
        else:
            print(f"❌ Failed to fetch 'See all/More' page: {response_all.status_code}")

    # Deduplicate by URL
    seen = set()
    unique_volume_links = []
    for url, title in volume_links:
        if url not in seen:
            unique_volume_links.append((url, title))
            seen.add(url)

    print(f"Found {len(unique_volume_links)} unique volume links:")
    for url, title in unique_volume_links:
        print(f"  {title} -> {url}")

    # Visit each volume page to get the release date
    for vol_url, vol_title in unique_volume_links:
        time.sleep(random.uniform(1.5, 3.5))

        vol_resp = scraper.get(vol_url)
        if vol_resp.status_code != 200:
            continue
        vol_soup = BeautifulSoup(vol_resp.content, "html.parser")
        date_div = vol_soup.find("div", class_="o_release-date")
        release_date = None
        if date_div:
            release_date = date_div.get_text(strip=True).replace("Release", "").strip()

        # --- ISBN extraction for Viz ---
        isbn = None
        isbn_div = vol_soup.find("div", class_="o_isbn13")
        if isbn_div:
            # Remove the <strong>ISBN-13</strong> label and strip spaces
            isbn_text = isbn_div.get_text(strip=True).replace("ISBN-13", "").strip()
            isbn = isbn_text.replace("-", "")  # Remove dashes if you want just digits

        print(f"DEBUG: {vol_title} -> {release_date} | ISBN: {isbn}")

        volume = extract_volume_number(vol_title)
        if volume is not None and release_date:
            releases.append({
                "title": vol_title,
                "volume": volume,
                "release_date": release_date,
                "isbn": isbn,
                "url": vol_url
            })

    return releases

def update_release_dates_for_viz(title, series_id, series_url, series_type="manga"):
    print(f"🔄 Updating Viz series: {title}")
    releases = scrape_release_dates_from_viz(series_url, series_type)

    if not releases:
        print(f"⚠️ No releases found for: {title}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for release in releases:
        vol_number = release.get("volume")
        release_date = release.get("release_date")
        title = release.get("title")
        isbn = release.get("isbn")
        url = release.get("url")

        if vol_number is None or not release_date:
            print(f"Skipping volume: {title} (vol_number: {vol_number}, release_date: {release_date})")
            continue

        cleaned_date = re.sub(r"\s+", " ", release_date.lstrip(": ").strip())
        parsed_date = parse_date(cleaned_date)

        if parsed_date:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET release_date = ?, isbn = ?, url = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (parsed_date, isbn, url, series_id, vol_number))
                if cursor.rowcount == 0:
                    print(f"❌ No DB row for series_id={series_id}, volume_number={vol_number} (title: {title})")
                else:
                    print(f"✅ Updated DB for series_id={series_id}, volume_number={vol_number} (title: {title})")
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update volume {vol_number}: {e}")
        else:
            print(f"❌ Failed to parse release date for volume {vol_number}: '{cleaned_date}' (title: {title})")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} volumes for {title}")

def update_all_viz(progress=None):
    print("🧠 Running update_all_viz...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url, type
        FROM series
        WHERE LOWER(publisher) LIKE '%viz%' AND status IN ('Collecting', 'Interested', 'On Hold')
    """)
    tracked_series = cursor.fetchall()
    conn.close()

    if not tracked_series:
        print("⚠️ No matching series found.")
        return

    total = len(tracked_series)
    print(f"🔄 Updating {total} Viz series...")

    if progress is not None:
        progress.update({"total": total, "current": 0, "done": False})

    for index, (series_id, title, series_url, series_type) in enumerate(tracked_series, start=1):
        print(f"➡️ Updating {title} ({series_type})...")
        try:
            update_release_dates_for_viz(title, series_id, series_url, series_type)
        except Exception as e:
            print(f"❌ Error updating {title}: {e}")

        if progress is not None:
            progress["current"] = index

        time.sleep(2)  # polite delay

    if progress is not None:
        progress["done"] = True

    print("✅ Finished Viz update.")

# --- CLI Test ---
if __name__ == "__main__":
    update_all_viz()

def scrape_single_viz_volume(volume_url, series_id, volume_number):
    print(f"🔄 Scraping Viz volume: {volume_url}")
    import cloudscraper
    from bs4 import BeautifulSoup

    scraper = cloudscraper.create_scraper()
    response = scraper.get(volume_url)
    if response.status_code != 200:
        print(f"❌ Failed to fetch volume page: {response.status_code}")
        return

    soup = BeautifulSoup(response.content, "html.parser")
    date_div = soup.find("div", class_="o_release-date")
    release_date = None
    if date_div:
        release_date = date_div.get_text(strip=True).replace("Release", "").strip()

    isbn = None
    isbn_div = soup.find("div", class_="o_isbn13")
    if isbn_div:
        isbn_text = isbn_div.get_text(strip=True).replace("ISBN-13", "").strip()
        isbn = isbn_text.replace("-", "")

    print(f"DEBUG: Volume {volume_number} -> {release_date} | ISBN: {isbn}")

    # Update the database for this volume
    conn = get_db_connection()
    cursor = conn.cursor()
    cleaned_date = re.sub(r"\s+", " ", release_date.lstrip(": ").strip()) if release_date else None
    parsed_date = parse_date(cleaned_date) if cleaned_date else None

    if parsed_date:
        try:
            cursor.execute("""
                UPDATE volumes
                SET release_date = ?, isbn = ?
                WHERE series_id = ? AND volume_number = ?
            """, (parsed_date, isbn, series_id, volume_number))
            conn.commit()
            print(f"✅ Updated DB for series_id={series_id}, volume_number={volume_number}")
        except Exception as e:
            print(f"❌ Failed to update volume {volume_number}: {e}")
    else:
        print(f"❌ Failed to parse release date for volume {volume_number}: '{release_date}'")

    conn.close()

def find_viz_volume_url_in_series(series_url, volume_number):
    import cloudscraper
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    scraper = cloudscraper.create_scraper()

    def get_volume_links(soup, base_url):
        links = []
        for a in soup.select('a.color-off-black'):
            vol_url = a.get('href')
            vol_title = a.get_text(strip=True)
            if vol_url and '/product/' in vol_url:
                full_url = urljoin(base_url, vol_url)
                links.append((full_url, vol_title))
        return links

    # Scrape main page
    response = scraper.get(series_url)
    if response.status_code != 200:
        print(f"❌ Failed to fetch series page: {response.status_code}")
        return None
    soup = BeautifulSoup(response.content, "html.parser")
    volume_links = get_volume_links(soup, series_url)

    # Scrape "See all"/"More" page if it exists
    see_all_link = None
    for a in soup.find_all("a", class_="color-off-black"):
        if "see all" in a.get_text(strip=True).lower():
            see_all_link = a
            break

    if see_all_link and see_all_link.get("href"):
        all_url = urljoin(series_url, see_all_link["href"])
        response_all = scraper.get(all_url)
        if response_all.status_code == 200:
            soup_all = BeautifulSoup(response_all.content, "html.parser")
            volume_links += get_volume_links(soup_all, all_url)

    # Deduplicate by URL
    seen = set()
    unique_volume_links = []
    for url, title in volume_links:
        if url not in seen:
            unique_volume_links.append((url, title))
            seen.add(url)

    # Use the same extract_volume_number logic
    for url, title in unique_volume_links:
        vnum = extract_volume_number(title)
        print(f"Checking title: {title} (extracted volume: {vnum})")
        if vnum is not None and int(vnum) == int(volume_number):
            print(f"Matched volume {volume_number} with title: {title}")
            return url
    return None

def scrape_release_dates_from_yen_press(series_url, series_type="manga"):
    print(f"Scraping Yen Press series page (Playwright): {series_url}")
    releases = []
    from playwright.sync_api import sync_playwright
    import time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(series_url)
        page.wait_for_selector("a.hovered-shadow", timeout=30000)

        volume_links = page.query_selector_all("a.hovered-shadow")
        print(f"Found {len(volume_links)} volume links (Playwright)")

        # Scroll to load more (repeat until no new content)
        print("Scrolling to load all volumes...")
        last_height = page.evaluate("document.body.scrollHeight")
        while True:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)  # Wait for load
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break  # No more loaded
            last_height = new_height
            print("Scrolled - checking for more...")
        
        volume_links = page.query_selector_all("a.hovered-shadow")
        print(f"Found {len(volume_links)} volume links AFTER full load")

        # Step 1: Collect all volume URLs first
        vol_urls = []
        for vol_link in volume_links:
            vol_url = vol_link.get_attribute("href")
            if not vol_url:
                continue
            if vol_url.startswith("/"):
                vol_url = "https://yenpress.com" + vol_url
            vol_urls.append(vol_url)

        # Step 2: Visit each volume page separately
        for vol_url in vol_urls:
            page.goto(vol_url)
            try:
                page.wait_for_selector("h1", timeout=5000)
            except:
                print(f"❌ Could not find title on {vol_url}")
                continue

            title_tag = page.query_selector("h1")
            # Find the <span> with "Release Date" and get the next sibling <p class="info">
            release_date = None
            isbn = None
            # Only look inside the main/print section
            main_detail = page.query_selector("div.detail.active")
            if main_detail:
                detail_boxes = main_detail.query_selector_all("div.detail-box")
                for box in detail_boxes:
                    label = box.query_selector("span")
                    info = box.query_selector("p.info")
                    if label and info:
                        label_text = label.inner_text().strip().lower()
                        if label_text == "isbn":
                            isbn_text = info.inner_text().strip()
                            isbn = isbn_text.replace("-", "").replace(" ", "")
                        if "release date" in label_text:
                            release_date = info.inner_text().strip()

            if not title_tag or not release_date:
                continue

            scraped_title = title_tag.inner_text().strip()
            volume = extract_volume_number(scraped_title)

            if volume is not None:
                releases.append({
                    "title": scraped_title,
                    "volume": volume,
                    "release_date": release_date,
                    "isbn": isbn
                })

            time.sleep(3)  # polite delay

        browser.close()
    return releases

def update_release_dates_for_yen_press(title, series_id, series_url, series_type="manga"):
    print(f"🔄 Updating Yen Press series: {title}")
    releases = scrape_release_dates_from_yen_press(series_url, series_type)

    if not releases:
        print(f"⚠️ No releases found for: {title}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for release in releases:
        vol_number = release.get("volume")
        release_date = release.get("release_date")
        isbn = release.get("isbn")

        if vol_number is None or not release_date:
            continue

        cleaned_date = release_date.lstrip(": ").strip()
        print(f"📦 Volume {vol_number} — Date string: '{cleaned_date}' | ISBN: {isbn}")
        parsed_date = parse_date(cleaned_date)

        if parsed_date:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET release_date = ?, isbn = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (parsed_date, isbn, series_id, vol_number))
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update volume {vol_number}: {e}")
        else:
            print(f"❌ Failed to parse release date for volume {vol_number}: '{cleaned_date}'")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} volumes for {title}")

def update_all_yen_press(progress=None):
    print("🧠 Running update_all_yen_press...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url, type
        FROM series
        WHERE publisher = 'Yen Press' AND status IN ('Collecting', 'Interested', 'On Hold')
    """)
    tracked_series = cursor.fetchall()
    conn.close()

    if not tracked_series:
        print("⚠️ No matching series found.")
        return

    total = len(tracked_series)
    print(f"🔄 Updating {total} series...")

    if progress is not None:
        progress.update({"total": total, "current": 0, "done": False})

    for index, (series_id, title, series_url, series_type) in enumerate(tracked_series, start=1):
        print(f"➡️ Updating {title} ({series_type})...")
        try:
            update_release_dates_for_yen_press(title, series_id, series_url, series_type)
        except Exception as e:
            print(f"❌ Error updating {title}: {e}")

        if progress is not None:
            progress["current"] = index

        time.sleep(3)  # polite delay

    if progress is not None:
        progress["done"] = True

    print("✅ Finished Yen Press update.")

# if __name__ == "__main__":
#     update_all_yen_press()

def scrape_release_dates_from_kodansha(series_url, series_type="manga"):
    print(f"Scraping Kodansha series page (Playwright): {series_url}")
    releases = []
    from playwright.sync_api import sync_playwright
    import time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(series_url)
        # Wait for volume cards to load
        page.wait_for_selector("div.info-wrapper", timeout=10000)
        info_wrappers = page.query_selector_all("div.info-wrapper")
        print(f"Found {len(info_wrappers)} volume cards (Playwright).")

        for wrapper in info_wrappers:
            a_tag = wrapper.query_selector("a.info-wrapper-title")
            h3_tag = wrapper.query_selector("h3.product-name")
            if not a_tag or not h3_tag:
                continue
            vol_url = a_tag.get_attribute("href")
            if vol_url.startswith("/"):
                vol_url = "https://kodansha.us" + vol_url
            vol_title = h3_tag.inner_text().strip()
            releases.append({"url": vol_url, "title": vol_title})

        # Visit each volume page to get release date and ISBN
        for release in releases:
            vol_url = release["url"]
            vol_title = release["title"]
            page.goto(vol_url)
            try:
                page.wait_for_selector("h1", timeout=5000)
            except:
                print(f"❌ Could not find title on {vol_url}")
                continue

            title_tag = page.query_selector("h1")
            release_date = None
            isbn = None

            # Find all product-rating-table-title-value-wrapper divs
            info_blocks = page.query_selector_all("div.product-rating-table-title-value-wrapper")
            for block in info_blocks:
                title_span = block.query_selector("div.product-rating-table-title-wrapper > span.product-rating-table-title")
                value_span = block.query_selector("div.product-rating-table-value-wrapper > span.product-rating-table-title")
                if not title_span or not value_span:
                    continue
                label = title_span.inner_text().strip()
                value = value_span.inner_text().strip()
                if label == "Print Release:":
                    release_date = value
                if label == "ISBN:":
                    isbn = value.replace("-", "").strip()

            if not title_tag or not release_date:
                continue

            scraped_title = title_tag.inner_text().strip()
            volume = extract_volume_number(scraped_title)

            print(f"DEBUG: {scraped_title} | volume: {volume} | release_date: {release_date} | isbn: {isbn}")

            if volume is not None:
                release.update({
                    "title": scraped_title,
                    "volume": volume,
                    "release_date": release_date,
                    "isbn": isbn
                })

            time.sleep(2)  # polite delay

        browser.close()

    # Filter out releases without volume number or release date
    final_releases = [
        {
            "title": r["title"],
            "volume": r["volume"],
            "release_date": r["release_date"],
            "isbn": r["isbn"],
            "url": r["url"]
        }
        for r in releases if r.get("volume") is not None and r.get("release_date")
    ]
    return final_releases

def update_release_dates_for_kodansha(title, series_id, series_url, series_type="manga"):
    print(f"🔄 Updating Kodansha series: {title}")
    releases = scrape_release_dates_from_kodansha(series_url, series_type)

    if not releases:
        print(f"⚠️ No releases found for: {title}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for release in releases:
        vol_number = release.get("volume")
        release_date = release.get("release_date")
        isbn = release.get("isbn")
        url = release.get("url")

        if vol_number is None or not release_date:
            print(f"Skipping volume: {release.get('title')} (vol_number: {vol_number}, release_date: {release_date})")
            continue

        cleaned_date = re.sub(r"\s+", " ", release_date.lstrip(": ").strip())
        parsed_date = parse_date(cleaned_date)

        if parsed_date:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET release_date = ?, isbn = ?, url = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (parsed_date, isbn, url, series_id, vol_number))
                if cursor.rowcount == 0:
                    print(f"❌ No DB row for series_id={series_id}, volume_number={vol_number} (title: {release.get('title')})")
                else:
                    print(f"✅ Updated DB for series_id={series_id}, volume_number={vol_number} (title: {release.get('title')})")
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update volume {vol_number}: {e}")
        else:
            print(f"❌ Failed to parse release date for volume {vol_number}: '{cleaned_date}' (title: {release.get('title')})")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} volumes for {title}")

def update_all_kodansha(progress=None):
    print("🧠 Running update_all_kodansha...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url, type
        FROM series
        WHERE LOWER(publisher) LIKE '%kodansha%' AND status IN ('Collecting', 'Interested', 'On Hold')
    """)
    tracked_series = cursor.fetchall()
    conn.close()

    if not tracked_series:
        print("⚠️ No matching series found.")
        return

    total = len(tracked_series)
    print(f"🔄 Updating {total} Kodansha series...")

    if progress is not None:
        progress.update({"total": total, "current": 0, "done": False})

    for index, (series_id, title, series_url, series_type) in enumerate(tracked_series, start=1):
        print(f"➡️ Updating {title} ({series_type})...")
        try:
            update_release_dates_for_kodansha(title, series_id, series_url, series_type)
        except Exception as e:
            print(f"❌ Error updating {title}: {e}")

        if progress is not None:
            progress["current"] = index

        time.sleep(2)  # polite delay

    if progress is not None:
        progress["done"] = True

    print("✅ Finished Kodansha update.")


def scrape_release_dates_from_square_enix(series_url, series_type="manga"):
    print(f"Scraping Square Enix series page (Playwright): {series_url}")
    releases = []
    from playwright.sync_api import sync_playwright
    import time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        page = browser.new_page()
        page.goto(series_url)
        # Handle region/cookie popup if present
        try:
            page.wait_for_selector('button:has-text("Continue")', timeout=3000)
            page.click('button:has-text("Continue")')
            print("Clicked region/cookie popup.")
        except:
            pass

        # ...existing code...
        # Wait for volume cards to load
        page.wait_for_selector('div.p-1', timeout=10000)
        num_vols = len(page.query_selector_all('div.p-1'))
        print(f"Found {num_vols} volume title divs (Playwright).")

        for idx in range(num_vols):
            # Always re-query after navigation!
            page.wait_for_selector('div.p-1', timeout=10000)
            locator = page.locator('div.p-1').nth(idx)
            vol_title = locator.inner_text().strip()
            parent_locator = locator.locator('..')
            parent_locator.click()
            time.sleep(2)  # Wait for navigation

            vol_url = page.url

            # Wait for info rows to load
            try:
                page.wait_for_selector('div.mb-2', timeout=10000)
            except:
                print(f"❌ Could not find details on {vol_url}")
                page.go_back()
                time.sleep(2)
                continue

            title_tag = page.query_selector('div.text-3xl.font-bold.uppercase')
            release_date = None
            isbn = None

            info_rows = page.query_selector_all("div.mb-2")
            for row in info_rows:
                label_span = row.query_selector("span.font-bold.uppercase")
                value_span = row.query_selector("span.mx-1")
                if not label_span or not value_span:
                    continue
                label = label_span.inner_text().strip().lower()
                value = value_span.inner_text().strip()
                if "release date" in label:
                    release_date = value
                if "isbn" in label:
                    isbn = value.replace("-", "").strip()

            print(f"URL: {vol_url}")
            print(f"title_tag: {title_tag.inner_text().strip() if title_tag else None}")

            scraped_title = title_tag.inner_text().strip() if title_tag else None
            volume = extract_volume_number(scraped_title) if scraped_title else None

            print(f"scraped_title: {scraped_title}")
            print(f"volume: {volume}")
            print(f"release_date: {release_date}")
            print(f"isbn: {isbn}")

            if not title_tag or not release_date:
                page.go_back()
                time.sleep(2)
                continue

            print(f"DEBUG: {scraped_title} | volume: {volume} | release_date: {release_date} | isbn: {isbn}")

            if volume is not None:
                releases.append({
                    "title": scraped_title,
                    "volume": volume,
                    "release_date": release_date,
                    "isbn": isbn,
                    "url": vol_url
                })

            page.go_back()
            time.sleep(2)
# ...existing code...
        browser.close()

    # Filter out releases without volume number or release date
    final_releases = [
        {
            "title": r["title"],
            "volume": r["volume"],
            "release_date": r["release_date"],
            "isbn": r["isbn"],
            "url": r["url"]
        }
        for r in releases if r.get("volume") is not None and r.get("release_date")
    ]
    return final_releases

def update_release_dates_for_square_enix(title, series_id, series_url, series_type="manga"):
    print(f"🔄 Updating Square Enix series: {title}")
    releases = scrape_release_dates_from_square_enix(series_url, series_type)

    if not releases:
        print(f"⚠️ No releases found for: {title}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for release in releases:
        vol_number = release.get("volume")
        release_date = release.get("release_date")
        isbn = release.get("isbn")
        url = release.get("url")

        if vol_number is None or not release_date:
            print(f"Skipping volume: {release.get('title')} (vol_number: {vol_number}, release_date: {release_date})")
            continue

        cleaned_date = re.sub(r"\s+", " ", release_date.lstrip(": ").strip())
        parsed_date = parse_date(cleaned_date)

        if parsed_date:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET release_date = ?, isbn = ?, url = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (parsed_date, isbn, url, series_id, vol_number))
                if cursor.rowcount == 0:
                    print(f"❌ No DB row for series_id={series_id}, volume_number={vol_number} (title: {release.get('title')})")
                else:
                    print(f"✅ Updated DB for series_id={series_id}, volume_number={vol_number} (title: {release.get('title')})")
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update volume {vol_number}: {e}")
        else:
            print(f"❌ Failed to parse release date for volume {vol_number}: '{cleaned_date}' (title: {release.get('title')})")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} volumes for {title}")

def scrape_isbns_from_one_peace_books(series_url):
    print(f"Scraping One Peace Books series page: {series_url}")
    import cloudscraper
    from bs4 import BeautifulSoup
    import re

    scraper = cloudscraper.create_scraper()
    response = scraper.get(series_url)
    if response.status_code != 200:
        print(f"❌ Failed to fetch series page: {response.status_code}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    results = []

    # Use the correct selector for each volume block
    for vol in soup.select("div.newbook-bookinfo-detail"):
        title_tag = vol.find("p", class_="booktitle")
        isbn = None

        # Find the ISBN in any of the bookinfo <p> tags
        for info in vol.find_all("p", class_="bookinfo"):
            match = re.search(r"ISBN:\s*([\dX-]+)", info.get_text(strip=True))
            if match:
                isbn = match.group(1).replace("-", "")
                break

        vol_title = title_tag.get_text(strip=True) if title_tag else None

        print(f"DEBUG: {vol_title} | ISBN: {isbn}")

        if vol_title and isbn:
            results.append({
                "title": vol_title,
                "isbn": isbn
            })

    return results

def update_isbns_for_one_peace_books(series_id, series_url):
    print(f"🔄 Updating ISBNs for One Peace Books series: {series_url}")
    volumes = scrape_isbns_from_one_peace_books(series_url)
    if not volumes:
        print(f"⚠️ No volumes found for: {series_url}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for vol in volumes:
        vol_title = vol["title"]
        isbn = vol["isbn"]
        volume_number = extract_volume_number(vol_title)
        if volume_number and isbn:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET isbn = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (isbn, series_id, volume_number))
                if cursor.rowcount == 0:
                    print(f"❌ No DB row for series_id={series_id}, volume_number={volume_number} (title: {vol_title})")
                else:
                    print(f"✅ Updated ISBN for series_id={series_id}, volume_number={volume_number} (title: {vol_title})")
                    updated += 1
            except Exception as e:
                print(f"❌ Failed to update ISBN for volume {volume_number}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} ISBNs for series_id={series_id}")

def scrape_release_dates_from_kaitenbooks(series_url, series_type="manga"):
    print(f"Scraping KaitenBooks series page (Playwright): {series_url}")
    releases = []
    from playwright.sync_api import sync_playwright
    import time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(series_url)
        # Wait for volume cards to load
        page.wait_for_selector("div.product-grid-item")
        items = page.query_selector_all("div.product-grid-item")
        print(f"Found {len(items)} volume cards (Playwright).")


        for wrapper in info_wrappers:
            link = item.query_selector("a.product-grid-item-link")
            title_tag = item.query_selector("h3.product-grid-item-title")

            if not a_tag or not h3_tag:
                continue
            vol_url = a_tag.get_attribute("href")
            if vol_url.startswith("/"):
                vol_url = "https://kodansha.us" + vol_url
            vol_title = h3_tag.inner_text().strip()
            releases.append({"url": vol_url, "title": vol_title})

        # Visit each volume page to get release date and ISBN
        for release in releases:
            vol_url = release["url"]
            vol_title = release["title"]
            page.goto(vol_url)
            try:
                page.wait_for_selector("h1", timeout=5000)
            except:
                print(f"❌ Could not find title on {vol_url}")
                continue

            title_tag = page.query_selector("h1")
            release_date = None
            isbn = None

            # Find all product-rating-table-title-value-wrapper divs
            info_blocks = page.query_selector_all("div.product-rating-table-title-value-wrapper")
            for block in info_blocks:
                title_span = block.query_selector("div.product-rating-table-title-wrapper > span.product-rating-table-title")
                value_span = block.query_selector("div.product-rating-table-value-wrapper > span.product-rating-table-title")
                if not title_span or not value_span:
                    continue
                label = title_span.inner_text().strip()
                value = value_span.inner_text().strip()
                if label == "Print Release:":
                    release_date = value
                if label == "ISBN:":
                    isbn = value.replace("-", "").strip()

            if not title_tag or not release_date:
                continue

            scraped_title = title_tag.inner_text().strip()
            volume = extract_volume_number(scraped_title)

            print(f"DEBUG: {scraped_title} | volume: {volume} | release_date: {release_date} | isbn: {isbn}")

            if volume is not None:
                release.update({
                    "title": scraped_title,
                    "volume": volume,
                    "release_date": release_date,
                    "isbn": isbn
                })

            time.sleep(2)  # polite delay

        browser.close()

    # Filter out releases without volume number or release date
    final_releases = [
        {
            "title": r["title"],
            "volume": r["volume"],
            "release_date": r["release_date"],
            "isbn": r["isbn"],
            "url": r["url"]
        }
        for r in releases if r.get("volume") is not None and r.get("release_date")
    ]
    return final_releases

def update_release_dates_for_kaitenbooks(title, series_id, series_url, series_type="manga"):
    print(f"🔄 Updating KaitenBooks series: {title}")
    releases = scrape_release_dates_from_kaitenbooks(series_url, series_type)

    if not releases:
        print(f"⚠️ No releases found for: {title}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    updated = 0

    for release in releases:
        vol_number = release.get("volume")
        release_date = release.get("release_date")
        isbn = release.get("isbn")
        url = release.get("url")

        if vol_number is None or not release_date:
            print(f"Skipping volume: {release.get('title')} (vol_number: {vol_number}, release_date: {release_date})")
            continue

        cleaned_date = re.sub(r"\s+", " ", release_date.lstrip(": ").strip())
        parsed_date = parse_date(cleaned_date)

        if parsed_date:
            try:
                cursor.execute("""
                    UPDATE volumes
                    SET release_date = ?, isbn = ?, url = ?
                    WHERE series_id = ? AND volume_number = ?
                """, (parsed_date, isbn, url, series_id, vol_number))
                if cursor.rowcount == 0:
                    print(f"❌ No DB row for series_id={series_id}, volume_number={vol_number} (title: {release.get('title')})")
                else:
                    print(f"✅ Updated DB for series_id={series_id}, volume_number={vol_number} (title: {release.get('title')})")
                updated += 1
            except Exception as e:
                print(f"❌ Failed to update volume {vol_number}: {e}")
        else:
            print(f"❌ Failed to parse release date for volume {vol_number}: '{cleaned_date}' (title: {release.get('title')})")

    conn.commit()
    conn.close()
    print(f"✅ Updated {updated} volumes for {title}")

def update_all_kodansha(progress=None):
    print("🧠 Running update_all_kaitenbooks...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, url, type
        FROM series
        WHERE LOWER(publisher) LIKE '%kaitenbooks%' AND status IN ('Collecting', 'Interested', 'On Hold')
    """)
    tracked_series = cursor.fetchall()
    conn.close()

    if not tracked_series:
        print("⚠️ No matching series found.")
        return

    total = len(tracked_series)
    print(f"🔄 Updating {total} KaitenBooks series...")

    if progress is not None:
        progress.update({"total": total, "current": 0, "done": False})

    for index, (series_id, title, series_url, series_type) in enumerate(tracked_series, start=1):
        print(f"➡️ Updating {title} ({series_type})...")
        try:
            update_release_dates_for_kaitenbooks(title, series_id, series_url, series_type)
        except Exception as e:
            print(f"❌ Error updating {title}: {e}")

        if progress is not None:
            progress["current"] = index

        time.sleep(2)  # polite delay

    if progress is not None:
        progress["done"] = True

    print("✅ Finished KaitenBooks update.")