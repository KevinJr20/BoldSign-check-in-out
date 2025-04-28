import os
import sqlite3
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO
from cryptography.fernet import Fernet
import pandas as pd
from dotenv import load_dotenv
import json
from jose import jwt, JWTError
from passlib.context import CryptContext
from functools import wraps

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'super-secret-key')
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-super-secret-key')
socketio = SocketIO(app)

DB_FILE = 'data/biometric_attendance.db'
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
CONFIG_FILE = 'config.json'

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY not set in .env")

cipher = Fernet(ENCRYPTION_KEY.encode())
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def load_config():
    default_config = {
        "company_name": "Your Company",
        "logo_url": "/static/default_logo.png",
        "primary_color": "#007bff",
        "secondary_color": "#6c757d",
        "max_cycles_per_day": 0,
        "timezone": "UTC"
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                default_config.update(config)
    except Exception as e:
        logging.error(f"Error loading config: {str(e)}")
    return default_config

CONFIG = load_config()

def init_db():
    os.makedirs('data', exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                fingerprint_template TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                timestamp TEXT,
                employee_id TEXT,
                name TEXT,
                date TEXT,
                time_in TEXT,
                time_out TEXT,
                fingerprint TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                timestamp TEXT,
                employee_id TEXT,
                action TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        ''')
        # Add default admin user (password: admin123)
        password_hash = pwd_context.hash("admin123")
        cursor.execute('INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)',
                       ('admin', password_hash))
        conn.commit()

def verify_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        return payload['sub']
    except JWTError:
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

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
        if not user or not pwd_context.verify(password, user[0]):
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401
        token = jwt.encode({
            'sub': username,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, JWT_SECRET_KEY, algorithm='HS256')
        return jsonify({'status': 'success', 'token': token})
    except Exception as e:
        logging.error(f"Error in login: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/')
def dashboard():
    current_date = datetime.now().strftime('%Y-%m-%d')
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date = ? ORDER BY timestamp DESC', (current_date,))
        records = cursor.fetchall()
    return render_template('dashboard.html', records=records, datetime=datetime, config=CONFIG)

@app.route('/attendance', methods=['GET'])
def get_attendance():
    try:
        current_date = datetime.now().strftime('%Y-%m-%d')
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date = ? ORDER BY timestamp DESC', (current_date,))
            records = [{'employee_id': row[0], 'name': row[1], 'date': row[2], 'time_in': row[3], 'time_out': row[4]} for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'records': records})
    except Exception as e:
        logging.error(f"Error in get_attendance: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/biometric_scan', methods=['POST'])
def biometric_scan():
    try:
        data = request.get_json()
        fingerprint_template = data.get('fingerprint_template')
        if not fingerprint_template:
            return jsonify({'status': 'error', 'message': 'No fingerprint template provided'}), 400
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name FROM employees WHERE fingerprint_template = ?', (fingerprint_template,))
            employee = cursor.fetchone()
            if not employee:
                return jsonify({'status': 'error', 'message': 'Fingerprint not recognized'}), 404
            employee_id, name = employee
            current_date = datetime.now().strftime('%Y-%m-%d')
            current_time = datetime.now().strftime('%I:%M %p')
            encrypted_fingerprint = cipher.encrypt(fingerprint_template.encode()).decode()
            if CONFIG['max_cycles_per_day'] > 0:
                cursor.execute('SELECT COUNT(*) FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, current_date))
                cycle_count = cursor.fetchone()[0]
                if cycle_count >= CONFIG['max_cycles_per_day'] * 2:
                    return jsonify({'status': 'error', 'message': 'Max daily cycles reached'}), 403
            cursor.execute('SELECT time_in, time_out FROM attendance WHERE employee_id = ? AND date = ? ORDER BY timestamp DESC LIMIT 1', (employee_id, current_date))
            record = cursor.fetchone()
            if not record:
                cursor.execute('''
                    INSERT INTO attendance (timestamp, employee_id, name, date, time_in, fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (datetime.now().isoformat(), employee_id, name, current_date, current_time, encrypted_fingerprint))
                cursor.execute('INSERT INTO audit_log (timestamp, employee_id, action) VALUES (?, ?, ?)',
                               (datetime.now().isoformat(), employee_id, 'Fingerprint Verified (Check-In)'))
                socketio.emit('attendance_update', {
                    'employee_id': employee_id,
                    'name': name,
                    'date': current_date,
                    'time_in': current_time,
                    'time_out': ''
                })
                return jsonify({'status': 'success', 'action': 'check-in', 'employee_id': employee_id, 'name': name, 'time': current_time})
            elif record[0] and not record[1]:
                cursor.execute('UPDATE attendance SET time_out = ?, fingerprint = ? WHERE employee_id = ? AND date = ? AND time_in = ?',
                               (current_time, encrypted_fingerprint, employee_id, current_date, record[0]))
                cursor.execute('INSERT INTO audit_log (timestamp, employee_id, action) VALUES (?, ?, ?)',
                               (datetime.now().isoformat(), employee_id, 'Fingerprint Verified (Check-Out)'))
                socketio.emit('attendance_update', {
                    'employee_id': employee_id,
                    'name': name,
                    'date': current_date,
                    'time_in': record[0],
                    'time_out': current_time
                })
                return jsonify({'status': 'success', 'action': 'check-out', 'employee_id': employee_id, 'name': name, 'time': current_time})
            else:
                cursor.execute('''
                    INSERT INTO attendance (timestamp, employee_id, name, date, time_in, fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (datetime.now().isoformat(), employee_id, name, current_date, current_time, encrypted_fingerprint))
                cursor.execute('INSERT INTO audit_log (timestamp, employee_id, action) VALUES (?, ?, ?)',
                               (datetime.now().isoformat(), employee_id, 'Fingerprint Verified (Check-In)'))
                socketio.emit('attendance_update', {
                    'employee_id': employee_id,
                    'name': name,
                    'date': current_date,
                    'time_in': current_time,
                    'time_out': ''
                })
                return jsonify({'status': 'success', 'action': 'check-in', 'employee_id': employee_id, 'name': name, 'time': current_time})
    except Exception as e:
        logging.error(f"Error in biometric_scan: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/employees', methods=['GET'])
@require_auth
def list_employees():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, fingerprint_template FROM employees ORDER BY employee_id')
            employees = [{'employee_id': row[0], 'name': row[1], 'fingerprint_template': row[2]} for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'employees': employees})
    except Exception as e:
        logging.error(f"Error in list_employees: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/employees', methods=['POST'])
@require_auth
def add_employee():
    try:
        data = request.get_json()
        employee_id = data.get('employee_id')
        name = data.get('name')
        fingerprint_template = data.get('fingerprint_template')
        if not all([employee_id, name, fingerprint_template]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO employees (employee_id, name, fingerprint_template) VALUES (?, ?, ?)',
                           (employee_id, name, fingerprint_template))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Employee ID already exists'}), 409
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Added {name} ({employee_id})'})
    except Exception as e:
        logging.error(f"Error in add_employee: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/employees/<employee_id>', methods=['PUT'])
@require_auth
def update_employee(employee_id):
    try:
        data = request.get_json()
        name = data.get('name')
        fingerprint_template = data.get('fingerprint_template')
        if not all([name, fingerprint_template]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE employees SET name = ?, fingerprint_template = ? WHERE employee_id = ?',
                           (name, fingerprint_template, employee_id))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Updated {name} ({employee_id})'})
    except Exception as e:
        logging.error(f"Error in update_employee: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/employees/<employee_id>', methods=['DELETE'])
@require_auth
def delete_employee(employee_id):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Employee not found'}), 404
            cursor.execute('DELETE FROM attendance WHERE employee_id = ?', (employee_id,))
            cursor.execute('DELETE FROM audit_log WHERE employee_id = ?', (employee_id,))
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Deleted employee {employee_id}'})
    except Exception as e:
        logging.error(f"Error in delete_employee: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/employees/bulk_delete', methods=['POST'])
@require_auth
def bulk_delete_employees():
    try:
        data = request.get_json()
        employee_ids = data.get('employee_ids', [])
        if not employee_ids:
            return jsonify({'status': 'error', 'message': 'No employee IDs provided'}), 400
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            deleted = 0
            for employee_id in employee_ids:
                cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
                deleted += cursor.rowcount
                cursor.execute('DELETE FROM attendance WHERE employee_id = ?', (employee_id,))
                cursor.execute('DELETE FROM audit_log WHERE employee_id = ?', (employee_id,))
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Deleted {deleted} employees'})
    except Exception as e:
        logging.error(f"Error in bulk_delete_employees: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/users', methods=['GET'])
@require_auth
def list_users():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT username FROM users ORDER BY username')
            users = [{'username': row[0]} for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'users': users})
    except Exception as e:
        logging.error(f"Error in list_users: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/users', methods=['POST'])
@require_auth
def add_user():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not all([username, password]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        if len(password) < 8:
            return jsonify({'status': 'error', 'message': 'Password must be at least 8 characters'}), 400
        password_hash = pwd_context.hash(password)
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)',
                           (username, password_hash))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'Username already exists'}), 409
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Added user {username}'})
    except Exception as e:
        logging.error(f"Error in add_user: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/users/<username>', methods=['PUT'])
@require_auth
def update_user(username):
    try:
        data = request.get_json()
        password = data.get('password')
        if not password:
            return jsonify({'status': 'error', 'message': 'Password is required'}), 400
        if len(password) < 8:
            return jsonify({'status': 'error', 'message': 'Password must be at least 8 characters'}), 400
        password_hash = pwd_context.hash(password)
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET password_hash = ? WHERE username = ?',
                           (password_hash, username))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Updated user {username}'})
    except Exception as e:
        logging.error(f"Error in update_user: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/users/<username>', methods=['DELETE'])
@require_auth
def delete_user(username):
    try:
        if username == 'admin':
            return jsonify({'status': 'error', 'message': 'Cannot delete default admin user'}), 403
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE username = ?', (username,))
            if cursor.rowcount == 0:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Deleted user {username}'})
    except Exception as e:
        logging.error(f"Error in delete_user: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/users/manage')
@require_auth
def manage_users():
    return render_template('users.html', datetime=datetime, config=CONFIG)

@app.route('/export', methods=['GET'])
def export_attendance():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            df = pd.read_sql_query('SELECT * FROM attendance', conn)
        filename = f"attendance_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
        csv_path = os.path.join('static', filename)
        df.to_csv(csv_path, index=False)
        return jsonify({'status': 'success', 'file': f'/static/{filename}'})
    except Exception as e:
        logging.error(f"Error in export_attendance: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_file(os.path.join('static', filename))

@socketio.on('connect')
def handle_connect():
    logging.info('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    logging.info('Client disconnected')

if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)