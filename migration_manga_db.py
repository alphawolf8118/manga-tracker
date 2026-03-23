import sqlite3

# Connect to your database
conn = sqlite3.connect('manga.db')
cursor = conn.cursor()

# Get all series entries
cursor.execute("SELECT id, title, type FROM series")
rows = cursor.fetchall()

for series_id, title, type in rows:
    if not type:
        continue  # Skip if no type

    # Make sure title doesn't already have the type
    if f"({type})" not in title:
        new_title = f"{title.strip()} ({type.strip()})"
        cursor.execute("UPDATE series SET title = ? WHERE id = ?", (new_title, series_id))
        print(f"Updated: {title} → {new_title}")

# Commit changes and close the connection
conn.commit()
conn.close()
print("✅ Done updating titles.")
