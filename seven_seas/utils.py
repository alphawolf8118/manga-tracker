import re
from rapidfuzz import fuzz


def extract_volume_number(title):
    match = re.search(r"(Vol\\.|Volume)?\\s*(\\d+)", title, re.IGNORECASE)
    return int(match.group(2)) if match else None


def is_fuzzy_match(title1, title2, threshold=70):
    return fuzz.ratio(title1.lower(), title2.lower()) >= threshold
