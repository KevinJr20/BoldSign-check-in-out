import sqlite3
conn = sqlite3.connect("data/biometric_attendance.db")
cursor = conn.cursor()
employees = [
    ("SFK000", "Kevin Omondi", "encrypted_fingerprint_SFK000"),
    ("SFK001", "Rowan Sam", "encrypted_fingerprint_SFK001"),
    ("SFK002", "Brenda Nelson", "encrypted_fingerprint_SFK002"),
    ("SFK003", "Simon Madeba", "encrypted_fingerprint_SFK003"),
]
cursor.execute("DELETE FROM employees")
for emp_id, name, fp in employees:
    cursor.execute("INSERT INTO employees (employee_id, name, fingerprint_template) VALUES (?, ?, ?)", (emp_id, name, fp))
conn.commit()
conn.close()
print("Employee registry updated.")
