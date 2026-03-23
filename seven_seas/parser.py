from seven_seas.fetcher import get_soup


def extract_series_data():
    soup = get_soup()
    series_data = []

    for a in soup.select("a.series.thumb"):
        title = a.select_one("h3")
        url = a.get("href")
        if title and url:
            clean_title = title.get_text(strip=True)
            series_data.append({"title": clean_title, "url": url})

    return series_data
