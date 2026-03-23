import sqlite3


conn = sqlite3.connect("manga.db")
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(cursor.fetchall())  # This will list all tables

conn.close()

def inspect_database(db_path="manga.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("📦 Connected to database:", db_path)

    # Show all table names
    print("\n📋 Tables in the database:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for name, in tables:
        print(f"  - {name}")

    # Show schemas
    for name, in tables:
        print(f"\n🧩 Schema for table: {name}")
        cursor.execute(f"PRAGMA table_info({name});")
        schema = cursor.fetchall()
        for col in schema:
            print(f"  {col[1]} ({col[2]})")

    # Optional: Show sample data from `series`
    if any(t[0] == 'series' for t in tables):
        print("\n📄 Sample data from 'series':")
        cursor.execute("SELECT * FROM series LIMIT 5;")
        rows = cursor.fetchall()
        for row in rows:
            print(row)

    conn.close()

if __name__ == "__main__":
    inspect_database()
