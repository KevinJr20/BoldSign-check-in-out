import sqlite3
conn = sqlite3.connect("data/biometric_attendance.db")
conn.execute("DELETE FROM attendance WHERE employee_id='SFK000' AND date='2025-04-22'")
conn.execute("DELETE FROM audit_log WHERE employee_id='SFK000'")
conn.commit()
conn.close()
