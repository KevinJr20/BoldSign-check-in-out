import os
import sqlite3
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO
from cryptography.fernet import Fernet
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Flask App Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'super-secret-key')
socketio = SocketIO(app)

DB_FILE = 'data/biometric_attendance.db'
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY not set in .env")

cipher = Fernet(ENCRYPTION_KEY.encode())

# Initialize database
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

@app.route('/')
def dashboard():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY timestamp DESC')
        records = cursor.fetchall()
    return render_template('dashboard.html', records=records, datetime=datetime)

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

            cursor.execute('SELECT time_in, time_out FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, current_date))
            record = cursor.fetchone()

            if not record:
                # First check-in
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
                # Check-out
                cursor.execute('UPDATE attendance SET time_out = ?, fingerprint = ? WHERE employee_id = ? AND date = ?',
                               (current_time, encrypted_fingerprint, employee_id, current_date))
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
                # Multiple cycles
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
