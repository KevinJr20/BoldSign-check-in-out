import sqlite3

def add_employee(employee_id, name, fingerprint_template):
    conn = sqlite3.connect("data/biometric_attendance.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO employees (employee_id, name, fingerprint_template) VALUES (?, ?, ?)",
        (employee_id, name, fingerprint_template),
    )
    conn.commit()
    conn.close()
    print(f"Added {name} ({employee_id}) to registry.")

if __name__ == "__main__":
    employees = [
        ("SFK000", "Kevin Omondi Jr.", "encrypted_fingerprint_SFK000"),
        ("SFK001", "Rowan Sam", "encrypted_fingerprint_SFK001"),
        ("SFK002", "Brenda Nelson", "encrypted_fingerprint_SFK002"),
        ("SFK003", "Simon Madeba", "encrypted_fingerprint_SFK003"),
    ]
    for emp_id, name, fp in employees:
        add_employee(emp_id, name, fp)