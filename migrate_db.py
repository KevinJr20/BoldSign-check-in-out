import sqlite3
import logging

logging.basicConfig(level=logging.INFO, filename='migrate.log')
logger = logging.getLogger(__name__)

DB_PATH = 'data/biometric_attendance.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Transactions table
        cursor.execute("PRAGMA table_info(transactions)")
        columns = [col['name'] for col in cursor.fetchall()]
        if 'amount' not in columns:
            logger.info("Adding 'amount' column to transactions table")
            cursor.execute("ALTER TABLE transactions ADD COLUMN amount FLOAT NOT NULL DEFAULT 0.0")
        if 'payment_method' not in columns:
            logger.info("Adding 'payment_method' column to transactions table")
            cursor.execute("ALTER TABLE transactions ADD COLUMN payment_method TEXT")

        # Users table
        cursor.execute("PRAGMA table_info(users)")
        columns = [col['name'] for col in cursor.fetchall()]
        if 'name' not in columns:
            logger.info("Adding 'name' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN name TEXT")
            cursor.execute("UPDATE users SET name = 'Admin User' WHERE username = 'admin'")
        if 'role' not in columns:
            logger.info("Adding 'role' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin'")
            cursor.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")

        # Employees table
        cursor.execute("PRAGMA table_info(employees)")
        columns = [col['name'] for col in cursor.fetchall()]
        if 'email' not in columns:
            logger.info("Adding 'email' column to employees table")
            cursor.execute("ALTER TABLE employees ADD COLUMN email TEXT")
        if 'role' not in columns:
            logger.info("Adding 'role' column to employees table")
            cursor.execute("ALTER TABLE employees ADD COLUMN role TEXT")
        if 'organization_id' not in columns:
            logger.info("Adding 'organization_id' column to employees table")
            cursor.execute("ALTER TABLE employees ADD COLUMN organization_id TEXT")
            cursor.execute("UPDATE employees SET organization_id = 'admin' WHERE organization_id IS NULL")

        conn.commit()
        logger.info("Database migration completed successfully")
    except sqlite3.Error as e:
        logger.error(f"Migration error: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate_db()