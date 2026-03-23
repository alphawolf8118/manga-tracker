import sqlite3

conn = sqlite3.connect("db.sqlite3")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT,
    owned_volumes TEXT,
    total_volumes INTEGER
)
""")

conn.commit()
conn.close()
