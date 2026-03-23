from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def scrape_bn_store_inventory(isbn, zipcode="02038", radius=75, store_name="", db_release_date=None):
    print(f"\n=== Starting inventory scrape for ISBN: {isbn} ===")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--window-size=1920,3000"]
        )

        page = browser.new_page(
            viewport={"width": 1920, "height": 3000}
        )

            

        # Realistic headers
        page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            )
        })

        # STEP 0 — Load homepage
        print("[Step 0] Loading BN homepage...")
        page.goto("https://www.barnesandnoble.com", timeout=45000)
        page.wait_for_timeout(2000)

        # Accept cookies
        try:
            page.click('button:has-text("Accept All Cookies")', timeout=3000)
            print("[Step 0] Accepted cookies")
        except:
            print("[Step 0] No cookie popup")

        # STEP 1 — Search ISBN
        print("[Step 1] Typing ISBN into search bar...")

        search_selectors = [
            "input[placeholder*='Search by']",
            "input.rbt-input-main",
            "input[role='combobox']",
            "input[type='text']"
        ]

        search_box = None
        for selector in search_selectors:
            try:
                el = page.wait_for_selector(selector, timeout=2000)
                if el:
                    search_box = selector
                    break
            except:
                pass

        if not search_box:
            print("❌ Could not find search bar")
            browser.close()
            return {"stores": ["Online Only"], "release_date": None, "error": "Search bar not found"}

        page.fill(search_box, isbn)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

        # STEP 2 — Click correct product result
        print("[Step 2] Clicking correct product result...")

        link = page.query_selector(f"a[href*='{isbn}']")
        if not link:
            print("❌ Could not find product link matching ISBN")
            browser.close()
            return {"stores": ["Online Only"], "release_date": None, "error": "Product link not found"}

        link.click()

        # DO NOT USE networkidle — BN never reaches it
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)

        print("[Step 2] Arrived at product page:", page.url)

        print("[Step 3] Waiting for Find in Stores button to appear...")

        try:
            button = page.wait_for_selector("input[value='FIND IN STORES']", timeout=8000)
        except:
            print("❌ Find in Stores button never appeared")
            browser.close()
            return {"stores": ["Online Only"], "release_date": None, "error": "Button never appeared"}

        print("[Step 3] Found Find in Stores button")




        print("[Step 4] Opening Find in Stores modal...")
        button.click()

        print("[Step 4] Waiting for modal container...")

        try:
            page.wait_for_selector(".ss-modal", timeout=10000)
        except Exception as e:
            print("❌ Modal container never appeared:", e)
            browser.close()
            return {"stores": ["Online Only"], "release_date": None, "error": "Modal did not appear"}

        print("[Step 4] Waiting for store list...")

        try:
            page.wait_for_selector(".store-list", timeout=10000)
        except Exception as e:
            print("❌ Store list never appeared:", e)
            browser.close()
            return {"stores": ["Online Only"], "release_date": None, "error": "Store list did not load"}

        # Give React time to hydrate the list
        page.wait_for_timeout(500)

        modal_html = page.content()
        browser.close()



    # STEP 5 — Parse modal HTML
    soup = BeautifulSoup(modal_html, "html.parser")
    store_blocks = soup.select(".list-of-stores .store-list")

    stores_in_stock = []

    for block in store_blocks:
        name_el = block.select_one("h3.store-name")
        status_el = block.select_one("p[aria-label]")

        if not name_el or not status_el:
            continue

        store_name = name_el.get_text(strip=True)
        status = status_el.get("aria-label", "")

        if "In Stock" in status:
            stores_in_stock.append(store_name)

    if not stores_in_stock:
        stores_in_stock = ["Online Only"]

    return {
        "stores": stores_in_stock,
        "release_date": None
    }
