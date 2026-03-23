import sqlite3

# Connect to the database
conn = sqlite3.connect('square_enix.db')
cursor = conn.cursor()

# Insert test data into the volumes table
cursor.execute('''
    INSERT INTO volumes (series_id, volume_number, release_date, url)
    VALUES (?, ?, ?, ?)
''', (1, 1, '2025-04-22', 'https://example.com/volume1'))

# Commit changes and close the connection
conn.commit()

# Check if the data was inserted
cursor.execute('SELECT * FROM volumes WHERE series_id = 1')
print(cursor.fetchall())

conn.close()
