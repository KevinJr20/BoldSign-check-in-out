import os
import sqlite3
import datetime
import json
# import requests
from cryptography.fernet import Fernet
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app)
DB_FILE = 'data/biometric_attendance.db'
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', Fernet.generate_key())
cipher = Fernet(ENCRYPTION_KEY)

# Initialize database
def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS attendance
                   (timestamp TEXT, employee_id TEXT, name TEXT, date TEXT, time_in TEXT, time_out TEXT, fingerprint TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS audit_log
                   (timestamp TEXT, employee_id TEXT, action TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS employees
                   (employee_id TEXT PRIMARY KEY, name TEXT, fingerprint_template TEXT)''')
    conn.commit()
    conn.close()

# Encrypt biometric data
def encrypt_data(data):
    return cipher.encrypt(data.encode()).decode()

# Decrypt biometric data
def decrypt_data(data):
    return cipher.decrypt(data.encode()).decode()

# Simulate fingerprint matching (replace with ZKTeco SDK)
def match_fingerprint(scanned_template):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT employee_id, name, fingerprint_template FROM employees')
    for employee_id, name, stored_template in cursor.fetchall():
        # In production, use ZKTeco SDK to compare templates
        if scanned_template == decrypt_data(stored_template):  # Placeholder
            conn.close()
            return employee_id, name
    conn.close()
    return None, None

# Biometric scan endpoint (called by scanner)
@app.route('/biometric_scan', methods=['POST'])
def biometric_scan():
    try:
        data = request.get_json()
        scanned_template = data.get('fingerprint_template')
        timestamp = datetime.datetime.now()
        date = timestamp.strftime('%Y-%m-%d')
        time = timestamp.strftime('%I:%M %p')

        # Match fingerprint
        employee_id, name = match_fingerprint(scanned_template)
        if not employee_id:
            return jsonify({'status': 'error', 'message': 'Fingerprint not recognized'}), 400

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, date))
        record = cursor.fetchone()

        if not record:
            # Check-in
            cursor.execute('INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (timestamp.isoformat(), employee_id, name, date, time, '', encrypt_data(scanned_template)))
            cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                           (timestamp.isoformat(), employee_id, 'Fingerprint Verified (Check-In)'))
            action = 'check-in'
        else:
            # Check-out if not already checked out
            if record[5]:  # time_out is set
                return jsonify({'status': 'error', 'message': 'Already checked out today'}), 400
            cursor.execute('UPDATE attendance SET time_out = ?, fingerprint = ? WHERE employee_id = ? AND date = ?',
                           (time, encrypt_data(scanned_template), employee_id, date))
            cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                           (timestamp.isoformat(), employee_id, 'Fingerprint Verified (Check-Out)'))
            action = 'check-out'

        conn.commit()
        conn.close()

        # Push update to dashboard
        socketio.emit('update_dashboard', {
            'timestamp': timestamp.isoformat(),
            'employee_id': employee_id,
            'name': name,
            'date': date,
            'time_in': time if action == 'check-in' else record[4],
            'time_out': time if action == 'check-out' else ''
        })

        return jsonify({'status': 'success', 'action': action, 'employee_id': employee_id, 'name': name, 'time': time}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Simulate biometric check-in (for demo)
@app.route('/checkin', methods=['POST'])
def checkin():
    employee_id = request.form.get('employee_id', 'SFK000')
    name = request.form.get('name', 'Kevin Omondi')
    time_in = request.form.get('time_in', datetime.datetime.now().strftime('%I:%M %p'))
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    fingerprint = encrypt_data(f'fingerprint_{employee_id}')  # Placeholder

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, date))
    if cursor.fetchone():
        return jsonify({'status': 'error', 'message': 'Already checked in today'}), 400
    cursor.execute('INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (datetime.datetime.now().isoformat(), employee_id, name, date, time_in, '', fingerprint))
    cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                   (datetime.datetime.now().isoformat(), employee_id, 'Fingerprint Verified (Check-In)'))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'}), 200

# Simulate biometric check-out (for demo)
@app.route('/checkout', methods=['POST'])
def checkout():
    employee_id = request.form.get('employee_id', 'SFK000')
    time_out = request.form.get('time_out', datetime.datetime.now().strftime('%I:%M %p'))
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    fingerprint = encrypt_data(f'fingerprint_{employee_id}')  # Placeholder

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, date))
    record = cursor.fetchone()
    if not record:
        return jsonify({'status': 'error', 'message': 'No check-in record found for today'}), 400
    if record[5]:  # time_out is not empty
        return jsonify({'status': 'error', 'message': 'Already checked out today'}), 400
    cursor.execute('UPDATE attendance SET time_out = ?, fingerprint = ? WHERE employee_id = ? AND date = ?',
                   (time_out, fingerprint, employee_id, date))
    cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                   (datetime.datetime.now().isoformat(), employee_id, 'Fingerprint Verified (Check-Out)'))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'}), 200

# Mobile check-in with facial recognition (placeholder API)
@app.route('/mobile_checkin', methods=['POST'])
def mobile_checkin():
    employee_id = request.form.get('employee_id', 'SFK000')
    name = request.form.get('name', 'Kevin Omondi')
    face_image = request.files.get('face_image')
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    time_in = datetime.datetime.now().strftime('%I:%M %p')

    # Placeholder: Call facial recognition API
    # response = requests.post('https://api.face_recognition.com/verify', files={'image': face_image})
    # if response.json().get('verified'):
    if True:  # Simulate success for demo
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, date))
        if cursor.fetchone():
            return jsonify({'status': 'error', 'message': 'Already checked in today'}), 400
        cursor.execute('INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (datetime.datetime.now().isoformat(), employee_id, name, date, time_in, '', ''))
        cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                       (datetime.datetime.now().isoformat(), employee_id, 'Face Verified (Check-In)'))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'failed'}), 400

# Mobile check-out with facial recognition (placeholder API)
@app.route('/mobile_checkout', methods=['POST'])
def mobile_checkout():
    employee_id = request.form.get('employee_id', 'SFK000')
    face_image = request.files.get('face_image')
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    time_out = datetime.datetime.now().strftime('%I:%M %p')

    # Placeholder: Call facial recognition API
    # response = requests.post('https://api.face_recognition.com/verify', files={'image': face_image})
    # if response.json().get('verified'):
    if True:  # Simulate success for demo
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, date))
        record = cursor.fetchone()
        if not record:
            return jsonify({'status': 'error', 'message': 'No check-in record found for today'}), 400
        if record[5]:  # time_out is not empty
            return jsonify({'status': 'error', 'message': 'Already checked out today'}), 400
        cursor.execute('UPDATE attendance SET time_out = ? WHERE employee_id = ? AND date = ?',
                       (time_out, employee_id, date))
        cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                       (datetime.datetime.now().isoformat(), employee_id, 'Face Verified (Check-Out)'))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'failed'}), 400

# HR dashboard
@app.route('/')
def dashboard():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT timestamp, employee_id, name, date, time_in, time_out FROM attendance ORDER BY date DESC')
    logs = cursor.fetchall()
    conn.close()
    return render_template('dashboard.html', logs=logs)

if __name__ == '__main__':
    init_db()
    # Insert test employee
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO employees VALUES (?, ?, ?)',
                   ('SFK000', 'Kevin Omondi', encrypt_data('fingerprint_SFK000')))
    cursor.execute('INSERT INTO attendance VALUES (?, ?, ?, ?, ?, ?, ?)',
                   ('2025-04-22T08:00:00', 'SFK000', 'Kevin Omondi', '2025-04-22', '08:00 AM', '', encrypt_data('fingerprint_SFK000')))
    cursor.execute('INSERT INTO audit_log VALUES (?, ?, ?)',
                   ('2025-04-22T08:00:00', 'SFK000', 'Fingerprint Verified (Check-In)'))
    conn.commit()
    conn.close()
    socketio.run(app, host='0.0.0.0', port=5000)
