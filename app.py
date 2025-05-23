import os
import json
import logging
import sqlite3
import requests
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, set_access_cookies, unset_jwt_cookies
from cryptography.fernet import Fernet
import pandas as pd
from passlib.hash import bcrypt
from dotenv import load_dotenv
import paypalrestsdk
import stripe
import base64

# Load environment variables
load_dotenv()
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    with open('.env', 'a') as f:
        f.write(f"\nENCRYPTION_KEY={ENCRYPTION_KEY}")

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"ENCRYPTION_KEY: {ENCRYPTION_KEY}, Length: {len(ENCRYPTION_KEY)}")
cipher = Fernet(ENCRYPTION_KEY.encode())

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_COOKIE_SECURE'] = False
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_COOKIE_SAMESITE'] = 'Lax'

socketio = SocketIO(app)

# Initialize JWTManager
jwt = JWTManager(app)

# Database setup
DB_PATH = 'data/biometric_attendance.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                fingerprint_template TEXT NOT NULL,
                photo_url TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT,
                name TEXT,
                date TEXT,
                time_in TEXT,
                time_out TEXT,
                timestamp TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                organization_id TEXT PRIMARY KEY,
                plan TEXT NOT NULL,
                employee_limit INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                FOREIGN KEY (organization_id) REFERENCES users (username)
            )
        ''')
        # Insert default admin user if not existing
        cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
        if not cursor.fetchone():
            logger.info("Creating default admin user")
            password_hash = bcrypt.hash('admin123')
            cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', ('admin', password_hash))
            cursor.execute('INSERT OR IGNORE INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                           ('admin', 'free', 10, date.today().isoformat()))
            conn.commit()
            logger.info("Default admin user and subscription created")
        else:
            cursor.execute('SELECT * FROM subscriptions WHERE organization_id = ?', ('admin',))
            if not cursor.fetchone():
                logger.info("No subscription found for admin, creating default subscription")
                cursor.execute('INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                               ('admin', 'free', 10, date.today().isoformat()))
                conn.commit()
                logger.info("Default subscription for admin created")

logger.info(f"Connecting to SQLite database at {DB_PATH}")
try:
    init_db()
    logger.info("Database connection successful")
except Exception as e:
    logger.error(f"Database connection failed: {e}")
    raise

# Load configuration
with open('config.json', 'r') as f:
    config = json.load(f)

# Subscription tier definitions
SUBSCRIPTION_TIERS = {
    'free': {'employee_limit': 10, 'features': ['dashboard', 'attendance'], 'price': 0},
    'starter': {'employee_limit': 50, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export'], 'price': 20},
    'pro': {'employee_limit': 500, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations'], 'price': 50},
    'enterprise': {'employee_limit': 10000, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'custom'], 'price': 100}
}

# Initialize payment gateways
# Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')

# PayPal
paypalrestsdk.configure({
    "mode": "sandbox",  # Change to "live" for production
    "client_id": os.getenv('PAYPAL_CLIENT_ID'),
    "client_secret": os.getenv('PAYPAL_CLIENT_SECRET')
})

# M-Pesa
MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')

def get_mpesa_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET)
    response = requests.get(api_url, auth=auth)
    return response.json().get('access_token')

# Helper function to check subscription feature
def verify_subscription_feature(username, feature):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT plan FROM subscriptions WHERE organization_id = ?', (username,))
        subscription = cursor.fetchone()
        if not subscription:
            return False, jsonify({'status': 'error', 'message': 'No subscription found'}), 403
        plan = subscription['plan']
        if feature not in SUBSCRIPTION_TIERS[plan]['features']:
            return False, jsonify({'status': 'error', 'message': f'Feature "{feature}" not available in your plan ({plan}). Please upgrade.'}), 403
        return True, None, None

# Helper function to check employee limit
def verify_employee_limit(username):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT plan, employee_limit FROM subscriptions WHERE organization_id = ?', (username,))
        subscription = cursor.fetchone()
        if not subscription:
            return False, jsonify({'status': 'error', 'message': 'No subscription found'}), 403
        plan, employee_limit = subscription['plan'], subscription['employee_limit']
        cursor.execute('SELECT COUNT(*) FROM employees')
        employee_count = cursor.fetchone()[0]
        if employee_count >= employee_limit:
            return False, jsonify({'status': 'error', 'message': f'Employee limit ({employee_limit}) reached for your plan ({plan}). Please upgrade.'}), 403
        return True, None, None

@app.route('/')
def index():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date = ? ORDER BY timestamp DESC', (date.today().isoformat(),))
        records = cursor.fetchall()
    return render_template('dashboard.html', records=records, config=config, datetime=datetime, stripe_publishable_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        if user and bcrypt.verify(password, user['password_hash']):
            access_token = create_access_token(identity=username, expires_delta=timedelta(hours=24))
            print(f"Generated token: {access_token}")  # Log for debugging
            response = jsonify({'status': 'success', 'message': 'Login successful'})
            set_access_cookies(response, access_token)
            print(f"Cookie set in response: {response.headers.get('Set-Cookie')}")  # Debug cookie
            return response, 200
        return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@app.route('/attendance')
@jwt_required()
def get_attendance():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if start_date and end_date:
            cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date BETWEEN ? AND ? ORDER BY timestamp DESC', (start_date, end_date))
        else:
            cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY timestamp DESC')
        records = cursor.fetchall()
    return jsonify({'status': 'success', 'records': [dict(record) for record in records]})

@app.route('/employees', methods=['GET', 'POST'])
@jwt_required()
def employees():
    print(f"Request cookies for /employees: {request.cookies}")
    username = get_jwt_identity()  
    # Check if the request is for JSON data (API call) or HTML (page load)
    if request.headers.get('Accept') == 'application/json':
        # For API calls, require the token
        @jwt_required()
        def get_employees_json():
            # Check subscription feature for employee_management
            has_access, error_response, status_code = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response, status_code
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT employee_id, name, fingerprint_template, photo_url FROM employees')
                employees = cursor.fetchall()
            return jsonify({'status': 'success', 'employees': [dict(emp) for emp in employees]})
        return get_employees_json()
    elif request.method == 'POST':
        # For POST requests (e.g., adding an employee), require the token
        @jwt_required()
        def post_employee():
            # Check subscription feature and employee limit
            has_access, error_response, status_code = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response, status_code
            limit_ok, limit_error, limit_status = verify_employee_limit(username)
            if not limit_ok:
                return limit_error, limit_status

            data = request.form
            employee_id = data.get('employee_id')
            name = data.get('name')
            fingerprint_template = data.get('fingerprint_template')
            photo = request.files.get('photo')
            photo_url = None
            if photo:
                photo_path = os.path.join('static', 'uploads', f"{employee_id}.jpg")
                os.makedirs(os.path.dirname(photo_path), exist_ok=True)
                photo.save(photo_path)
                photo_url = f"/static/uploads/{employee_id}.jpg"
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT OR REPLACE INTO employees (employee_id, name, fingerprint_template, photo_url) VALUES (?, ?, ?, ?)',
                               (employee_id, name, fingerprint_template, photo_url))
                conn.commit()
            return jsonify({'status': 'success', 'message': 'Employee added successfully'})
        return post_employee()
    else:
        # For direct page loads (GET for HTML), render the template without requiring a token initially
        return render_template('employees.html', config=config, datetime=datetime)

@app.route('/employees/<employee_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def update_delete_employee(employee_id):
    username = get_jwt_identity()
    # Check subscription feature for employee_management
    has_access, error_response, status_code = verify_subscription_feature(username, 'employee_management')
    if not has_access:
        return error_response, status_code

    if request.method == 'PUT':
        data = request.form
        name = data.get('name')
        fingerprint_template = data.get('fingerprint_template')
        photo = request.files.get('photo')
        photo_url = None
        if photo:
            photo_path = os.path.join('static', 'uploads', f"{employee_id}.jpg")
            os.makedirs(os.path.dirname(photo_path), exist_ok=True)
            photo.save(photo_path)
            photo_url = f"/static/uploads/{employee_id}.jpg"
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT photo_url FROM employees WHERE employee_id = ?', (employee_id,))
            existing = cursor.fetchone()
            photo_url = photo_url or (existing['photo_url'] if existing else None)
            cursor.execute('UPDATE employees SET name = ?, fingerprint_template = ?, photo_url = ? WHERE employee_id = ?',
                           (name, fingerprint_template, photo_url, employee_id))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'Employee updated successfully'})
    elif request.method == 'DELETE':
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
            cursor.execute('DELETE FROM attendance WHERE employee_id = ?', (employee_id,))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'Employee deleted successfully'})

@app.route('/employees/bulk_import', methods=['POST'])
@jwt_required()
def bulk_import():
    username = get_jwt_identity()
    # Check subscription feature for bulk_operations
    has_access, error_response, status_code = verify_subscription_feature(username, 'bulk_operations')
    if not has_access:
        return error_response, status_code
    # Check employee limit
    limit_ok, limit_error, limit_status = verify_employee_limit(username)
    if not limit_ok:
        return limit_error, limit_status

    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'status': 'error', 'message': 'File must be a CSV'}), 400
    df = pd.read_csv(file)
    required_columns = ['employee_id', 'name', 'fingerprint_template']
    if not all(col in df.columns for col in required_columns):
        return jsonify({'status': 'error', 'message': 'CSV must contain employee_id, name, and fingerprint_template columns'}), 400
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for _, row in df.iterrows():
            cursor.execute('INSERT OR REPLACE INTO employees (employee_id, name, fingerprint_template) VALUES (?, ?, ?)',
                           (row['employee_id'], row['name'], row['fingerprint_template']))
        conn.commit()
    return jsonify({'status': 'success', 'message': 'Employees imported successfully'})

@app.route('/employees/bulk_delete', methods=[' edadPOST'])
@jwt_required()
def bulk_delete():
    username = get_jwt_identity()
    # Check subscription feature for bulk_operations
    has_access, error_response, status_code = verify_subscription_feature(username, 'bulk_operations')
    if not has_access:
        return error_response, status_code

    data = request.get_json()
    employee_ids = data.get('employee_ids', [])
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for employee_id in employee_ids:
            cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
            cursor.execute('DELETE FROM attendance WHERE employee_id = ?', (employee_id,))
        conn.commit()
    return jsonify({'status': 'success', 'message': 'Employees deleted successfully'})

@app.route('/users', methods=['GET'])
def users():
    # Check if the request is for JSON data (API call) or HTML (page load)
    if request.headers.get('Accept') == 'application/json':
        # For API calls, require the token
        @jwt_required()
        def get_users_json():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT username FROM users')
                users = cursor.fetchall()
            return jsonify({'status': 'success', 'users': [dict(user) for user in users]})
        return get_users_json()
    else:
        # For direct page loads, render the template without requiring a token
        return render_template('users.html', config=config, datetime=datetime)

@app.route('/users/<username>', methods=['DELETE'])
@jwt_required()
def delete_user(username):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.commit()
    return jsonify({'status': 'success', 'message': 'User deleted successfully'})

@app.route('/subscription', methods=['GET', 'POST'])
@jwt_required()
def manage_subscription():
    username = get_jwt_identity()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if request.method == 'GET':
            cursor.execute('SELECT plan, employee_limit, start_date, end_date FROM subscriptions WHERE organization_id = ?', (username,))
            subscription = cursor.fetchone()
            if not subscription:
                logger.info(f"No subscription found for user {username}, creating default 'free' subscription")
                cursor.execute('INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                               (username, 'free', 10, date.today().isoformat()))
                conn.commit()
                cursor.execute('SELECT plan, employee_limit, start_date, end_date FROM subscriptions WHERE organization_id = ?', (username,))
                subscription = cursor.fetchone()
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'status': 'success', 'subscription': dict(subscription)})
            return render_template(
                'subscription.html',
                config=config,
                subscription=dict(subscription),
                stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                username=username,
                datetime=datetime  # Pass datetime to the template context
            )
        elif request.method == 'POST':
            data = request.get_json()
            new_plan = data.get('plan')
            payment_method = data.get('payment_method')
            if new_plan not in SUBSCRIPTION_TIERS:
                return jsonify({'status': 'error', 'message': 'Invalid plan'}), 400
            if payment_method not in ['stripe', 'paypal', 'mpesa']:
                return jsonify({'status': 'error', 'message': 'Invalid payment method'}), 400
            employee_limit = SUBSCRIPTION_TIERS[new_plan]['employee_limit']
            amount = SUBSCRIPTION_TIERS[new_plan]['price']
            if amount == 0:  # Free plan, no payment needed
                cursor.execute('UPDATE subscriptions SET plan = ?, employee_limit = ?, start_date = ? WHERE organization_id = ?',
                               (new_plan, employee_limit, date.today().isoformat(), username))
                conn.commit()
                return jsonify({'status': 'success', 'message': f'Subscription upgraded to {new_plan}'})
            # Payment required
            if payment_method == 'stripe':
                try:
                    session = stripe.checkout.Session.create(
                        payment_method_types=['card'],
                        line_items=[{
                            'price_data': {
                                'currency': 'usd',
                                'product_data': {
                                    'name': f'{new_plan.capitalize()} Plan Subscription',
                                },
                                'unit_amount': int(amount * 100),  # Amount in cents
                            },
                            'quantity': 1,
                        }],
                        mode='payment',
                        success_url='http://localhost:5000/subscription/success?session_id={CHECKOUT_SESSION_ID}&plan=' + new_plan,
                        cancel_url='http://localhost:5000/subscription/cancel',
                        metadata={'username': username}
                    )
                    return jsonify({'status': 'success', 'session_id': session.id})
                except Exception as e:
                    return jsonify({'status': 'error', 'message': str(e)}), 500
            elif payment_method == 'paypal':
                payment = paypalrestsdk.Payment({
                    "intent": "sale",
                    "payer": {"payment_method": "paypal"},
                    "redirect_urls": {
                        "return_url": f"http://localhost:5000/subscription/paypal/success?plan={new_plan}",
                        "cancel_url": "http://localhost:5000/subscription/paypal/cancel"
                    },
                    "transactions": [{
                        "amount": {
                            "total": f"{amount:.2f}",
                            "currency": "USD"
                        },
                        "description": f"Subscription to {new_plan} plan"
                    }]
                })
                if payment.create():
                    approval_url = next(link.href for link in payment.links if link.rel == "approval_url")
                    return jsonify({'status': 'success', 'approval_url': approval_url, 'payment_id': payment.id})
                else:
                    return jsonify({'status': 'error', 'message': payment.error}), 500
            elif payment_method == 'mpesa':
                phone_number = data.get('phone_number')
                if not phone_number:
                    return jsonify({'status': 'error', 'message': 'Phone number required for M-Pesa payment'}), 400
                access_token = get_mpesa_access_token()
                if not access_token:
                    return jsonify({'status': 'error', 'message': 'Failed to get M-Pesa access token'}), 500
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                password = base64.b64encode(f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}".encode()).decode()
                api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "BusinessShortCode": MPESA_SHORTCODE,
                    "Password": password,
                    "Timestamp": timestamp,
                    "TransactionType": "CustomerPayBillOnline",
                    "Amount": amount,
                    "PartyA": phone_number,
                    "PartyB": MPESA_SHORTCODE,
                    "PhoneNumber": phone_number,
                    "CallBackURL": "http://localhost:5000/subscription/mpesa/callback",
                    "AccountReference": f"Sub-{username}",
                    "TransactionDesc": f"Subscription to {new_plan} plan"
                }
                response = requests.post(api_url, json=payload, headers=headers)
                result = response.json()
                if response.status_code == 200 and result.get('ResponseCode') == '0':
                    return jsonify({'status': 'success', 'message': 'M-Pesa payment request sent. Please complete the payment on your phone.'})
                else:
                    return jsonify({'status': 'error', 'message': result.get('errorMessage', 'Failed to initiate M-Pesa payment')}), 500

@app.route('/subscription/success')
@jwt_required()
def subscription_success():
    session_id = request.args.get('session_id')
    plan = request.args.get('plan')
    username = get_jwt_identity()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == 'paid':
            with get_db_connection() as conn:
                cursor = conn.cursor()
                employee_limit = SUBSCRIPTION_TIERS[plan]['employee_limit']
                cursor.execute('UPDATE subscriptions SET plan = ?, employee_limit = ?, start_date = ? WHERE organization_id = ?',
                               (plan, employee_limit, date.today().isoformat(), username))
                conn.commit()
            return jsonify({'status': 'success', 'message': f'Subscription upgraded to {plan}'})
        else:
            return jsonify({'status': 'error', 'message': 'Payment not completed'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/subscription/cancel')
def subscription_cancel():
    return jsonify({'status': 'error', 'message': 'Payment cancelled'})

@app.route('/subscription/paypal/success')
@jwt_required()
def paypal_success():
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    plan = request.args.get('plan')
    username = get_jwt_identity()
    payment = paypalrestsdk.Payment.find(payment_id)
    if payment.execute({"payer_id": payer_id}):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            employee_limit = SUBSCRIPTION_TIERS[plan]['employee_limit']
            cursor.execute('UPDATE subscriptions SET plan = ?, employee_limit = ?, start_date = ? WHERE organization_id = ?',
                           (plan, employee_limit, date.today().isoformat(), username))
            conn.commit()
        return jsonify({'status': 'success', 'message': f'Subscription upgraded to {plan}'})
    else:
        return jsonify({'status': 'error', 'message': payment.error}), 500

@app.route('/subscription/paypal/cancel')
def paypal_cancel():
    return jsonify({'status': 'error', 'message': 'PayPal payment cancelled'})

@app.route('/subscription/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    if data['Body']['stkCallback']['ResultCode'] == 0:
        username = data['Body']['stkCallback']['CallbackMetadata']['Item'][4]['Value']  # AccountReference
        username = username.replace('Sub-', '')
        plan = 'starter'  # Simplified; in practice, store this in a temp table during payment initiation
        with get_db_connection() as conn:
            cursor = conn.cursor()
            employee_limit = SUBSCRIPTION_TIERS[plan]['employee_limit']
            cursor.execute('UPDATE subscriptions SET plan = ?, employee_limit = ?, start_date = ? WHERE organization_id = ?',
                           (plan, employee_limit, date.today().isoformat(), username))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'M-Pesa payment successful'})
    else:
        return jsonify({'status': 'error', 'message': 'M-Pesa payment failed'})

@app.route('/analytics')
@jwt_required()
def analytics():
    username = get_jwt_identity()
    # Check subscription feature for analytics
    has_access, error_response, status_code = verify_subscription_feature(username, 'analytics')
    if not has_access:
        return error_response, status_code

    with get_db_connection() as conn:
        cursor = conn.cursor()
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        cursor.execute('''
            SELECT date, COUNT(DISTINCT employee_id) as active_employees
            FROM attendance
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
        ''', (start_date.isoformat(), end_date.isoformat()))
        trends = cursor.fetchall()
    return jsonify({'status': 'success', 'trends': [dict(trend) for trend in trends]})

@app.route('/logout', methods=['POST'])
def logout():
    response = jsonify({"status": "success", "message": "Logged out"})
    unset_jwt_cookies(response)
    return response, 200

@app.route('/check_auth', methods=['GET'])
@jwt_required(optional=True)
def check_auth():
    if get_jwt_identity():
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "unauthenticated"}), 401

@app.route('/export', methods=['GET'])
@jwt_required()
def export_attendance():
    username = get_jwt_identity()
    # Check subscription feature for csv_export
    has_access, error_response, status_code = verify_subscription_feature(username, 'csv_export')
    if not has_access:
        return error_response, status_code

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY timestamp DESC')
        records = cursor.fetchall()
    df = pd.DataFrame([dict(record) for record in records])
    csv_path = 'attendance_export.csv'
    df.to_csv(csv_path, index=False)
    return send_file(csv_path, as_attachment=True)

@app.route('/biometric_scan', methods=['POST'])
def biometric_scan():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data provided in request body'}), 400
        
        employee_id = data.get('employee_id')
        scan_data = data.get('scan_data')
        
        if not employee_id:
            return jsonify({'status': 'error', 'message': 'Missing employee_id in request'}), 400
        if not scan_data:
            return jsonify({'status': 'error', 'message': 'Missing scan_data in request'}), 400
        
        # Validate employee exists
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id FROM employees WHERE employee_id = ?', (employee_id,))
            employee = cursor.fetchone()
            if not employee:
                return jsonify({'status': 'error', 'message': f'Employee with ID {employee_id} not found'}), 404
            
            # Simulate biometric scan validation (replace with actual logic)
            if len(scan_data) < 10:  # Example validation
                return jsonify({'status': 'error', 'message': 'Invalid scan data: too short'}), 400
            
            # Record attendance
            today = date.today().isoformat()
            current_time = datetime.now().strftime('%H:%M:%S')
            cursor.execute('SELECT name FROM employees WHERE employee_id = ?', (employee_id,))
            employee_name = cursor.fetchone()['name']
            cursor.execute('INSERT INTO attendance (employee_id, name, date, time_in, timestamp) VALUES (?, ?, ?, ?, ?)',
                           (employee_id, employee_name, today, current_time, datetime.now().isoformat()))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Biometric scan recorded successfully'})
    
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'Database integrity error: possible duplicate scan'}), 400
    except sqlite3.Error as e:
        return jsonify({'status': 'error', 'message': f'Database error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Unexpected error: {str(e)}'}), 500

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")

@socketio.on('fingerprint_data')
def handle_fingerprint_data(data):
    try:
        fingerprint_template = data.get('fingerprint_template')
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name FROM employees WHERE fingerprint_template = ?', (fingerprint_template,))
            employee = cursor.fetchone()
            if not employee:
                emit('attendance_update', {'status': 'error', 'message': 'Employee not found'})
                return
            employee_id, name = employee['employee_id'], employee['name']
            today = date.today().isoformat()
            cursor.execute('SELECT * FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, today))
            record = cursor.fetchone()
            current_time = datetime.now().strftime('%H:%M:%S')
            if not record:
                cursor.execute('INSERT INTO attendance (employee_id, name, date, time_in, timestamp) VALUES (?, ?, ?, ?, ?)',
                               (employee_id, name, today, current_time, datetime.now().isoformat()))
                conn.commit()
                emit('attendance_update', {
                    'status': 'success', 'employee_id': employee_id, 'name': name, 'date': today,
                    'time_in': current_time, 'time_out': None, 'action': 'check-in'
                }, broadcast=True)
            else:
                max_cycles = config.get('max_cycles_per_day', 2)
                cursor.execute('SELECT COUNT(*) FROM attendance WHERE employee_id = ? AND date = ?', (employee_id, today))
                cycle_count = cursor.fetchone()[0]
                if cycle_count >= max_cycles:
                    emit('attendance_update', {'status': 'error', 'message': 'Maximum check-in/out cycles reached for today'})
                    return
                if record['time_out']:
                    cursor.execute('INSERT INTO attendance (employee_id, name, date, time_in, timestamp) VALUES (?, ?, ?, ?, ?)',
                                   (employee_id, name, today, current_time, datetime.now().isoformat()))
                    conn.commit()
                    emit('attendance_update', {
                        'status': 'success', 'employee_id': employee_id, 'name': name, 'date': today,
                        'time_in': current_time, 'time_out': None, 'action': 'check-in'
                    }, broadcast=True)
                else:
                    cursor.execute('UPDATE attendance SET time_out = ?, timestamp = ? WHERE id = ?',
                                   (current_time, datetime.now().isoformat(), record['id']))
                    conn.commit()
                    emit('attendance_update', {
                        'status': 'success', 'employee_id': employee_id, 'name': name, 'date': today,
                        'time_in': record['time_in'], 'time_out': current_time, 'action': 'check-out'
                    }, broadcast=True)
    except Exception as e:
        logger.error(f"Error processing fingerprint data: {e}")
        emit('attendance_update', {'status': 'error', 'message': 'Internal server error'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)