import sqlite3
conn = sqlite3.connect("data/biometric_attendance.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
print(cursor.fetchone())
conn.close()
