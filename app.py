import os
import logging
import json
import sqlite3
import base64
from datetime import datetime, date
from urllib.parse import urlparse
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO
from cryptography.fernet import Fernet
import jwt
import bcrypt
from passlib.hash import bcrypt as passlib_bcrypt
import smtplib
from email.mime.text import MIMEText
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*")

# Database configuration
DB_FILE = 'data/biometric_attendance.db'
DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    try:
        if DATABASE_URL:
            logging.info("Connecting to PostgreSQL database using DATABASE_URL")
            url = urlparse(DATABASE_URL)
            conn = psycopg2.connect(
                database=url.path[1:],
                user=url.username,
                password=url.password,
                host=url.hostname,
                port=url.port
            )
        else:
            logging.info(f"Connecting to SQLite database at {DB_FILE}")
            conn = sqlite3.connect(DB_FILE)
        logging.info("Database connection successful")
        return conn
    except Exception as e:
        logging.error(f"Failed to connect to database: {str(e)}")
        raise

# Encryption setup
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY not set in environment variables")

# Debug: Check the ENCRYPTION_KEY length and format
logging.info(f"ENCRYPTION_KEY: {ENCRYPTION_KEY}, Length: {len(ENCRYPTION_KEY)}")

# Validate ENCRYPTION_KEY
if len(ENCRYPTION_KEY) != 44:
    raise ValueError(f"ENCRYPTION_KEY must be 44 characters long, got {len(ENCRYPTION_KEY)} characters")

try:
    # Try decoding to ensure it's valid base64
    decoded_key = base64.urlsafe_b64decode(ENCRYPTION_KEY.encode())
    if len(decoded_key) != 32:
        raise ValueError(f"Decoded ENCRYPTION_KEY must be 32 bytes, got {len(decoded_key)} bytes")
    cipher = Fernet(ENCRYPTION_KEY.encode())
except Exception as e:
    logging.error(f"Failed to initialize Fernet cipher: {str(e)}")
    raise

# JWT setup
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'your-jwt-secret-key')

# Email configuration
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_TO = os.getenv('EMAIL_TO')

# Load configuration
with open('config.json', 'r') as f:
    config = json.load(f)

# Ensure static directories exist
os.makedirs('static/photos', exist_ok=True)
os.makedirs('static/exports', exist_ok=True)

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Create employees table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                fingerprint_template TEXT NOT NULL
            )
        ''')

        # Check if photo_url column exists and add it if missing
        if DATABASE_URL:  # PostgreSQL
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'employees'")
            columns = [row[0] for row in cursor.fetchall()]
            if 'photo_url' not in columns:
                cursor.execute('ALTER TABLE employees ADD COLUMN photo_url TEXT')
                logging.info("Added photo_url column to employees table (PostgreSQL)")
        else:  # SQLite
            cursor.execute("PRAGMA table_info(employees)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'photo_url' not in columns:
                cursor.execute('ALTER TABLE employees ADD COLUMN photo_url TEXT')
                logging.info("Added photo_url column to employees table (SQLite)")

        # Create attendance table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                timestamp INTEGER,
                employee_id TEXT,
                name TEXT,
                date TEXT,
                time_in TEXT,
                time_out TEXT,
                fingerprint TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
            )
        ''')

        # Create audit_log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                timestamp INTEGER,
                employee_id TEXT,
                action TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
            )
        ''')

        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        ''')

        # Insert default admin user if not exists
        default_password = passlib_bcrypt.hash('admin123')
        cursor.execute('INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)', ('admin', default_password))
        conn.commit()
        logging.info("Database initialized successfully")

init_db()

def send_notification(employee_id, name, action, time):
    if not all([EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO]):
        logging.warning("Email configuration missing, skipping notification")
        return
    try:
        msg = MIMEText(f"{name} ({employee_id}) {action} at {time}")
        msg['Subject'] = 'Attendance Update'
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        logging.info(f"Sent email notification for {employee_id} - {action}")
    except Exception as e:
        logging.error(f"Failed to send email notification: {str(e)}")

def verify_token(token):
    try:
        decoded = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        return decoded['username']
    except jwt.InvalidTokenError:
        return None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or not token.startswith('Bearer '):
            return jsonify({'status': 'error', 'message': 'Missing or invalid token'}), 401
        token = token.split(' ')[1]
        username = verify_token(token)
        if not username:
            return jsonify({'status': 'error', 'message': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date = ? ORDER BY timestamp DESC', (date.today().isoformat(),))
        records = cursor.fetchall()
    return render_template('dashboard.html', records=records, config=config, datetime=datetime)

@app.route('/attendance', methods=['GET'])
@require_auth
def get_attendance():
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        if not start_date or not end_date:
            current_date = datetime.now().strftime('%Y-%m-%d')
            start_date = end_date = current_date
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date BETWEEN ? AND ? ORDER BY timestamp DESC', (start_date, end_date))
            records = [{'employee_id': row[0], 'name': row[1], 'date': row[2], 'time_in': row[3], 'time_out': row[4]} for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'records': records})
    except Exception as e:
        logging.error(f"Error in get_attendance: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch attendance records.'}), 500

@app.route('/analytics', methods=['GET'])
@require_auth
def get_analytics():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT date, COUNT(DISTINCT employee_id) as active_employees FROM attendance GROUP BY date ORDER BY date DESC LIMIT 30')
            trends = [{'date': row[0], 'active_employees': row[1]} for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'trends': trends})
    except Exception as e:
        logging.error(f"Error in get_analytics: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch analytics.'}), 500

@app.route('/employees', methods=['GET'])
@require_auth
def list_employees():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, fingerprint_template, photo_url FROM employees')
            employees = []
            for row in cursor.fetchall():
                logging.debug(f"Fetched employee row: {row}")
                employees.append({
                    'employee_id': row[0],
                    'name': row[1],
                    'fingerprint_template': row[2],
                    'photo_url': row[3]
                })
        logging.info(f"Successfully fetched {len(employees)} employees")
        return jsonify({'status': 'success', 'employees': employees})
    except Exception as e:
        logging.error(f"Error in list_employees: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch employees.'}), 500

@app.route('/employees', methods=['POST'])
@require_auth
def add_employee():
    try:
        data = request.form
        employee_id = data.get('employee_id')
        name = data.get('name')
        fingerprint_template = data.get('fingerprint_template')
        photo = request.files.get('photo')
        photo_url = None
        if photo:
            filename = f"{employee_id}_{photo.filename}"
            photo_path = os.path.join('static', 'photos', filename)
            os.makedirs(os.path.dirname(photo_path), exist_ok=True)
            photo.save(photo_path)
            photo_url = f"/static/photos/{filename}"
        if not all([employee_id, name, fingerprint_template]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO employees (employee_id, name, fingerprint_template, photo_url) VALUES (?, ?, ?, ?)',
                           (employee_id, name, fingerprint_template, photo_url))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Employee ID already exists'}), 409
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Added {name} ({employee_id})'})
    except Exception as e:
        logging.error(f"Error in add_employee: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to add employee.'}), 500

@app.route('/employees/<employee_id>', methods=['PUT'])
@require_auth
def update_employee(employee_id):
    try:
        data = request.get_json()
        name = data.get('name')
        fingerprint_template = data.get('fingerprint_template')
        if not all([name, fingerprint_template]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE employees SET name = ?, fingerprint_template = ? WHERE employee_id = ?',
                           (name, fingerprint_template, employee_id))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Updated {name} ({employee_id})'})
    except Exception as e:
        logging.error(f"Error in update_employee: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to update employee.'}), 500

@app.route('/employees/<employee_id>', methods=['DELETE'])
@require_auth
def delete_employee(employee_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Deleted employee {employee_id}'})
    except Exception as e:
        logging.error(f"Error in delete_employee: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to delete employee.'}), 500

@app.route('/employees/bulk_delete', methods=['POST'])
@require_auth
def bulk_delete_employees():
    try:
        data = request.get_json()
        employee_ids = data.get('employee_ids', [])
        if not employee_ids:
            return jsonify({'status': 'error', 'message': 'No employee IDs provided'}), 400
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('DELETE FROM employees WHERE employee_id = ?', [(eid,) for eid in employee_ids])
            deleted_count = cursor.rowcount
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Deleted {deleted_count} employees'})
    except Exception as e:
        logging.error(f"Error in bulk_delete_employees: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to bulk delete employees.'}), 500

@app.route('/employees/bulk_import', methods=['POST'])
@require_auth
def bulk_import_employees():
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400
        file = request.files['file']
        if not file.filename.endswith('.csv'):
            return jsonify({'status': 'error', 'message': 'File must be a CSV'}), 400
        import pandas as pd
        import io
        df = pd.read_csv(io.StringIO(file.read().decode('utf-8')))
        expected_columns = ['employee_id', 'name', 'fingerprint_template']
        if not all(col in df.columns for col in expected_columns):
            return jsonify({'status': 'error', 'message': 'CSV must contain employee_id, name, fingerprint_template columns'}), 400
        with get_db_connection() as conn:
            cursor = conn.cursor()
            inserted = 0
            for _, row in df.iterrows():
                cursor.execute('INSERT OR IGNORE INTO employees (employee_id, name, fingerprint_template, photo_url) VALUES (?, ?, ?, ?)',
                               (row['employee_id'], row['name'], row['fingerprint_template'], None))
                inserted += cursor.rowcount
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Imported {inserted} employees'})
    except Exception as e:
        logging.error(f"Error in bulk_import_employees: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to import employees.'}), 500

@app.route('/employees/manage')
@require_auth
def manage_employees():
    return render_template('employees.html', config=config)

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({'status': 'error', 'message': 'Username and password required'}), 400
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
        if not user or not passlib_bcrypt.verify(password, user[0]):
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401
        token = jwt.encode({'username': username}, JWT_SECRET_KEY, algorithm='HS256')
        return jsonify({'status': 'success', 'token': token})
    except Exception as e:
        logging.error(f"Error in login: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Login failed.'}), 500

@app.route('/users', methods=['GET'])
@require_auth
def list_users():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT username FROM users')
            users = [{'username': row[0]} for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'users': users})
    except Exception as e:
        logging.error(f"Error in list_users: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch users.'}), 500

@app.route('/users', methods=['POST'])
@require_auth
def add_user():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({'status': 'error', 'message': 'Username and password required'}), 400
        if len(password) < 8:
            return jsonify({'status': 'error', 'message': 'Password must be at least 8 characters long'}), 400
        password_hash = passlib_bcrypt.hash(password)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Username already exists'}), 409
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Added user {username}'})
    except Exception as e:
        logging.error(f"Error in add_user: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to add user.'}), 500

@app.route('/users/<username>', methods=['DELETE'])
@require_auth
def delete_user(username):
    try:
        if username == 'admin':
            return jsonify({'status': 'error', 'message': 'Cannot delete default admin user'}), 403
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE username = ?', (username,))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Deleted user {username}'})
    except Exception as e:
        logging.error(f"Error in delete_user: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to delete user.'}), 500

@app.route('/users/<username>', methods=['PUT'])
@require_auth
def update_user(username):
    try:
        data = request.get_json()
        new_password = data.get('password')
        if not new_password:
            return jsonify({'status': 'error', 'message': 'New password required'}), 400
        if len(new_password) < 8:
            return jsonify({'status': 'error', 'message': 'Password must be at least 8 characters long'}), 400
        password_hash = passlib_bcrypt.hash(new_password)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET password_hash = ? WHERE username = ?', (password_hash, username))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Updated password for {username}'})
    except Exception as e:
        logging.error(f"Error in update_user: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to update user.'}), 500

@app.route('/users/manage')
@require_auth
def manage_users():
    return render_template('users.html', config=config)

@app.route('/export', methods=['GET'])
@require_auth
def export_attendance():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY timestamp DESC')
            records = cursor.fetchall()
        import pandas as pd
        df = pd.DataFrame(records, columns=['Employee ID', 'Name', 'Date', 'Time In', 'Time Out'])
        export_path = 'static/exports/attendance_export.csv'
        df.to_csv(export_path, index=False)
        return send_from_directory('static/exports', 'attendance_export.csv', as_attachment=True)
    except Exception as e:
        logging.error(f"Error in export_attendance: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to export attendance.'}), 500

@app.route('/biometric_scan', methods=['POST'])
def biometric_scan():
    try:
        data = request.get_json()
        fingerprint = data.get('fingerprint_template')
        if not fingerprint:
            return jsonify({'status': 'error', 'message': 'Fingerprint template required'}), 400
        encrypted_fingerprint = cipher.encrypt(fingerprint.encode()).decode()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, fingerprint_template FROM employees WHERE fingerprint_template = ?', (fingerprint,))
            employee = cursor.fetchone()
            if not employee:
                logging.warning(f"Unknown fingerprint: {fingerprint}")
                return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
            employee_id, name, _ = employee
            current_time = datetime.now()
            timestamp = int(current_time.timestamp())
            current_date = current_time.strftime('%Y-%m-%d')
            current_time_str = current_time.strftime('%H:%M:%S')
            cursor.execute('SELECT time_in, time_out FROM attendance WHERE employee_id = ? AND date = ? ORDER BY timestamp DESC LIMIT 1',
                           (employee_id, current_date))
            last_record = cursor.fetchone()
            max_cycles = config.get('max_cycles_per_day', 2)
            cursor.execute('SELECT COUNT(*) FROM attendance WHERE employee_id = ? AND date = ? AND time_in IS NOT NULL',
                           (employee_id, current_date))
            cycle_count = cursor.fetchone()[0]
            if last_record and cycle_count < max_cycles:
                time_in, time_out = last_record
                if time_in and not time_out:
                    cursor.execute('UPDATE attendance SET time_out = ?, fingerprint = ? WHERE employee_id = ? AND date = ? AND time_in = ?',
                                   (current_time_str, encrypted_fingerprint, employee_id, current_date, time_in))
                    action = 'check-out'
                else:
                    cursor.execute('INSERT INTO attendance (timestamp, employee_id, name, date, time_in, fingerprint) VALUES (?, ?, ?, ?, ?, ?)',
                                   (timestamp, employee_id, name, current_date, current_time_str, encrypted_fingerprint))
                    action = 'check-in'
            else:
                cursor.execute('INSERT INTO attendance (timestamp, employee_id, name, date, time_in, fingerprint) VALUES (?, ?, ?, ?, ?, ?)',
                               (timestamp, employee_id, name, current_date, current_time_str, encrypted_fingerprint))
                action = 'check-in'
            cursor.execute('INSERT INTO audit_log (timestamp, employee_id, action) VALUES (?, ?, ?)',
                           (timestamp, employee_id, action))
            conn.commit()
        socketio.emit('attendance_update', {
            'employee_id': employee_id,
            'name': name,
            'date': current_date,
            'time_in': current_time_str if action == 'check-in' else None,
            'time_out': current_time_str if action == 'check-out' else None,
            'action': action,
            'time': current_time_str
        })
        send_notification(employee_id, name, action, current_time_str)
        return jsonify({'status': 'success', 'message': f'{action.capitalize()} recorded for {name}'})
    except Exception as e:
        logging.error(f"Error in biometric_scan: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to process biometric scan. Please try again or contact support.'}), 500

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)