import re
from bs4 import BeautifulSoup
import cloudscraper

def extract_volume_number(title):
    match = re.search(r"(Vol\.|Volume)?\s*(\d+)", title, re.IGNORECASE)
    return int(match.group(2)) if match else None

def scrape_volumes_from_series_page(url):
    print(f"🌐 Fetching: {url}")  # Debugging
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url)

    if response.status_code != 200:
        print(f"❌ Failed to fetch page. Status code: {response.status_code}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")

    # Save HTML for inspection
    with open("debug_sevenseas.html", "w", encoding="utf-8") as f:
        f.write(soup.prettify())

    releases = []

    for volume_tag in soup.select("a.series-volume"):
        title_tag = volume_tag.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else None

        release_text = volume_tag.get_text(separator="\n", strip=True)
        date_match = re.search(r"Release Date\s*:\s*(.*)", release_text)
        release_date = date_match.group(1) if date_match else None

        if title and release_date:
            volume = extract_volume_number(title)
            if volume is not None:
                releases.append({
                    "title": title,
                    "volume": volume,
                    "release_date": release_date
                })

    print(f"🔍 Found {len(releases)} volumes")
    return releases

# 🔍 Test URL
if __name__ == "__main__":
    test_url = "https://sevenseasentertainment.com/series/im-the-evil-lord-of-an-intergalactic-empire-manga/"
    data = scrape_volumes_from_series_page(test_url)
    for d in data:
        print(f"Vol. {d['volume']:>2} | {d['release_date']} | {d['title']}")

