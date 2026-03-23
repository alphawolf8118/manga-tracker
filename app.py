from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
import sqlite3
from datetime import date
from datetime import datetime
from seven_seas_scraper import update_all_seven_seas, update_release_dates_for_title
from threading import Thread
from db import get_db_connection
import re
import io
import csv
from constants import COMMON_TAGS


seven_seas_progress = {"total": 0, "current": 0, "done": False}


def init_db():
    conn = sqlite3.connect("manga.db")
    cursor = conn.cursor()

    # Series table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            publisher TEXT NOT NULL,
            status TEXT NOT NULL,
            url TEXT NOT NULL,
            total_volumes INTEGER
        )
    """)

    # Volumes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS volumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            volume_number INTEGER NOT NULL,
            purchased BOOLEAN DEFAULT 0,
            base_price REAL,
            amazon_price REAL,
            bn_location TEXT,
            release_date TEXT,
            FOREIGN KEY(series_id) REFERENCES series(id)
        )
    """)

    conn.commit()
    conn.close()


# Call it before app starts
init_db()

#conn = sqlite3.connect("manga.db")
#conn.execute("ALTER TABLE series ADD COLUMN type TEXT")
#conn.commit()
#conn.close()




app = Flask(__name__)

DB = "manga.db"

@app.context_processor
def inject_common_tags():
    return dict(common_tags=COMMON_TAGS)

@app.route("/")
def index():
    status_filter = request.args.get("status")
    location_filter = request.args.get("location")  # NEW
    conn = get_db_connection()

    if status_filter:
        series = conn.execute("SELECT * FROM series WHERE status = ? ORDER BY title", (status_filter,)).fetchall()
    else:
        series = conn.execute("SELECT * FROM series ORDER BY title").fetchall()

    # Get unpurchased volumes grouped by series
    volumes_by_series = {}
    all_locations = set()
    city_state_pattern = re.compile(r"[A-Za-z .'-]+,\s*[A-Z]{2}")
    for s in series:
        volumes = conn.execute("""
            SELECT volume_number, bn_location, release_date, base_price, amazon_price
            FROM volumes 
            WHERE series_id = ? AND purchased = 0
            ORDER BY volume_number
        """, (s["id"],)).fetchall()
        vols = []
        for vol in volumes:
            vol = dict(vol)
            # Extract all "City, ST" pairs from bn_location
            if vol["bn_location"]:
                matches = city_state_pattern.findall(vol["bn_location"])
                for loc in matches:
                    loc = loc.strip()
                    if loc.lower() != "online only":
                        all_locations.add(loc)
            # ...existing price/discount logic...
            try:
                base_price = float(vol["base_price"]) if vol["base_price"] else 0.0
                amazon_price = float(vol["amazon_price"]) if vol["amazon_price"] else 0.0
                vol["discount"] = base_price - amazon_price
                vol["discount_abs"] = abs(vol["discount"])
                if base_price > 0:
                    vol["discount_pct"] = (vol["discount"] / base_price) * 100
                else:
                    vol["discount_pct"] = 0.0
            except (ValueError, TypeError):
                vol["discount"] = 0.0
                vol["discount_abs"] = 0.0
                vol["discount_pct"] = 0.0
            vols.append(vol)
        volumes_by_series[s["id"]] = vols

    conn.close()
    all_locations = sorted([loc for loc in all_locations if loc and loc.lower() != "online only"])  # Clean up
    return render_template(
        "index.html",
        series=series,
        volumes_by_series=volumes_by_series,
        status_filter=status_filter,
        location_filter=location_filter,
        all_locations=all_locations
    )

@app.route("/add", methods=("GET", "POST"))
def add_series():
    if request.method == "POST":
        title = request.form["title"].strip()
        type = request.form["type"].strip()
        # Add type to title if not already present
        if not title.lower().endswith(f"({type.lower()})"):
            title = f"{title} ({type})"
        publisher = request.form["publisher"]
        status = request.form["status"]
        total_volumes = request.form["total_volumes"]
        url = request.form.get("url", "").strip()  # Add the URL field here
        base_price = request.form.get("base_price", "").strip()
        try:
            base_price = float(base_price) if base_price else 0.0
        except ValueError:
            base_price = 0.0
        # Handle tags from multi-select
        selected_tags = request.form.getlist('tags[]')
        tags_str = ','.join(selected_tags) if selected_tags else None

        # Normalize (optional)
        if tags_str:
            tag_list = [t.strip().lower() for t in tags_str.split(',') if t.strip()]
            tags_str = ','.join(sorted(set(tag_list)))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO series (title, type, publisher, status, total_volumes, url) VALUES (?, ?, ?, ?, ?, ?)",
            (title, type, publisher, status, total_volumes, url)
        )
        series_id = cursor.lastrowid

        # Auto-create volumes if total_volumes is a valid integer
        try:
            total = int(total_volumes)
            for vol_num in range(1, total + 1):
                cursor.execute(
                    "INSERT INTO volumes (series_id, volume_number, base_price, amazon_price) VALUES (?, ?, ?, ?)",
                    (series_id, vol_num, base_price, base_price)
                )
        except Exception as e:
            print(f"Could not auto-create volumes: {e}")

        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("add_series.html")

@app.route("/edit/<int:id>", methods=("GET", "POST"))
def edit_series(id):
    conn = get_db_connection()
    series = conn.execute("SELECT * FROM series WHERE id = ?", (id,)).fetchone()

    if series is None:
        conn.close()
        return "Series not found", 404  # Or redirect to index with a flash message
    
    if request.method == "POST":
        title = request.form["title"].strip()
        # ... other fields ...
        selected_tags = request.form.getlist('tags[]')  # ← This gets the list from multi-select
        tags = ','.join(selected_tags) if selected_tags else None

        # Normalize tags (good practice)
        if tags:
            tag_list = [t.strip().lower() for t in tags.split(',') if t.strip()]
            tags = ','.join(sorted(set(tag_list)))  # remove dups, sort

        type = request.form["type"].strip()
                # Add type to title if not already present
        if not title.lower().endswith(f"({type.lower()})"):
            title = f"{title} ({type})"
        status = request.form["status"]
        total_volumes = request.form["total_volumes"]
        publisher = request.form["publisher"]
        url = request.form["url"]  # Add the URL field here

        conn.execute(
            "UPDATE series SET title = ?, type = ?, publisher = ?, status = ?, total_volumes = ?, url = ?, tags = ? WHERE id = ?",
            (title, type, publisher, status, total_volumes, url, tags, id)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    conn.close()
    return render_template("edit_series.html", series=series)

@app.route("/delete/<int:id>", methods=["GET"])
def delete_series(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM series WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

@app.template_filter('release_status_color')
def release_status_color(date_str):
    if not date_str:
        return ""
    try:
        # Try parsing as YYYY-MM-DD or as "Mon DD, YYYY"
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            date_obj = datetime.strptime(date_str, "%b %d, %Y")
        today = datetime.today().date()
        if date_obj.date() > today:
            return "text-red-600 font-bold"
        elif date_obj.date() == today:
            return "text-blue-600 font-bold"
        else:
            return "text-green-600 font-bold"
    except Exception:
        return ""

@app.route("/series/<int:series_id>")
def view_series(series_id):
    conn = get_db_connection()
    series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    volumes = conn.execute("SELECT * FROM volumes WHERE series_id = ? ORDER BY volume_number", (series_id,)).fetchall()
    conn.close()

    volumes = [dict(vol) for vol in volumes]  # convert all to dicts

    # Calculate discount for each volume
    for vol in volumes:
        try:
            base_price = float(vol["base_price"]) if vol["base_price"] else 0.0
            amazon_price = float(vol["amazon_price"]) if vol["amazon_price"] else 0.0

            vol["discount"] = base_price - amazon_price
            vol["discount_abs"] = abs(vol["discount"])

            if base_price > 0:
                vol["discount_pct"] = (vol["discount"] / base_price) * 100
            else:
                vol["discount_pct"] = 0.0
        except (ValueError, TypeError):
            vol["discount"] = 0.0
            vol["discount_abs"] = 0.0
            vol["discount_pct"] = 0.0


    return render_template("series_detail.html", series=series, volumes=volumes, now=str(date.today()))


@app.route("/series/<int:series_id>/add-volume", methods=["GET", "POST"])
def add_volume(series_id):
    if request.method == "POST":
        volume_input = request.form["volume_number"]
        purchased = 1 if "purchased" in request.form else 0
        base_price = request.form.get("base_price", "").strip()
        try:
            base_price = float(base_price)
        except ValueError:
            base_price = 0.0

        amazon_price = request.form.get("amazon_price", "").strip()
        try:
            amazon_price = float(amazon_price) if amazon_price else base_price
        except ValueError:
            amazon_price = base_price
        bn_location = request.form.get("bn_location", "")
        release_date = request.form.get("release_date", "")

        base_price = float(base_price)
        amazon_price = float(amazon_price)

        # Handle ranges like "1-5"
        volume_input = volume_input.strip()
        volume_numbers = []

        if not volume_input:
            return "Volume number is required", 400

        if "-" in volume_input:
            try:
                parts = volume_input.split("-")
                if len(parts) != 2:
                    raise ValueError("Invalid range format")
                start, end = map(int, parts)
                if start > end:
                    raise ValueError("Start of range cannot be greater than end")
                volume_numbers = list(range(start, end + 1))
            except ValueError:
                return "Invalid volume range format", 400
        else:
            try:
                volume_numbers = [int(volume_input)]
            except ValueError:
                return "Invalid volume number", 400


        conn = get_db_connection()
        for num in volume_numbers:
            conn.execute("""
                INSERT INTO volumes (series_id, volume_number, purchased, base_price, amazon_price, bn_location, release_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (series_id, num, purchased, base_price, amazon_price, bn_location, release_date))
        conn.commit()
        conn.close()

        return redirect(url_for("view_series", series_id=series_id))

    return render_template("add_volume.html", series_id=series_id)

@app.route('/edit-volume/<int:volume_id>', methods=['GET', 'POST'])
def edit_volume(volume_id):
    conn = get_db_connection()
    volume = conn.execute("SELECT * FROM volumes WHERE id = ?", (volume_id,)).fetchone()

    if not volume:
        return "Volume not found", 404

    if request.method == 'POST':
        # ... your existing fields (volume_number, purchased, prices, etc.) ...

        # Handle tags from multi-select
        selected_tags = request.form.getlist('tags[]')
        tags_str = None
        if selected_tags:
            tag_list = [t.strip().lower() for t in selected_tags if t.strip()]
            tags_str = ','.join(sorted(set(tag_list)))  # remove dups, sort, lowercase

        # Your UPDATE query - add tags
        conn.execute("""
            UPDATE volumes
            SET volume_number = ?, purchased = ?, base_price = ?, amazon_price = ?,
                bn_location = ?, release_date = ?, tags = ?
            WHERE id = ?
        """, (
            request.form['volume_number'],
            1 if 'purchased' in request.form else 0,
            request.form.get('base_price'),
            request.form.get('amazon_price'),
            request.form.get('bn_location'),
            request.form.get('release_date'),
            tags_str,
            volume_id
        ))

        conn.commit()
        conn.close()
        return redirect(url_for('view_series', series_id=volume['series_id']))

    conn.close()
    return render_template('edit_volume.html', volume=volume, common_tags=COMMON_TAGS)

@app.route("/volume/<int:volume_id>/delete", methods=["POST"])
def delete_volume(volume_id):
    conn = get_db_connection()
    volume = conn.execute("SELECT * FROM volumes WHERE id = ?", (volume_id,)).fetchone()
    conn.execute("DELETE FROM volumes WHERE id = ?", (volume_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("view_series", series_id=volume["series_id"]))


@app.route("/toggle-purchased/<int:volume_id>", methods=["POST"])
def toggle_purchased(volume_id):
    conn = get_db_connection()
    volume = conn.execute("SELECT purchased FROM volumes WHERE id = ?", (volume_id,)).fetchone()
    new_status = 0 if volume["purchased"] else 1

    if new_status == 1:
        # If purchased, clear bn_location
        conn.execute("UPDATE volumes SET purchased = ?, bn_location = '' WHERE id = ?", (new_status, volume_id))
    else:
        conn.execute("UPDATE volumes SET purchased = ? WHERE id = ?", (new_status, volume_id))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True, "purchased": new_status})



@app.route("/update-series/<int:series_id>", methods=["POST"])
def update_series_releases_route(series_id):
    conn = get_db_connection()
    print(f"Updating series with ID: {series_id}")
    series = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    conn.close()

    if not series:
        return "❌ Series not found", 404

    if series["status"] not in ("Collecting", "Interested", "On Hold"):
        return f"🚫 Skipping {series['title']} — not marked for tracking.", 400

    title = series["title"]
    publisher = (series["publisher"] or "").lower()
    series_url = series["url"]
    series_type = series["type"] or "manga"

    # Call the correct update function based on publisher
    if "seven seas" in publisher:
        update_release_dates_for_title(title, series_id, series_url)
    elif "yen press" in publisher:
        from seven_seas_scraper import update_release_dates_for_yen_press
        update_release_dates_for_yen_press(title, series_id, series_url, series_type)
    elif "viz" in publisher:
        from seven_seas_scraper import update_release_dates_for_viz
        update_release_dates_for_viz(title, series_id, series_url, series_type)
    elif "kodansha" in publisher:
        from seven_seas_scraper import update_release_dates_for_kodansha
        update_release_dates_for_kodansha(title, series_id, series_url, series_type)
    elif "square enix" in publisher:
        from seven_seas_scraper import update_release_dates_for_square_enix
        update_release_dates_for_square_enix(title, series_id, series_url, series_type)
    elif "one peace" in publisher:
        from seven_seas_scraper import update_isbns_for_one_peace_books
        update_isbns_for_one_peace_books(series_id, series_url)
    elif "kaitenbooks" in publisher.lower():
        from seven_seas_scraper import update_release_dates_for_kaitenbooks
        update_release_dates_for_kaitenbooks(title, series_id, series_url, series_type)

    else:
        return f"⚠️ Unsupported publisher: {series['publisher']}", 400


    return "✅ Series updated successfully!", 200

from flask import redirect, url_for, flash

@app.route("/update-volume-isbn/<int:volume_id>", methods=["POST"])
def update_volume_isbn(volume_id):
    data = request.get_json()
    isbn = data.get("isbn", "").strip().replace("-", "")  # Clean dashes

    conn = get_db_connection()
    conn.execute("UPDATE volumes SET isbn = ? WHERE id = ?", (isbn or None, volume_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route("/check-bn-inventory/<int:series_id>", methods=["POST"])
def check_bn_inventory_route(series_id):
    from bn_inventory_scraper import scrape_bn_store_inventory
    from db import get_db_connection
    from datetime import date

    conn = get_db_connection()
    volumes = conn.execute(
        """
        SELECT volume_number, isbn, release_date FROM volumes
        WHERE series_id = ? AND isbn IS NOT NULL AND purchased = 0
        AND release_date IS NOT NULL AND release_date <= ?
        """,
        (series_id, date.today())
    ).fetchall()
    conn.close()

    for vol in volumes:
        result = scrape_bn_store_inventory(vol["isbn"])
        stores = result["stores"]
        locations_str = ", ".join(stores)
        scraped_date = result.get("release_date")  # Safe access
        conn = get_db_connection()
        conn.execute(
            "UPDATE volumes SET bn_location = ? WHERE series_id = ? AND volume_number = ?",
            (locations_str, series_id, vol["volume_number"])
        )
        if scraped_date and (not vol["release_date"] or vol["release_date"].strip() == ""):
            conn.execute(
                "UPDATE volumes SET release_date = ? WHERE series_id = ? AND volume_number = ?",
                (scraped_date, series_id, vol["volume_number"])
            )
            print(f"Updated release_date for vol {vol['volume_number']} to {scraped_date}")
        conn.commit()
        conn.close()

    from flask import jsonify

    return jsonify({"success": True})

@app.route("/check-bn-inventory-volume/<int:volume_id>", methods=["POST"])
def check_bn_inventory_volume_route(volume_id):
    from bn_inventory_scraper import scrape_bn_store_inventory
    from db import get_db_connection

    conn = get_db_connection()
    vol = conn.execute(
        "SELECT isbn, release_date FROM volumes WHERE id = ?", (volume_id,)
    ).fetchone()
    conn.close()

    if not vol or not vol["isbn"]:
        return {"success": False, "error": "No ISBN found."}, 400

    result = scrape_bn_store_inventory(vol["isbn"])  # ← Get the dict with "stores" and "release_date"
    
    stores = result["stores"]
    locations_str = ", ".join(stores)
    scraped_date = result.get("release_date")  # Safe access, None if not found
    conn = get_db_connection()
    conn.execute(
        "UPDATE volumes SET bn_location = ? WHERE id = ?",
        (locations_str, volume_id)
    )
    # NEW: Update release_date only if currently empty
    if scraped_date and (not vol["release_date"] or vol["release_date"].strip() == ""):
        conn.execute(
            "UPDATE volumes SET release_date = ? WHERE id = ?",
            (scraped_date, volume_id)
        )
        print(f"Updated release_date for volume_id {volume_id} to {scraped_date}")
    conn.commit()
    conn.close()

    return {"success": True}


@app.route("/update-seven-seas-all")
def update_seven_seas_all_route():
    conn = get_db_connection()
    series_list = conn.execute("""
        SELECT id, title FROM series
        WHERE publisher = 'Seven Seas' AND status IN ('Collecting', 'Interested', 'On Hold')
    """).fetchall()
    conn.close()

    updated = []

    for s in series_list:
        title = s["title"].lower()
        update_release_dates_for_title(title, s["id"])
        updated.append(s["title"])

    print("✅ Finished updating:", updated)
    return redirect(url_for("index"))

# Progress tracker
seven_seas_progress = {
    "current": 0,
    "total": 0,
    "done": False
}

@app.route("/api/update-seven-seas-progress")
def update_all_seven_seas_background():
    def run_scraper():
        from seven_seas_scraper import update_all_seven_seas
        update_all_seven_seas(progress=seven_seas_progress)

    # Reset progress
    seven_seas_progress["current"] = 0
    seven_seas_progress["total"] = 0
    seven_seas_progress["done"] = False

    Thread(target=run_scraper).start()
    return jsonify({"status": "started"})

@app.route("/api/seven-seas-progress")
def get_seven_seas_progress():
    return jsonify(seven_seas_progress)

# Progress tracker for general update
general_progress = {
    "current": 0,
    "total": 0,
    "done": False
}

@app.route("/api/update-all-general-progress")
def update_all_general_background():
    def run_scraper():
        from seven_seas_scraper import update_all_general
        update_all_general(progress=general_progress)

    # Reset progress
    general_progress["current"] = 0
    general_progress["total"] = 0
    general_progress["done"] = False

    Thread(target=run_scraper).start()
    return jsonify({"status": "started"})

@app.route("/api/general-progress")
def get_general_progress():
    return jsonify(general_progress)

@app.route("/manual-update-seven-seas")
def update_all_seven_seas_route():
    from threading import Thread

    def run_scraper():
        update_all_seven_seas()

    # Run scraper in background thread so browser doesn’t hang
    Thread(target=run_scraper).start()
    return jsonify({"status": "started"})

@app.route("/scrape-volume/<int:volume_id>", methods=["POST"])
def scrape_volume(volume_id):
    conn = get_db_connection()
    volume = conn.execute("SELECT * FROM volumes WHERE id = ?", (volume_id,)).fetchone()
    if not volume:
        conn.close()
        return "❌ Volume not found", 404

    series = conn.execute("SELECT * FROM series WHERE id = ?", (volume["series_id"],)).fetchone()
    if not series:
        conn.close()
        return "❌ Series not found", 404

    publisher = (series["publisher"] or "").lower()
    volume_url = volume["url"]
    series_id = volume["series_id"]
    volume_number = volume["volume_number"]
    series_url = series["url"]

    # --- Auto-fetch URL if missing ---
    if not volume_url and "viz" in publisher:
        from seven_seas_scraper import find_viz_volume_url_in_series
        volume_url = find_viz_volume_url_in_series(series_url, volume_number)
        if volume_url:
            conn.execute("UPDATE volumes SET url = ? WHERE id = ?", (volume_url, volume_id))
            conn.commit()
        else:
            conn.close()
            return "❌ Could not find URL for this volume.", 400
    conn.close()
    # ----------------------------------

    # Import your single-volume scrapers
    from seven_seas_scraper import (
    scrape_single_viz_volume,
    scrape_single_seven_seas_volume,
    scrape_single_yen_press_volume,
    scrape_single_kodansha_volume,
    scrape_single_square_enix_volume,
    scrape_single_one_peace_volume,
)

    # Dispatch to the correct scraper
    if "viz" in publisher:
        scrape_single_viz_volume(volume_url, series_id, volume_number)
    elif "seven seas" in publisher:
        scrape_single_seven_seas_volume(volume_url, series_id, volume_number)
    elif "yen press" in publisher:
        scrape_single_yen_press_volume(volume_url, series_id, volume_number)
    elif "kodansha" in publisher:
        scrape_single_kodansha_volume(volume_url, series_id, volume_number)
    elif "square enix" in publisher:
        scrape_single_square_enix_volume(volume_url, series_id, volume_number)
    elif "one peace" in publisher:
        scrape_single_one_peace_volume(volume_url, series_id, volume_number)
    else:
        return f"⚠️ Unsupported publisher: {series['publisher']}", 400

    return redirect(url_for("view_series", series_id=series_id))

from flask import request, jsonify

@app.route("/update-volume-tags/<int:volume_id>", methods=["POST"])
def update_volume_tags(volume_id):
    data = request.get_json()
    tags = data.get("tags", "").strip()

    # Normalize (lowercase, dedup, sort)
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(',') if t.strip()]
        tags = ','.join(sorted(set(tag_list)))
    else:
        tags = None

    conn = get_db_connection()
    conn.execute("UPDATE volumes SET tags = ? WHERE id = ?", (tags, volume_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route("/update-series-tags/<int:series_id>", methods=["POST"])
def update_series_tags(series_id):
    data = request.get_json()
    tags = data.get("tags", "").strip()
    # Optional: clean up (remove spaces, lowercase, etc.)
    tags = ",".join(t.strip().lower() for t in tags.split(",") if t.strip())

    conn = get_db_connection()
    conn.execute("UPDATE series SET tags = ? WHERE id = ?", (tags, series_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route("/export_all")
def export_all_unpurchased():
    conn = get_db_connection()

    # Pull all unpurchased volumes with status
    rows = conn.execute("""
        SELECT 
            s.title AS series_name,
            s.status AS series_status,
            v.volume_number,
            v.release_date,
            v.base_price,
            v.amazon_price
        FROM volumes v
        JOIN series s ON v.series_id = s.id
        WHERE v.purchased = 0
            AND DATE(v.release_date) <= DATE('now')
        ORDER BY s.status, s.title, v.volume_number
    """).fetchall()

    conn.close()

    # Group rows by status
    grouped = {}
    for row in rows:
        status = row["series_status"]
        grouped.setdefault(status, []).append(row)

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)

    for status, items in grouped.items():
        # Section header
        writer.writerow([f"=== {status.upper()} ==="])
        # Column headers
        writer.writerow(["Series Name", "Volume Number", "Release Date", "Amazon Discount"])

        for row in items:
            base = float(row["base_price"]) if row["base_price"] else 0.0
            amazon = float(row["amazon_price"]) if row["amazon_price"] else 0.0
            discount_pct = ((base - amazon) / base * 100) if base > 0 else 0.0

            writer.writerow([
                row["series_name"],
                row["volume_number"],
                row["release_date"],
                f"{discount_pct:.1f}%"
            ])

        # Blank line between sections
        writer.writerow([])

    today_str = datetime.now().strftime("%m-%d-%Y")

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=all_unpurchased_volumes_{today_str}.csv"
        }
    )



@app.context_processor
def utility_processor():
    def get_volumes(series_id):
        conn = get_db_connection()
        volumes = conn.execute("SELECT * FROM volumes WHERE series_id = ?", (series_id,)).fetchall()
        conn.close()
        return volumes
    return dict(get_volumes=get_volumes)

# ====================
# MANUAL B&N PARSER
# ====================

from bs4 import BeautifulSoup
import re

def parse_instock_stores(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    instock = []

    for store_block in soup.find_all('div', class_='store-list'):
        # Get status first (fast fail if not in stock)
        status_tag = store_block.find('p', attrs={'aria-label': True})
        if not status_tag:
            continue
        status = status_tag.get('aria-label', '').strip()
        if 'In Stock in Store' not in status:
            continue

        # Now extract town and state from the address <p>
        address_p = store_block.find('p', class_='mt-0 mb-xs')
        if address_p:
            # The structure is: <span>Town,</span>&nbsp;<span>ST</span>&nbsp;<span>ZIP</span>
            spans = address_p.find_all('span')
            if len(spans) >= 2:
                town = spans[0].get_text(strip=True).rstrip(',')
                state = spans[1].get_text(strip=True)
                location = f"{town}, {state}"
                if location not in instock:
                    instock.append(location)

        # Fallback: if spans fail, scrape the whole p text
        else:
            address_text = store_block.get_text(strip=True)
            match = re.search(r'([A-Za-z\s\.\-\']+),\s*([A-Z]{2})', address_text)
            if match:
                town, state = match.groups()
                location = f"{town}, {state}"
                if location not in instock:
                    instock.append(location)

    if instock:
        return ", ".join(sorted(instock))
    else:
        return "Online Only"


@app.route("/manual-bn-parse/<int:volume_id>", methods=["GET", "POST"])
def manual_bn_parse(volume_id):
    conn = get_db_connection()
    volume = conn.execute("SELECT series_id, isbn, volume_number FROM volumes WHERE id = ?", (volume_id,)).fetchone()
    conn.close()

    if not volume:
        return "Volume not found", 404

    message = None

    if request.method == "POST":
        raw_html = request.form.get("raw_html", "").strip()

        if raw_html:
            try:
                result = parse_instock_stores(raw_html)
                if result and "No stores" not in result:  # optional: only save if useful
                    conn = get_db_connection()
                    conn.execute("UPDATE volumes SET bn_location = ? WHERE id = ?", (result, volume_id))
                    conn.commit()
                    conn.close()
                    print(f"Saved '{result}' to volume {volume_id}")  # debug
                    return redirect(url_for("view_series", series_id=volume["series_id"]))
                else:
                    message = "Nothing useful to save — no in-stock stores found."
            except Exception as e:
                message = f"Error: {str(e)} — Try copying the full store list again."
        else:
            message = "Paste the HTML first."

    return render_template(
        "manual_bn_parse.html",
        volume_id=volume_id,
        isbn=volume["isbn"],
        vol_number=volume["volume_number"],
        series_id=volume["series_id"],
        message=message,
        volume=volume
    )

if __name__ == "__main__":
    app.run(debug=True)
