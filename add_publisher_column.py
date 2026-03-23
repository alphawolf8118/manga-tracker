import sqlite3

conn = sqlite3.connect("manga.db")
cursor = conn.cursor()

cursor.execute("ALTER TABLE series ADD COLUMN publisher TEXT")

conn.commit()
conn.close()
print("Publisher column added!")
