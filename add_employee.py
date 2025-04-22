import sqlite3
conn = sqlite3.connect("data/biometric_attendance.db")
conn.execute("INSERT OR IGNORE INTO employees (employee_id, name, fingerprint_template) VALUES ('SFK000', 'Kevin Omondi', 'encrypted_fingerprint_SFK000')")
conn.commit()
conn.close()
