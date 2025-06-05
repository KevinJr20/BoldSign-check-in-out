import os
import json
import logging
import sqlite3
import requests
import datetime
import pytz
from datetime import date, datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, send_file, g, url_for, redirect, flash, make_response
from flask_socketio import SocketIO, emit
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, set_access_cookies, unset_jwt_cookies
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.csrf import generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask.cli import with_appcontext
from cryptography.fernet import Fernet
import pandas as pd
from passlib.hash import bcrypt
from dotenv import load_dotenv
import paypalrestsdk
import stripe
import base64
from dateutil.parser import parse as parse_date
import re
import uuid
import click

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    with open('.env', 'a') as f:
        f.write(f"\nENCRYPTION_KEY={ENCRYPTION_KEY}")
    logger.info("Generated new encryption key and saved to .env")
else:
    try:
        Fernet(ENCRYPTION_KEY.encode())
        logger.info("Encryption key validated successfully")
    except ValueError as e:
        logger.error(f"Invalid encryption key format: {e}")
        raise ValueError("ENCRYPTION_KEY must be a valid Fernet key")

# Validate environment variables
required_env_vars = ['STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY', 'PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET', 'MPESA_SHORTCODE', 'MPESA_PASSKEY', 'SECRET_KEY']
for var in required_env_vars:
    value = os.getenv(var)
    if not value or not isinstance(value, str) or value.strip() == "":
        raise EnvironmentError(f"Environment variable {var} is required and must be a non-empty string")

# Validate encryption key
try:
    cipher = Fernet(ENCRYPTION_KEY.encode())
except ValueError as e:
    logger.error(f"Invalid encryption key: {e}")
    raise ValueError("ENCRYPTION_KEY must be a valid Fernet key (32 url-safe base64-encoded bytes)")

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24).hex())
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
app.config['JWT_COOKIE_CSRF_PROTECT'] = os.getenv('FLASK_ENV', 'development') != 'development'
app.config['JWT_COOKIE_SECURE'] = os.getenv('FLASK_ENV', 'development') != 'development'
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_COOKIE_SAMESITE'] = 'Lax'
app.config['WTF_CSRF_ENABLED'] = True

socketio = SocketIO(app)
csrf = CSRFProtect(app)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)
limiter.init_app(app)

# Initialize JWTManager
jwt = JWTManager(app)

# Load config.json
with open('config.json', 'r') as config_file:
    config_data = json.load(config_file)
app.config.update(config_data)

nairobi_tz = pytz.timezone('Africa/Nairobi')

# Database setup
DB_PATH = 'data/biometric_attendance.db'

def get_db_connection():
    if 'db' not in g:
        logger.info(f"Connecting to SQLite database at {DB_PATH}")
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()
        logger.info("Database connection closed")

# Room pricing and organization types
ROOM_PRICING = {
    'standard': 50,
    'deluxe': 80,
    'suite': 150
}

ORGANIZATION_TYPES = {
    'hotel': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management'], 'default_plan': 'pro'},
    'school': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations'], 'default_plan': 'pro'},
    'retail': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'bulk_operations', 'analytics'], 'default_plan': 'pro'}
}

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
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                organization_type TEXT NOT NULL
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                room_type TEXT NOT NULL,
                status TEXT DEFAULT 'available' CHECK (status IN ('available', 'occupied', 'maintenance'))
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guest_id TEXT,
                guest_name TEXT NOT NULL,
                room_id TEXT,
                check_in_date TEXT NOT NULL,
                check_out_date TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled')),
                payment_status TEXT DEFAULT 'pending' CHECK (payment_status IN ('pending', 'completed', 'failed')),
                FOREIGN KEY (room_id) REFERENCES rooms (room_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guests (
                guest_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                check_in_date TEXT,
                check_out_date TEXT,
                room_id TEXT,
                status TEXT DEFAULT 'checked_out' CHECK (status IN ('checked_in', 'checked_out')),
                FOREIGN KEY (room_id) REFERENCES rooms (room_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                username TEXT,
                plan TEXT,
                status TEXT,
                created_at TEXT,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')
        cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
        if not cursor.fetchone():
            logger.info("Creating default admin user")
            password_hash = bcrypt.hash('admin123')
            cursor.execute('INSERT OR IGNORE INTO users (username, email, password_hash, organization_type) VALUES (?, ?, ?, ?)', ('admin', 'admin@example.com', password_hash, 'hotel'))
            cursor.execute('INSERT OR IGNORE INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                           ('admin', 'starter', 50, date.today().isoformat()))
            cursor.execute('INSERT OR IGNORE INTO rooms (room_id, room_type) VALUES (?, ?)', ('R001', 'standard'))
            cursor.execute('INSERT OR IGNORE INTO rooms (room_id, room_type) VALUES (?, ?)', ('R002', 'deluxe'))
            conn.commit()
            logger.info("Default admin user, subscription, and sample rooms created")
        else:
            cursor.execute('SELECT * FROM subscriptions WHERE organization_id = ?', ('admin',))
            if not cursor.fetchone():
                logger.info("No subscription found for admin, creating default subscription")
                cursor.execute('INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                               ('admin', 'starter', 50, date.today().isoformat()))
                conn.commit()
                logger.info("Default subscription for admin created")

@app.cli.command("init-db")
@with_appcontext
def init_db_command():
    """Initialize the database."""
    init_db()
    click.echo("Initialized the database.")

# Subscription tier definitions
SUBSCRIPTION_TIERS = {
    'free': {'employee_limit': 10, 'features': ['dashboard', 'attendance', 'employee_management'], 'price': 0},
    'starter': {'employee_limit': 50, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'hotel_booking', 'guest_management'], 'price': 25},
    'pro': {'employee_limit': 500, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management'], 'price': 35},
    'enterprise': {'employee_limit': 10000, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management', 'custom'], 'price': 99}
}

# Initialize payment gateways
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')

paypal_mode = 'live' if os.getenv('FLASK_ENV') == 'production' else 'sandbox'
paypalrestsdk.configure({
    "mode": paypal_mode,
    "client_id": os.getenv('PAYPAL_CLIENT_ID'),
    "client_secret": os.getenv('PAYPAL_CLIENT_SECRET')
})

MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')

def get_mpesa_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET)
    try:
        response = requests.get(api_url, auth=auth, timeout=10)
        response.raise_for_status()
        return response.json().get('access_token')
    except requests.RequestException as e:
        logger.error(f"Error getting M-Pesa access token: {e}")
        return None

def validate_mpesa_signature(data):
    # Placeholder: Implement signature validation using Safaricom's security credentials
    return True  # Replace with actual validation logic

def verify_subscription_feature(username, feature):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT plan, organization_type FROM subscriptions s JOIN users u ON s.organization_id = u.username WHERE organization_id = ?', (username,))
            subscription = cursor.fetchone()
            if not subscription:
                return False, jsonify({'status': 'error', 'message': 'No subscription found'}), 403
            plan, org_type = subscription['plan'], subscription['organization_type']
            available_features = ORGANIZATION_TYPES.get(org_type, {}).get('features', []) + SUBSCRIPTION_TIERS.get(plan, {}).get('features', [])
            if feature not in available_features:
                return False, jsonify({'status': 'error', 'message': f'Feature "{feature}" not available for your plan ({plan}). Please upgrade.'}), 403
            return True, None, None
        except sqlite3.OperationalError as e:
            logger.error(f"Database error in verify_subscription_feature: {e}")
            return False, jsonify({'status': 'error', 'message': 'Database error, please contact support'}), 500

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

# Input sanitization helper
def sanitize_input(value):
    if isinstance(value, str):
        return re.sub(r'[^\w\s-]', '', value.strip())
    return value

# Placeholder for fingerprint matching
def match_fingerprint(scan_data, stored_template):
    try:
        similarity = 0.95 if len(scan_data) >= 10 and scan_data == stored_template else 0.0
        return similarity > 0.9
    except Exception as e:
        logger.error(f"Biometric matching error: {e}")
        return False

# Encrypt/decrypt guest name
def encrypt_guest_name(name):
    return cipher.encrypt(name.encode()).decode()

def decrypt_guest_name(encrypted_name):
    return cipher.decrypt(encrypted_name.encode()).decode()

@app.route('/')
@jwt_required(optional=True)
def index():
    current_user = get_jwt_identity()
    if current_user:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET'])
@jwt_required()
def dashboard():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    current_time = nairobi_tz.localize(datetime.now()).strftime('%H:%M:%S')
    today = nairobi_tz.localize(datetime.now()).date().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date = ? ORDER BY timestamp DESC', (today,))
        records = cursor.fetchall()
        cursor.execute('SELECT organization_type FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        org_type = user['organization_type'] if user else 'hotel'
        role = 'admin' if username == 'admin' else ('employee' if org_type == 'school' else 'guest')
    return render_template('dashboard.html', records=records, config=app.config, current_year=datetime.now(timezone.utc).year, current_time=current_time, hasLoggedIn=True, username=username, userRole=role)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
@jwt_required(optional=True)
def login():
    current_user = get_jwt_identity()
    if current_user:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username'))
        password = request.form.get('password')
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('login.html', config=app.config, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT password_hash, organization_type FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            if user and bcrypt.verify(password, user['password_hash']):
                role = 'admin' if username == 'admin' else ('employee' if user['organization_type'] == 'school' else 'guest')
                access_token = create_access_token(identity=username, expires_delta=timedelta(hours=24))
                response = make_response(redirect(url_for('dashboard')))
                set_access_cookies(response, access_token)
                flash('Login successful!', 'success')
                return response
            else:
                flash('Invalid username or password.', 'danger')
                return render_template('login.html', config=app.config, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())
    return render_template('login.html', config=app.config, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())

@app.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    response = make_response(redirect(url_for('login')))
    unset_jwt_cookies(response)
    flash('You have been logged out.', 'success')
    return response

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
@jwt_required(optional=True)
def register():
    current_user = get_jwt_identity()
    if current_user:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username'))
        email = sanitize_input(request.form.get('email'))
        password = request.form.get('password')
        organization_type = sanitize_input(request.form.get('organization_type'))
        if not all([username, email, password, organization_type]):
            flash('All fields are required.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())
        if organization_type not in ORGANIZATION_TYPES:
            flash('Invalid organization type.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())
        password_hash = bcrypt.hash(password)
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT username FROM users WHERE username = ?', (username,))
                if cursor.fetchone():
                    flash('Username already exists.', 'danger')
                    return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())
                cursor.execute('INSERT INTO users (username, email, password_hash, organization_type) VALUES (?, ?, ?, ?)',
                               (username, email, password_hash, organization_type))
                default_plan = ORGANIZATION_TYPES[organization_type]['default_plan']
                employee_limit = SUBSCRIPTION_TIERS[default_plan]['employee_limit']
                cursor.execute('INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                               (username, default_plan, employee_limit, date.today().isoformat()))
                conn.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.Error as e:
            logger.error(f"Registration error: {str(e)}")
            flash('Registration failed due to a server error.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())
    return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now(timezone.utc).year, hasLoggedIn=False, username='', userRole='', csrf_token=generate_csrf())

@app.route('/subscribe', methods=['GET', 'POST'])
@jwt_required()
def subscribe():
    username = get_jwt_identity()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if request.method == 'GET':
            cursor.execute('SELECT plan, employee_limit, start_date, end_date FROM subscriptions WHERE organization_id = ?', (username,))
            subscription = cursor.fetchone()
            if not subscription:
                cursor.execute('SELECT organization_type FROM users WHERE username = ?', (username,))
                org_type = cursor.fetchone()['organization_type']
                default_plan = ORGANIZATION_TYPES[org_type]['default_plan']
                employee_limit = SUBSCRIPTION_TIERS[default_plan]['employee_limit']
                cursor.execute('INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (?, ?, ?, ?)',
                               (username, default_plan, employee_limit, date.today().isoformat()))
                conn.commit()
                cursor.execute('SELECT plan, employee_limit, start_date, end_date FROM subscriptions WHERE organization_id = ?', (username,))
                subscription = cursor.fetchone()
            return render_template(
                'subscribe.html',
                config=app.config,
                subscription=dict(subscription),
                stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                username=username,
                current_year=datetime.now(timezone.utc).year
            )
        elif request.method == 'POST':
            plan_type = sanitize_input(request.form.get('plan_type'))
            payment_method = sanitize_input(request.form.get('payment_method'))
            if not plan_type or not payment_method:
                flash('Plan type and payment method are required.', 'danger')
                return redirect(url_for('subscribe'))
            if plan_type not in SUBSCRIPTION_TIERS:
                flash('Invalid plan selected.', 'danger')
                return redirect(url_for('subscribe'))
            if payment_method not in ['stripe', 'paypal', 'mpesa']:
                flash('Invalid payment method.', 'danger')
                return redirect(url_for('subscribe'))
            amount = SUBSCRIPTION_TIERS[plan_type]['price']
            employee_limit = SUBSCRIPTION_TIERS[plan_type]['employee_limit']
            if amount == 0:
                cursor.execute('UPDATE subscriptions SET plan = ?, employee_limit = ?, start_date = ? WHERE organization_id = ?',
                               (plan_type, employee_limit, date.today().isoformat(), username))
                conn.commit()
                flash(f'Subscription upgraded to {plan_type}.', 'success')
                return redirect(url_for('dashboard'))
            transaction_id = str(uuid.uuid4())
            cursor.execute('INSERT INTO transactions (transaction_id, username, plan, status, created_at) VALUES (?, ?, ?, ?, ?)',
                           (transaction_id, username, plan_type, 'pending', nairobi_tz.localize(datetime.now()).isoformat()))
            conn.commit()
            base_url = request.host_url if request.host_url else f"http://{os.getenv('APP_HOST', 'localhost')}:5000"
            if payment_method == 'stripe':
                try:
                    session = stripe.checkout.Session.create(
                        payment_method_types=['card'],
                        line_items=[{
                            'price_data': {
                                'currency': 'usd',
                                'product_data': {'name': f'{plan_type.capitalize()} Plan Subscription'},
                                'unit_amount': int(amount * 100),
                            },
                            'quantity': 1,
                        }],
                        mode='payment',
                        success_url=f"{base_url}subscribe/success?session_id={{CHECKOUT_SESSION_ID}}&plan={plan_type}",
                        cancel_url=f"{base_url}subscribe/cancel",
                        metadata={'username': username, 'transaction_id': transaction_id}
                    )
                    return redirect(session.url)
                except Exception as e:
                    logger.error(f"Stripe error: {str(e)}")
                    flash(f'Payment failed: {str(e)}', 'danger')
                    return redirect(url_for('subscribe'))
            elif payment_method == 'paypal':
                payment = paypalrestsdk.Payment({
                    "intent": "sale",
                    "payer": {"payment_method": "paypal"},
                    "redirect_urls": {
                        "return_url": f"{base_url}subscribe/paypal/success?plan={plan_type}&transaction_id={transaction_id}",
                        "cancel_url": f"{base_url}subscribe/paypal/cancel"
                    },
                    "transactions": [{
                        "amount": {"total": f"{amount:.2f}", "currency": "USD"},
                        "description": f"Subscription to {plan_type} plan"
                    }]
                })
                if payment.create():
                    approval_url = next(link.href for link in payment.links if link.rel == "approval_url")
                    return redirect(approval_url)
                else:
                    logger.error(f"PayPal error: {payment.error}")
                    flash(f'Payment failed: {payment.error}', 'danger')
                    return redirect(url_for('subscribe'))
            elif payment_method == 'mpesa':
                mpesa_number = sanitize_input(request.form.get('mpesa_number'))
                if not mpesa_number:
                    flash('M-Pesa phone number is required.', 'danger')
                    return redirect(url_for('subscribe'))
                access_token = get_mpesa_access_token()
                if not access_token:
                    flash('Failed to get M-Pesa access token.', 'danger')
                    return redirect(url_for('subscribe'))
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                password = base64.b64encode(f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}".encode()).decode()
                api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
                headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                payload = {
                    "BusinessShortCode": MPESA_SHORTCODE,
                    "Password": password,
                    "Timestamp": timestamp,
                    "TransactionType": "CustomerPayBillOnline",
                    "Amount": amount,
                    "PartyA": mpesa_number,
                    "PartyB": MPESA_SHORTCODE,
                    "PhoneNumber": mpesa_number,
                    "CallBackURL": f"{base_url}subscribe/mpesa/callback",
                    "AccountReference": f"Sub-{username}-{plan_type}-{transaction_id}",
                    "TransactionDesc": f"Subscription to {plan_type} plan"
                }
                try:
                    response = requests.post(api_url, json=payload, headers=headers, timeout=10)
                    result = response.json()
                    if response.status_code == 200 and result.get('ResponseCode') == '0':
                        flash('M-Pesa payment request sent. Please complete the payment on your phone.', 'info')
                        return redirect(url_for('dashboard'))
                    else:
                        flash(result.get('errorMessage', 'Failed to initiate M-Pesa payment'), 'danger')
                        return redirect(url_for('subscribe'))
                except requests.RequestException as e:
                    logger.error(f"M-Pesa error: {str(e)}")
                    flash(f'Payment failed: {str(e)}', 'danger')
                    return redirect(url_for('subscribe'))

@app.route('/subscribe/success')
@jwt_required()
def subscribe_success():
    session_id = request.args.get('session_id')
    plan = request.args.get('plan')
    username = get_jwt_identity()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == 'paid':
            transaction_id = session.metadata.get('transaction_id')
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT status FROM transactions WHERE transaction_id = ?', (transaction_id,))
                transaction = cursor.fetchone()
                if not transaction or transaction['status'] == 'completed':
                    flash('Invalid or already processed transaction.', 'danger')
                    return redirect(url_for('dashboard'))
                start_date = nairobi_tz.localize(datetime.now()).strftime('%Y-%m-%d')
                end_date = (nairobi_tz.localize(datetime.now()) + timedelta(days=30)).strftime('%Y-%m-%d')
                employee_limit = SUBSCRIPTION_TIERS[plan]['employee_limit']
                cursor.execute('INSERT OR REPLACE INTO subscriptions (organization_id, plan, employee_limit, start_date, end_date) VALUES (?, ?, ?, ?, ?)',
                               (username, plan, employee_limit, start_date, end_date))
                cursor.execute('UPDATE transactions SET status = ? WHERE transaction_id = ?', ('completed', transaction_id))
                conn.commit()
            flash(f'Subscription upgraded to {plan}.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Payment not completed.', 'danger')
            return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"Stripe success error: {str(e)}")
        flash(f'Error processing payment: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/subscribe/cancel')
@jwt_required()
def subscribe_cancel():
    flash('Payment cancelled.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/subscribe/paypal/success')
@jwt_required()
def subscribe_paypal_success():
    payment_id = request.args.get('paymentId')
    payer_id = request.args.get('PayerID')
    plan = request.args.get('plan')
    transaction_id = request.args.get('transaction_id')
    username = get_jwt_identity()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT status FROM transactions WHERE transaction_id = ?', (transaction_id,))
        transaction = cursor.fetchone()
        if not transaction or transaction['status'] == 'completed':
            flash('Invalid or already processed transaction.', 'danger')
            return redirect(url_for('dashboard'))
        payment = paypalrestsdk.Payment.find(payment_id)
        if payment.execute({"payer_id": payer_id}):
            start_date = nairobi_tz.localize(datetime.now()).strftime('%Y-%m-%d')
            end_date = (nairobi_tz.localize(datetime.now()) + timedelta(days=30)).strftime('%Y-%m-%d')
            employee_limit = SUBSCRIPTION_TIERS[plan]['employee_limit']
            cursor.execute('INSERT OR REPLACE INTO subscriptions (organization_id, plan, employee_limit, start_date, end_date) VALUES (?, ?, ?, ?, ?)',
                           (username, plan, employee_limit, start_date, end_date))
            cursor.execute('UPDATE transactions SET status = ? WHERE transaction_id = ?', ('completed', transaction_id))
            conn.commit()
            flash(f'Subscription upgraded to {plan}.', 'success')
            return redirect(url_for('dashboard'))
        else:
            logger.error(f"PayPal success error: {payment.error}")
            flash(f'Payment failed: {payment.error}', 'danger')
            return redirect(url_for('dashboard'))

@app.route('/subscribe/paypal/cancel')
@jwt_required()
def subscribe_paypal_cancel():
    flash('PayPal payment cancelled.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/subscribe/mpesa/callback', methods=['POST'])
def subscribe_mpesa_callback():
    data = request.get_json()
    if not validate_mpesa_signature(data):
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
    try:
        if data['Body']['stkCallback']['ResultCode'] == 0:
            callback_data = data['Body']['stkCallback']['CallbackMetadata']['Item']
            account_reference = next(item['Value'] for item in callback_data if item['Name'] == 'AccountReference')
            _, _, transaction_id, _, _ = account_reference.split('-')
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT username, plan, status FROM transactions WHERE transaction_id = ? AND status = ?', (transaction_id, 'pending'))
                transaction = cursor.fetchone()
                if not transaction:
                    return jsonify({'status': 'error', 'message': 'Invalid or already processed transaction'}), 400
                username, plan = transaction['username'], transaction['plan']
                start_date = nairobi_tz.localize(datetime.now()).strftime('%Y-%m-%d')
                end_date = (nairobi_tz.localize(datetime.now()) + timedelta(days=30)).strftime('%Y-%m-%d')
                employee_limit = SUBSCRIPTION_TIERS[plan]['employee_limit']
                cursor.execute('INSERT OR REPLACE INTO subscriptions (organization_id, plan, employee_limit, start_date, end_date) VALUES (?, ?, ?, ?, ?)',
                               (username, plan, employee_limit, start_date, end_date))
                cursor.execute('UPDATE transactions SET status = ? WHERE transaction_id = ?', ('completed', transaction_id))
                conn.commit()
            return jsonify({'status': 'success', 'message': 'M-Pesa payment successful'})
        else:
            return jsonify({'status': 'error', 'message': 'M-Pesa payment failed'})
    except Exception as e:
        logger.error(f"M-Pesa callback error: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to process callback'}), 500

@app.route('/attendance', methods=['GET'])
@jwt_required()
def get_attendance():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role not in ['admin', 'employee']:
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            if start_date and end_date:
                cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance WHERE date BETWEEN ? AND ? ORDER BY timestamp DESC', (sanitize_input(start_date), sanitize_input(end_date)))
            else:
                cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY timestamp DESC')
            records = cursor.fetchall()
            return jsonify({'status': 'success', 'records': [dict(record) for record in records]})
        except sqlite3.Error as e:
            logger.error(f"Error fetching records records: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to retrieve records records'}), 500

@app.route('/employees', methods=['GET', 'POST'])
@jwt_required()
def employees():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'employee_management')
    if not has_access:
        return error_response, message
    if request.method == 'POST':
        limit_ok, limit_error, message = verify_employee_limit(username)
        if not limit_ok:
            return limit_error, message
        data = request.form
        employee_id = sanitize_input(data.get('employee_id'))
        name = sanitize_input(data.get('name'))
        fingerprint_template = sanitize_input(data.get('fingerprint_template'))
        photo = request.files.get('photo')
        photo_url = None
        if photo:
            photo_path = os.path.join('static', 'uploads', f"{employee_id}.jpg")
            os.makedirs(os.path.dirname(photo_path), exist_ok=True)
            photo.save(photo_path)
            photo_url = f"/static/uploads/{employee_id}.jpg"
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('INSERT OR REPLACE INTO employees (employee_id, name, fingerprint_template, photo_url) VALUES (?, ?, ?, ?)',
                               (employee_id, name, fingerprint_template, photo_url))
                conn.commit()
                return jsonify({'status': 'success', 'message': 'Employee added successfully'})
            except sqlite3.Error as e:
                logger.error(f"Error adding employee: {e}")
                return jsonify({'status': 'error', 'message': 'Failed to add employee'}), 500
    else:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT employee_id, name, fingerprint_template, photo_url FROM sessions')
                records = cursor.fetchall()
                return jsonify({'status': 'success', 'employees': [dict(record) for record in records]})
            except sqlite3.Error as e:
                logger.error(f"Error retrieving employees: {e}")
                return jsonify({'status': 'error', 'message': 'Failed to retrieve employee records'}), 500

@app.route('/employees/<employee_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def update_delete_employee(employee_id):
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'employee_management')
    if not has_access:
        return error_response, message
    employee_id = sanitize_input(employee_id)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            if request.method == 'PUT':
                data = request.form
                name = sanitize_input(data.get('name'))
                fingerprint_template = sanitize_input(data.get('fingerprint_template'))
                photo = request.files.get('photo')
                photo_url = None
                if photo:
                    photo_path = os.path.join('static', 'uploads', f"{employee_id}.jpg")
                    os.makedirs(os.path.dirname(photo_path), exist_ok=True)
                    photo.save(photo_path)
                    photo_url = f"/static/uploads/{employee_id}.jpg"
                cursor.execute('SELECT photo_url FROM employees WHERE employee_id = ?', (employee_id,))
                existing = cursor.fetchone()
                photo_url = photo_url or (existing['photo_url'] if existing else None)
                cursor.execute('UPDATE employees SET name = ?, fingerprint_template = ?, photo_url = ? WHERE employee_id = ?',
                               (name, fingerprint_template, photo_url, employee_id))
                conn.commit()
                return jsonify({'status': 'success', 'message': 'Employee updated successfully'})
            else:  # DELETE
                cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
                cursor.execute('DELETE FROM attendance WHERE employee_id = ?', (employee_id,))
                conn.commit()
                return jsonify({'status': 'success', 'message': 'Employee deleted successfully'})
        except sqlite3.Error as e:
            logger.error(f"Error in update/delete operation: {e}")
            return jsonify({'status': 'error', 'message': 'Operation failed due to database error'}), 500

@app.route('/employees/bulk_import', methods=['POST'])
@jwt_required()
def bulk_import():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'bulk_operations')
    if not has_access:
        return error_response, message
    limit_ok, limit_error, message = verify_employee_limit(username)
    if not limit_ok:
        return limit_error, message
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'status': 'error', 'message': 'File must be a CSV'}), 400
    try:
        df = pd.read_csv(file)
        required_columns = ['employee_id', 'name', 'fingerprint_template']
        if not all(col in df.columns for col in required_columns):
            return jsonify({'status': 'error', 'message': 'CSV must contain employee_id, name, and fingerprint_template columns'}), 400
        with get_db_connection() as conn:
            cursor = conn.cursor()
            for _, row in df.iterrows():
                cursor.execute('INSERT OR REPLACE INTO employees (employee_id, name, fingerprint_template) VALUES (?, ?, ?)',
                               (sanitize_input(row['employee_id']), sanitize_input(row['name']), sanitize_input(row['fingerprint_template'])))
            conn.commit()
        return jsonify({'status': 'success', 'message': 'Employees imported successfully'})
    except Exception as e:
        logger.error(f"Bulk import error: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Import failed: {str(e)}'}), 500

@app.route('/employees/bulk_delete', methods=['POST'])
@jwt_required()
def bulk_delete():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'bulk_operations')
    if not has_access:
        return error_response, message
    data = request.get_json()
    employee_ids = [sanitize_input(eid) for eid in data.get('employee_ids', [])]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            for employee_id in employee_ids:
                cursor.execute('DELETE FROM employees WHERE employee_id = ?', (employee_id,))
                cursor.execute('DELETE FROM attendance WHERE employee_id = ?', (employee_id,))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Employees deleted successfully'})
        except sqlite3.Error as e:
            logger.error(f"Bulk delete error: {e}")
            return jsonify({'status': 'error', 'message': 'Delete operation failed'}), 500

@app.route('/users', methods=['GET'])
@jwt_required()
def users():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    if request.headers.get('Accept') == 'application/json':
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT username FROM users')
                users = cursor.fetchall()
                return jsonify({'status': 'success', 'users': [dict(user) for user in users]})
            except sqlite3.Error as e:
                logger.error(f"Error retrieving users: {e}")
                return jsonify({'status': 'error', 'message': 'Failed to retrieve users'}), 500
    else:
        return render_template('users.html', config=app.config, current_year=datetime.now(timezone.utc).year)

@app.route('/users/<username>', methods=['DELETE'])
@jwt_required()
def delete_user(target_username):
    current_user = get_jwt_identity()
    role = 'admin' if current_user == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    target_username = sanitize_input(target_username)
    if current_user == target_username:
        return jsonify({'status': 'error', 'message': 'Cannot delete your own account'}), 400
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM users WHERE username = ?', (target_username,))
            cursor.execute('DELETE FROM subscriptions WHERE organization_id = ?', (target_username,))
            conn.commit()
            return jsonify({'status': 'success', 'message': 'User deleted successfully'})
        except sqlite3.Error as e:
            logger.error(f"Error deleting user: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to delete user'}), 500

@app.route('/analytics')
@jwt_required()
def analytics():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'analytics')
    if not has_access:
        return error_response, message
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            end_date = nairobi_tz.localize(datetime.now()).date()
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
        except sqlite3.Error as e:
            logger.error(f"Analytics error: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to retrieve analytics'}), 500

@app.route('/export', methods=['GET'])
@jwt_required()
def export_attendance():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'csv_export')
    if not has_access:
        return error_response, message
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY date DESC')
            records = cursor.fetchall()
            df = pd.DataFrame([dict(record) for record in records])
            csv_path = 'attendance_export.csv'
            df.to_csv(csv_path, index=False)
            return send_file(csv_path, as_attachment=True, download_name='attendance_export.csv')
        except sqlite3.Error as e:
            logger.error(f"Export error: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to export attendance'}), 500

@app.route('/scan', methods=['POST'])
@jwt_required()
def scan_fingerprint():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role not in ['admin', 'employee']:
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    data = request.get_json()
    scan_data = data.get('fingerprint_data')
    if not scan_data:
        return jsonify({'status': 'error', 'message': 'No fingerprint data provided'}), 400
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT employee_id, name, fingerprint_template FROM employees')
            employees = cursor.fetchall()
            for emp in employees:
                if match_fingerprint(scan_data, emp['fingerprint_template']):
                    today = nairobi_tz.localize(datetime.now()).date().isoformat()
                    current_time = nairobi_tz.localize(datetime.now()).strftime('%H:%M:%S')
                    cursor.execute('SELECT time_in, time_out FROM attendance WHERE employee_id = ? AND date = ?', (emp['employee_id'], today))
                    record = cursor.fetchone()
                    if record and not record['time_out']:
                        cursor.execute('UPDATE attendance SET time_out = ?, timestamp = ? WHERE employee_id = ? AND date = ?',
                                       (current_time, nairobi_tz.localize(datetime.now()).isoformat(), emp['employee_id'], today))
                        action = 'check-out'
                    else:
                        cursor.execute('INSERT INTO attendance (employee_id, name, date, time_in, timestamp) VALUES (?, ?, ?, ?, ?)',
                                       (emp['employee_id'], emp['name'], today, current_time, nairobi_tz.localize(datetime.now()).isoformat()))
                        action = 'check-in'
                    conn.commit()
                    socketio.emit('employee_status', {
                        'employee_id': emp['employee_id'],
                        'name': emp['name'],
                        'action': action,
                        'time': current_time,
                        'date': today
                    })
                    return jsonify({'status': 'success', 'message': f'{emp["name"]} {action} successful', 'action': action})
            return jsonify({'status': 'error', 'message': 'Fingerprint not recognized'}), 404
    except sqlite3.Error as e:
        logger.error(f"Scan error: {e}")
        return jsonify({'status': 'error', 'message': 'Server error'}), 500

@app.route('/room_status', methods=['GET'])
@jwt_required()
def room_status():
    username = get_jwt_identity()
    has_access, error_response, message = verify_subscription_feature(username, 'hotel_booking')
    if not has_access:
        return error_response, message
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT room_id, room_type, status FROM rooms')
            rooms = cursor.fetchall()
            return jsonify({'status': 'success', 'rooms': [dict(room) for room in rooms]})
        except sqlite3.Error as e:
            logger.error(f"Room status error: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to retrieve room status'}), 500

@app.route('/book_room', methods=['POST'])
@jwt_required()
def book_room():
    username = get_jwt_identity()
    has_access, error_response, message = verify_subscription_feature(username, 'hotel_booking')
    if not has_access:
        return error_response, message
    data = request.get_json()
    guest_name = sanitize_input(data.get('guest_name'))
    room_id = sanitize_input(data.get('room_id'))
    check_in_date = sanitize_input(data.get('check_in_date'))
    check_out_date = sanitize_input(data.get('check_out_date'))
    payment_method = sanitize_input(data.get('payment_method'))
    if not all([guest_name, room_id, check_in_date, check_out_date, payment_method]):
        return jsonify({'status': 'error', 'message': 'All fields are required'}), 400
    try:
        check_in = parse_date(check_in_date).date()
        check_out = parse_date(check_out_date).date()
        if check_in >= check_out or check_in < date.today():
            return jsonify({'status': 'error', 'message': 'Invalid check-in or check-out date'}), 400
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid date format'}), 400
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT status, room_type FROM rooms WHERE room_id = ?', (room_id,))
            room = cursor.fetchone()
            if not room:
                return jsonify({'status': 'error', 'message': 'Room not found'}), 404
            if room['status'] != 'available':
                return jsonify({'status': 'error', 'message': 'Room is not available'}), 400
            cursor.execute('''
                SELECT booking_id FROM bookings
                WHERE room_id = ? AND status NOT IN ('cancelled', 'checked_out')
                AND (check_in_date <= ? AND check_out_date >= ?)
            ''', (room_id, check_out_date, check_in_date))
            if cursor.fetchone():
                return jsonify({'status': 'error', 'message': 'Room is booked for the selected dates'}), 400
            guest_id = str(uuid.uuid4())
            encrypted_name = encrypt_guest_name(guest_name)
            nights = (check_out - check_in).days
            amount = ROOM_PRICING[room['room_type']] * nights
            if payment_method == 'mpesa':
                phone_number = sanitize_input(data.get('phone_number'))
                if not phone_number:
                    return jsonify({'status': 'error', 'message': 'Phone number required for M-Pesa payment'}), 400
                access_token = get_mpesa_access_token()
                if not access_token:
                    return jsonify({'status': 'error', 'message': 'Failed to get M-Pesa access token'}), 500
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                password = base64.b64encode(f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}".encode()).decode()
                base_url = request.host_url if request.host_url else f"http://{os.getenv('APP_HOST', 'localhost')}:5000"
                api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
                headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                payload = {
                    "BusinessShortCode": MPESA_SHORTCODE,
                    "Password": password,
                    "Timestamp": timestamp,
                    "TransactionType": "CustomerPayBillOnline",
                    "Amount": amount,
                    "PartyA": phone_number,
                    "PartyB": MPESA_SHORTCODE,
                    "PhoneNumber": phone_number,
                    "CallBackURL": f"{base_url}mpesa/callback",
                    "AccountReference": f"Booking-{guest_id}",
                    "TransactionDesc": f"Room booking for {guest_name}"
                }
                response = requests.post(api_url, json=payload, headers=headers, timeout=10)
                result = response.json()
                if response.status_code != 200 or result.get('ResponseCode') != '0':
                    return jsonify({'status': 'error', 'message': result.get('errorMessage', 'Failed to initiate M-Pesa payment')}), 500
            cursor.execute('INSERT INTO bookings (guest_id, guest_name, room_id, check_in_date, check_out_date, payment_status) VALUES (?, ?, ?, ?, ?, ?)',
                           (guest_id, encrypted_name, room_id, check_in_date, check_out_date, 'pending' if payment_method == 'mpesa' else 'completed'))
            cursor.execute('UPDATE rooms SET status = ? WHERE room_id = ?', ('occupied', room_id))
            cursor.execute('INSERT OR REPLACE INTO guests (guest_id, name, check_in_date, check_out_date, room_id, status) VALUES (?, ?, ?, ?, ?, ?)',
                           (guest_id, encrypted_name, check_in_date, check_out_date, room_id, 'checked_in'))
            conn.commit()
            socketio.emit('room_status_update', {'room_id': room_id, 'status': 'occupied'})
            return jsonify({'status': 'success', 'message': 'Room booked successfully'})
        except sqlite3.Error as e:
            logger.error(f"Book room error: {e}")
            return jsonify({'status': 'error', 'message': 'Failed to book room'}), 500

@app.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    if not validate_mpesa_signature(data):
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403
    try:
        if data['Body']['stkCallback']['ResultCode'] == 0:
            callback_data = data['Body']['stkCallback']['CallbackMetadata']['Item']
            account_reference = next(item['Value'] for item in callback_data if item['Name'] == 'AccountReference')
            guest_id = account_reference.replace('Booking-', '')
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE bookings SET payment_status = ? WHERE guest_id = ?', ('completed', guest_id))
                conn.commit()
            return jsonify({'status': 'success', 'message': 'M-Pesa payment successful'})
        return jsonify({'status': 'error', 'message': 'M-Pesa payment failed'})
    except Exception as e:
        logger.error(f"M-Pesa callback error: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to process callback'}), 500

@app.route('/check_in_out', methods=['POST'])
@jwt_required()
def check_in_out():
    username = get_jwt_identity()
    has_access, error_response, message = verify_subscription_feature(username, 'guest_management')
    if not has_access:
        return error_response, message
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    action = sanitize_input(data.get('action'))
    if action not in ['check_in', 'check_out']:
        return jsonify({'status': 'error', 'message': 'Invalid action'}), 400
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT name, room_id, status FROM guests WHERE guest_id = ?', (guest_id,))
            guest = cursor.fetchone()
            if not guest:
                return jsonify({'status': 'error', 'message': 'Guest not found'}), 404
            if action == 'check_in' and guest['status'] == 'checked_in':
                return jsonify({'status': 'error', 'message': 'Guest is already checked in'}), 400
            if action == 'check_out' and guest['status'] == 'checked_out':
                return jsonify({'status': 'error', 'message': 'Guest is already checked out'}), 400
            current_date = nairobi_tz.localize(datetime.now()).date().isoformat()
            if action == 'check_in':
                cursor.execute('UPDATE guests SET status = ?, check_in_date = ? WHERE guest_id = ?', ('checked_in', current_date, guest_id))
                cursor.execute('UPDATE bookings SET status = ? WHERE guest_id = ?', ('checked_in', guest_id))
            else:
                cursor.execute('UPDATE guests SET status = ?, check_out_date = ? WHERE guest_id = ?', ('checked_out', current_date, guest_id))
                cursor.execute('UPDATE bookings SET status = ? WHERE guest_id = ?', ('checked_out', guest_id))
                cursor.execute('UPDATE rooms SET status = ? WHERE room_id = ?', ('available', guest['room_id']))
                socketio.emit('room_status_update', {'room_id': guest['room_id'], 'status': 'available'})
            conn.commit()
            return jsonify({'status': 'success', 'message': f'Guest {action} successful'})
        except sqlite3.Error as e:
            logger.error(f"Check in/out error: {e}")
            return jsonify({'status': 'error', 'message': 'Operation failed'}), 500

@app.route('/sync_channels', methods=['POST'])
@jwt_required()
def sync_channels():
    username = get_jwt_identity()
    role = 'admin' if username == 'admin' else 'employee'
    if role != 'admin':
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403
    has_access, error_response, message = verify_subscription_feature(username, 'guest_management')
    if not has_access:
        return error_response, message
    try:
        third_party_api_url = os.getenv('THIRD_PARTY_API_URL', 'https://api.example.com/sync')
        third_party_api_key = os.getenv('THIRD_PARTY_API_KEY', 'dummy-api-key')
        headers = {'Authorization': f'Bearer {third_party_api_key}', 'Content-Type': 'application/json'}
        payload = {
            'organization_id': username,
            'sync_date': nairobi_tz.localize(datetime.now()).isoformat(),
            'status': 'sync_initiated'
        }
        response = requests.post(third_party_api_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return jsonify({'status': 'success', 'message': 'Channels synced with OTAs and PMS successfully'})
    except requests.RequestException as e:
        logger.error(f"Sync channels error: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Failed to sync: {str(e)}'}), 500

@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')
    emit('connection_status', {'status': 'connected'})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=os.getenv('FLASK_ENV') != 'production')