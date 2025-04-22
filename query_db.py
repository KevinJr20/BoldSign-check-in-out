import sqlite3
conn = sqlite3.connect("data/biometric_attendance.db")
cursor = conn.cursor()
print("Employees:")
cursor.execute("SELECT * FROM employees")
for row in cursor.fetchall():
    print(row)
print("\nAttendance for SFK000:")
cursor.execute("SELECT * FROM attendance WHERE employee_id='SFK000'")
for row in cursor.fetchall():
    print(row)
print("\nAudit Log for SFK000:")
cursor.execute("SELECT * FROM audit_log WHERE employee_id='SFK000'")
for row in cursor.fetchall():
    print(row)
conn.close()
