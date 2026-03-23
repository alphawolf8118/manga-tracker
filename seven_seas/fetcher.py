import cloudscraper
from bs4 import BeautifulSoup

scraper = cloudscraper.create_scraper()

URL = "https://sevenseasentertainment.com/series/"


def fetch_series_page():
    print("\U0001F310 Fetching series page...")
    response = scraper.get(URL)
    response.raise_for_status()
    return response.text


def get_soup():
    html = fetch_series_page()
    return BeautifulSoup(html, "html.parser")

