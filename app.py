import os
import json
import uuid
import hashlib
import structlog
import psycopg
import requests
import datetime
import pytz
import base64
import re
import pandas as pd
from flask import Flask, render_template, request, jsonify, url_for, redirect, flash, make_response, g, send_file
from flask_socketio import SocketIO, emit
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, set_access_cookies, unset_jwt_cookies
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_assets import Environment, Bundle
from cryptography.fernet import Fernet
from passlib.hash import bcrypt
from dotenv import load_dotenv
from datetime import date, timedelta, datetime
import paypalrestsdk
import stripe
from dateutil.parser import parse as parse_date
from werkzeug.utils import secure_filename
import magic
from jinja2.exceptions import TemplateNotFound
import email_validator
from tenacity import retry, stop_after_attempt, wait_exponential
from redis import Redis
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
import functools

# Initialize structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

# Load environment variables
load_dotenv()
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '').strip()
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    with open('.env', 'a') as f:
        f.write(f"\nENCRYPTION_KEY={ENCRYPTION_KEY}")
    logger.info("Generated new encryption key")
else:
    try:
        # if not re.match(r'^[A-Za-z0-9+/=]+$', ENCRYPTION_KEY):
            # raise ValueError("Invalid ENCRYPTION_KEY format")
        Fernet(ENCRYPTION_KEY.encode())
        logger.info("Encryption key validated")
    except ValueError as e:
        logger.error("Invalid encryption key", error=str(e))
        raise ValueError("Invalid ENCRYPTION_KEY format")

# Validate environment variables
required_env_vars = ['STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY', 'PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET',
                    'MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET', 'MPESA_SHORTCODE', 'MPESA_PASSKEY', 'SECRET_KEY',
                    'DATABASE_URL']
for var in required_env_vars:
    if not os.getenv(var):
        logger.error("Missing environment variable", variable=var)
        raise EnvironmentError(f"Environment variable {var} required")

# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
app.config['JWT_COOKIE_CSRF_PROTECT'] = os.getenv('FLASK_ENV') != 'development'
app.config['JWT_COOKIE_SECURE'] = os.getenv('FLASK_ENV') != 'development'
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_COOKIE_SAMESITE'] = 'Lax'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=12)
app.config['WTF_CSRF_ENABLED'] = True
app.config['STRIPE_PUBLISHABLE_KEY'] = os.getenv('STRIPE_PUBLISHABLE_KEY')
app.config['MPESA_CONSUMER_KEY'] = os.getenv('MPESA_CONSUMER_KEY')
app.config['MPESA_CONSUMER_SECRET'] = os.getenv('MPESA_CONSUMER_SECRET')
app.config['MPESA_SHORTCODE'] = os.getenv('MPESA_SHORTCODE')
app.config['MPESA_PASSKEY'] = os.getenv('MPESA_PASSKEY')
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL')
app.config['REDIS_URL'] = os.getenv('REDIS_URL')
app.config['SENTRY_DSN'] = os.getenv('SENTRY_DSN')
app.config['SUBSCRIPTION_DURATION_DAYS'] = int(os.getenv('SUBSCRIPTION_DURATION_DAYS', 30))

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_FILE_SIZE = 5 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename, file_stream):
    if not '.' in filename or filename.rsplit('.', 1)[1].lower() not in ALLOWED_EXTENSIONS:
        return False
    mime = magic.Magic(mime=True)
    file_stream.seek(0)
    file_mime = mime.from_buffer(file_stream.read(2048))
    file_stream.seek(0)
    return file_mime in ['image/png', 'image/jpeg']

# Initialize Sentry
if app.config['SENTRY_DSN']:
    sentry_sdk.init(
        dsn=app.config['SENTRY_DSN'],
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1
    )
    logger.info("Sentry initialized")

# Initialize Redis
# redis_client = Redis.from_url(app.config['REDIS_URL'])

socketio = SocketIO(app, message_queue=app.config['REDIS_URL'], async_mode='eventlet')
csrf = CSRFProtect(app)
app.config['WTF_CSRF_ENABLED'] = False
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)
jwt = JWTManager(app)

# Initialize Flask-Assets
assets = Environment(app)
css = Bundle('css/styles.css', filters='cssmin', output='gen/min.css')
js = Bundle('js/scripts.js', filters='jsmin', output='gen/min.js')
assets.register('css_all', css)
assets.register('js_all', js)

# Load config.json
try:
    with open('config.json', 'r') as config_file:
        config_data = json.load(config_file)
    app.config.update(config_data)
except FileNotFoundError:
    logger.error("Config file not found")
    raise

nairobi_tz = pytz.timezone('Africa/Nairobi')
cipher = Fernet(ENCRYPTION_KEY.encode())

# Database setup
def get_db_connection():
    if 'db' not in g:
        logger.info("Connecting to PostgreSQL")
        g.db = psycopg.connect(app.config['DATABASE_URL'])
        g.db.autocommit = False
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db:
        db.close()
        logger.info("Database connection closed")


ORGANIZATION_TYPES = {
    'hotel': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management'], 'default_plan': 'pro'},
    'school': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations'], 'default_plan': 'pro'},
    'retail': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'bulk_operations', 'analytics'], 'default_plan': 'pro'}
}

SUBSCRIPTION_TIERS = {
    'basic': {'price': 10, 'employee_limit': 10, 'duration_days': 30},
    'premium': {'price': 20, 'employee_limit': 20, 'duration_days': 60}
}

def init_db():
    with app.app_context():
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS employees (
                        employee_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT,
                        role TEXT,
                        organization_id TEXT,
                        fingerprint_template TEXT,
                        biometric_hash TEXT,
                        photo_url TEXT,
                        FOREIGN KEY (organization_id) REFERENCES users (username)
                    );
                    CREATE INDEX IF NOT EXISTS idx_employees_organization_id ON employees (organization_id);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS attendance (
                        id SERIAL PRIMARY KEY,
                        employee_id TEXT,
                        name TEXT,
                        date TEXT,
                        time_in TEXT,
                        time_out TEXT,
                        timestamp TEXT,
                        FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance (date);
                    CREATE INDEX IF NOT EXISTS idx_attendance_employee_id ON attendance (employee_id);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        email TEXT NOT NULL,
                        name TEXT,
                        password_hash TEXT NOT NULL,
                        organization_type TEXT NOT NULL,
                        role TEXT DEFAULT 'admin'
                    );
                    CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        organization_id TEXT PRIMARY KEY,
                        plan TEXT NOT NULL,
                        employee_limit INTEGER NOT NULL,
                        start_date TEXT NOT NULL,
                        end_date TEXT,
                        FOREIGN KEY (organization_id) REFERENCES users (username)
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS rooms (
                        room_id TEXT PRIMARY KEY,
                        room_type TEXT NOT NULL,
                        status TEXT DEFAULT 'available' CHECK (status IN ('available', 'occupied', 'maintenance'))
                    );
                    CREATE INDEX IF NOT EXISTS idx_rooms_status ON rooms (status);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bookings (
                        booking_id SERIAL PRIMARY KEY,
                        guest_id TEXT,
                        guest_name TEXT NOT NULL,
                        room_id TEXT,
                        check_in_date TEXT NOT NULL,
                        check_out_date TEXT NOT NULL,
                        status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'checked_in', 'completed', 'cancelled')),
                        payment_status TEXT DEFAULT 'pending' CHECK (payment_status IN ('pending', 'completed', 'failed')),
                        FOREIGN KEY (room_id) REFERENCES rooms (room_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_bookings_room_id ON bookings (room_id);
                    CREATE INDEX IF NOT EXISTS idx_bookings_guest_id ON bookings (guest_id);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS guests (
                        guest_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        check_in_date TEXT,
                        check_out_date TEXT,
                        room_id TEXT,
                        status TEXT DEFAULT 'completed' CHECK (status IN ('checked_in', 'checked_out', 'completed')),
                        FOREIGN KEY (room_id) REFERENCES rooms (room_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_guests_status ON guests (status);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        transaction_id TEXT PRIMARY KEY,
                        username TEXT,
                        amount FLOAT NOT NULL DEFAULT 0.0,
                        plan TEXT,
                        payment_method TEXT,
                        status TEXT NOT NULL,
                        created_at TEXT,
                        FOREIGN KEY (username) REFERENCES users (username)
                    );
                    CREATE INDEX IF NOT EXISTS idx_transactions_username ON transactions (username);
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS configurations (
                        config_key TEXT PRIMARY KEY,
                        config_value TEXT NOT NULL
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS qr_codes (
                        id SERIAL PRIMARY KEY,
                        qr_code TEXT NOT NULL UNIQUE,
                        user_id TEXT NOT NULL,
                        user_type TEXT NOT NULL CHECK (user_type IN ('employee', 'guest')),
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP NOT NULL,
                        used BOOLEAN DEFAULT FALSE
                    );
                    CREATE INDEX IF NOT EXISTS idx_qr_code ON qr_codes (qr_code);
                """)
                cursor.execute("SELECT config_key FROM configurations WHERE config_key = %s", ('room_pricing',))
                if not cursor.fetchone():
                    room_pricing = {'standard': 50, 'deluxe': 80, 'suite': 150}
                    subscription_tiers = {
                        'free': {'employee_limit': 10, 'features': ['dashboard', 'attendance', 'employee_management'], 'price': 0},
                        'starter': {'employee_limit': 50, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'hotel_booking', 'guest_management'], 'price': 25},
                        'pro': {'employee_limit': 500, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management'], 'price': 35},
                        'enterprise': {'employee_limit': 10000, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management', 'custom'], 'price': 99}
                    }
                    cursor.execute("INSERT INTO configurations (config_key, config_value) VALUES (%s, %s)", ('room_pricing', json.dumps(room_pricing)))
                    cursor.execute("INSERT INTO configurations (config_key, config_value) VALUES (%s, %s)", ('subscription_tiers', json.dumps(subscription_tiers)))
                cursor.execute("SELECT * FROM users WHERE username = %s", ('admin',))
                if not cursor.fetchone():
                    logger.info("Creating default admin user")
                    password_hash = bcrypt.hash('admin123')
                    cursor.execute("INSERT INTO users (username, email, name, password_hash, organization_type, role) VALUES (%s, %s, %s, %s, %s, %s)",
                                   ('admin', 'admin@example.com', 'Admin User', password_hash, 'hotel', 'admin'))
                    cursor.execute("INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (%s, %s, %s, %s)",
                                   ('admin', 'starter', 50, date.today().isoformat()))
                    cursor.execute("INSERT INTO rooms (room_id, room_type) VALUES (%s, %s)", ('R001', 'standard'))
                    cursor.execute("INSERT INTO rooms (room_id, room_type) VALUES (%s, %s)", ('R002', 'deluxe'))
                    conn.commit()
                    logger.info("Default admin user created")
            conn.commit()
        except psycopg.Error as e:
            logger.error("Database initialization error", error=str(e))
            conn.rollback()
            raise

def get_config(config_key):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT config_value FROM configurations WHERE config_key = %s", (config_key,))
            result = cursor.fetchone()
            return json.loads(result[0]) if result else {}

def load_configurations():
    with app.app_context():
        global ROOM_PRICING, SUBSCRIPTION_TIERS
        ROOM_PRICING = get_config('room_pricing')
        SUBSCRIPTION_TIERS = get_config('subscription_tiers')

def get_config(config_key):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT config_value FROM configurations WHERE config_key = %s", (config_key,))
            result = cursor.fetchone()
            return json.loads(result[0]) if result else {}

# Initialize payment gateways
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
paypal_mode = 'live' if os.getenv('FLASK_ENV') == 'production' else 'sandbox'
paypalrestsdk.configure({
    "mode": paypal_mode,
    "client_id": os.getenv('PAYPAL_CLIENT_ID'),
    "client_secret": os.getenv('PAYPAL_CLIENT_SECRET')
})

def get_mpesa_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (app.config['MPESA_CONSUMER_KEY'], app.config['MPESA_CONSUMER_SECRET'])
    try:
        response = requests.get(api_url, auth=auth, timeout=10)
        response.raise_for_status()
        return response.json().get('access_token')
    except requests.RequestException as e:
        logger.error("M-Pesa access token error", error=str(e))
        return None

def validate_mpesa_signature(data):
    logger.warning("M-Pesa signature validation placeholder")
    return True

def validate_email(email):
    try:
        email_validator.validate_email(email)
        return True
    except email_validator.EmailNotValidError:
        return False

def validate_date(date_str):
    try:
        parse_date(date_str)
        return True
    except ValueError:
        return False

def verify_subscription_feature(username, feature):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT plan FROM subscriptions WHERE organization_id = %s", (username,))
            subscription = cursor.fetchone()
            if not subscription:
                return (False, jsonify({'error': 'No subscription found'}), 403)
            plan = subscription[0]
            return (True, None, None) if feature in SUBSCRIPTION_TIERS[plan]['features'] else (False, jsonify({'error': f'Feature {feature} not available'}), 403)

def verify_employee_limit(username):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT employee_limit FROM subscriptions WHERE organization_id = %s", (username,))
            subscription = cursor.fetchone()
            if not subscription:
                return False, jsonify({'error': 'No subscription found'}), 0
            employee_limit = subscription[0]
            cursor.execute("SELECT COUNT(*) FROM employees WHERE organization_id = %s", (username,))
            current_count = cursor.fetchone()[0]
            return current_count < employee_limit, jsonify({'error': 'Employee limit reached'}), current_count

def sanitize_input(value):
    if isinstance(value, str):
        return re.sub(r'[^\w\s-]', '', value.strip())
    return value

def match_fingerprint(scan_data, stored_hash):
    try:
        scan_hash = hashlib.sha256(scan_data.encode()).hexdigest()
        return scan_hash == stored_hash
    except Exception as e:
        logger.error("Biometric matching error", error=str(e))
        return False

def encrypt_guest_name(name):
    return cipher.encrypt(name.encode()).decode()

def decrypt_guest_name(encrypted_name):
    try:
        return cipher.decrypt(encrypted_name.encode()).decode()
    except Exception as e:
        logger.error("Decryption error", error=str(e))
        return "Unknown"

# HTTPS enforcement
@app.before_request
def enforce_https():
    if not request.is_secure and os.getenv('FLASK_ENV') == 'production':
        url = request.url.replace('http://', 'https://', 1)
        logger.info("Redirecting to HTTPS", url=url)
        return redirect(url, code=301)

# SocketIO rate limiter
def socketio_limit(rate_limit):
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            key = f"socketio_{request.sid}_{f.__name__}"
            if not limiter._limiter.limit(rate_limit, key).test():
                logger.warning("SocketIO rate limit exceeded", client_id=request.sid)
                emit('error', {'error': 'Too many requests'})
                return
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.route('/')
@jwt_required(optional=True)
def index():
    current_user = get_jwt_identity()
    if current_user:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/health', methods=['GET'])
def health():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        return jsonify({'status': 'healthy', 'database': 'connected'}), 200
    except psycopg.Error as e:
        logger.error("Health check failed", error=str(e))
        return jsonify({'status': 'unhealthy', 'database': 'disconnected'}), 500

@app.route('/dashboard', methods=['GET'])
@jwt_required()
def dashboard():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user:
                logger.error("User not found", username=username)
                return jsonify({'error': 'User not found'}), 404
            role = user[0]
            current_time = nairobi_tz.localize(datetime.now()).strftime('%H:%M:%S')
            today = nairobi_tz.localize(datetime.now()).date().isoformat()

            # Pagination parameters
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page

            # Attendance records
            cursor.execute("SELECT COUNT(*) FROM attendance WHERE date = %s", (today,))
            total_records = cursor.fetchone()[0]
            cursor.execute("""
                SELECT employee_id, name, date, time_in, time_out 
                FROM attendance 
                WHERE date = %s 
                ORDER BY timestamp DESC 
                LIMIT %s OFFSET %s
            """, (today, per_page, offset))
            records = cursor.fetchall()
            records_pagination = {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_records,
                'total_pages': (total_records + per_page - 1) // per_page
            }

            # Rooms
            cursor.execute("SELECT COUNT(*) FROM rooms")
            total_rooms = cursor.fetchone()[0]
            cursor.execute("""
                SELECT room_id, room_type, status 
                FROM rooms 
                ORDER BY room_id 
                LIMIT %s OFFSET %s
            """, (per_page, offset))
            rooms = cursor.fetchall()
            rooms_pagination = {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_rooms,
                'total_pages': (total_rooms + per_page - 1) // per_page
            }

            # Guests
            cursor.execute("SELECT COUNT(*) FROM guests WHERE status = %s", ('checked_in',))
            total_guests = cursor.fetchone()[0]
            cursor.execute("""
                SELECT guest_id, name, check_in_date, check_out_date, status 
                FROM guests 
                WHERE status = %s 
                ORDER BY check_in_date DESC 
                LIMIT %s OFFSET %s
            """, ('checked_in', per_page, offset))
            guests = [dict(g) for g in cursor.fetchall()]
            for guest in guests:
                guest['name'] = decrypt_guest_name(guest['name'])

            guests_pagination = {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_guests,
                'total_pages': (total_guests + per_page - 1) // per_page
            }

    try:
        return render_template(
            'dashboard.html',
            records=records,
            records_pagination=records_pagination,
            rooms=rooms,
            rooms_pagination=rooms_pagination,
            guests=guests,
            guests_pagination=guests_pagination,
            config=app.config,
            current_year=datetime.now().year,
            datetime=datetime,
            current_time=current_time,
            hasLoggedIn=True,
            username=username,
            userRole=role
        )
    except TemplateNotFound as e:
        logger.error("Template not found", template="dashboard.html", error=str(e))
        return jsonify({'error': 'Template error'}), 500

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
        login_type = sanitize_input(request.form.get('login_type'))
        if not username or not password or not login_type:
            flash('All fields required.', 'danger')
            return render_template('login.html', config=app.config, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if login_type == 'employee':
                    cursor.execute("SELECT password_hash, role FROM users WHERE username = %s", (username,))
                    user = cursor.fetchone()
                    if user and bcrypt.verify(password, user[0]):
                        access_token = create_access_token(identity=username, additional_claims={'role': user[1]})
                        response = make_response(redirect(url_for('dashboard')))
                        set_access_cookies(response, access_token)
                        flash('Login successful!', 'success')
                        logger.info("User logged in", username=username)
                        return response
                elif login_type == 'guest':
                    cursor.execute("SELECT name FROM guests WHERE guest_id = %s", (username,))
                    guest = cursor.fetchone()
                    if guest:
                        access_token = create_access_token(identity=username, additional_claims={'role': 'guest'})
                        response = make_response(redirect(url_for('dashboard')))
                        set_access_cookies(response, access_token)
                        flash('Guest login successful!', 'success')
                        logger.info("Guest logged in", guest_id=username)
                        return response
                flash('Invalid credentials.', 'danger')
                logger.warning("Login failed", username=username)
                return render_template('login.html', config=app.config, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
    return render_template('login.html', config=app.config, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')

@app.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    response = make_response(jsonify({'success': True, 'message': 'Logged out'}))
    unset_jwt_cookies(response)
    flash('Logged out.', 'success')
    logger.info("User logged out", username=get_jwt_identity())
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
        role = 'admin'
        if not all([username, email, password, organization_type]):
            flash('All fields required.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
        if not validate_email(email):
            flash('Invalid email.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
        if organization_type not in ORGANIZATION_TYPES:
            flash('Invalid organization type.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
        password_hash = bcrypt.hash(password)
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
                    if cursor.fetchone():
                        flash('Username exists.', 'danger')
                        return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
                    cursor.execute("INSERT INTO users (username, email, password_hash, organization_type, role) VALUES (%s, %s, %s, %s, %s)",
                                   (username, email, password_hash, organization_type, role))
                    default_plan = ORGANIZATION_TYPES[organization_type]['default_plan']
                    employee_limit = SUBSCRIPTION_TIERS[default_plan]['employee_limit']
                    cursor.execute("INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (%s, %s, %s, %s)",
                                   (username, default_plan, employee_limit, date.today().isoformat()))
                    conn.commit()
            flash('Registration successful!', 'success')
            logger.info("User registered", username=username)
            return redirect(url_for('login'))
        except psycopg.Error as e:
            logger.error("Registration error", error=str(e))
            flash('Registration failed.', 'danger')
            return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')
    return render_template('register.html', organization_types=ORGANIZATION_TYPES, current_year=datetime.now().year, datetime=datetime, hasLoggedIn=False, username='', userRole='')

@app.route('/subscribe', methods=['GET', 'POST'])
@jwt_required()
def subscribe():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if request.method == 'GET':
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if not user:
                    flash('User not found.', 'danger')
                    return render_template('error.html', message='User not found', config=app.config, hasLoggedIn=False, username='', userRole='', current_year=datetime.now().year, datetime=datetime)
                cursor.execute("SELECT plan, employee_limit, start_date, end_date FROM subscriptions WHERE organization_id = %s", (username,))
                subscription = cursor.fetchone()
                if not subscription:
                    org_type = user[4]
                    default_plan = ORGANIZATION_TYPES.get(org_type, {}).get('default_plan', 'free')
                    employee_limit = SUBSCRIPTION_TIERS[default_plan]['employee_limit']
                    cursor.execute("INSERT INTO subscriptions (organization_id, plan, employee_limit, start_date) VALUES (%s, %s, %s, %s)",
                                   (username, default_plan, employee_limit, date.today().isoformat()))
                    conn.commit()
                    cursor.execute("SELECT plan, employee_limit, start_date, end_date FROM subscriptions WHERE organization_id = %s", (username,))
                    subscription = cursor.fetchone()
                transaction_id = str(uuid.uuid4())
                return render_template(
                    'subscribe.html',
                    config=app.config,
                    subscription=dict(zip(['plan', 'employee_limit', 'start_date', 'end_date'], subscription)),
                    subscription_tiers=SUBSCRIPTION_TIERS,
                    stripe_publishable_key=app.config['STRIPE_PUBLISHABLE_KEY'],
                    paypal_client_id=os.getenv('PAYPAL_CLIENT_ID'),
                    transaction_id=transaction_id,
                    hasLoggedIn=True,
                    username=username,
                    userRole='admin',
                    current_year=datetime.now().year,
                    datetime=datetime
                )
            else:
                plan_type = request.form.get('plan_type')
                payment_method = request.form.get('payment_method')
                transaction_id = request.form.get('transaction_id')
                if not all([plan_type, payment_method, transaction_id]):
                    logger.warning("Subscription failed: missing fields", username=username)
                    return jsonify({'error': 'Required fields missing'}), 400
                if plan_type not in SUBSCRIPTION_TIERS:
                    logger.warning("Subscription failed: invalid plan", plan=plan_type)
                    return jsonify({'error': 'Invalid plan type'}), 400
                amount = SUBSCRIPTION_TIERS[plan_type]['price']
                employee_limit = SUBSCRIPTION_TIERS[plan_type]['employee_limit']
                cursor.execute("INSERT INTO transactions (transaction_id, username, amount, plan, payment_method, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                               (transaction_id, username, amount, plan_type, payment_method, 'pending', nairobi_tz.localize(datetime.now()).strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                if amount == 0:
                    cursor.execute("UPDATE subscriptions SET plan = %s, employee_limit = %s, start_date = %s, end_date = %s WHERE organization_id = %s",
                                   (plan_type, employee_limit, date.today().isoformat(), None, username))
                    cursor.execute("UPDATE transactions SET status = %s WHERE transaction_id = %s",
                                   ('completed', transaction_id))
                    conn.commit()
                    flash('Subscribed to free plan.', 'success')
                    logger.info("Subscribed to free plan", username=username)
                    return render_template('success.html', message=f'Subscription upgraded to {plan_type} plan', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)
                if payment_method == 'stripe':
                    payment_method_id = request.form.get('payment_method_id')
                    if not payment_method_id:
                        logger.warning("Stripe payment failed: missing payment method ID")
                        return jsonify({'error': 'Card details required'}), 400
                    try:
                        intent = stripe.checkout.Session.create(
                            payment_method_types=['card'],
                            line_items=[{
                                'price_data': {
                                    'currency': 'usd',
                                    'unit_amount': int(amount * 100),
                                    'product_data': {
                                        'name': f'{plan_type.capitalize()} Subscription'
                                    },
                                },
                                'quantity': 1,
                            }],
                            mode='payment',
                            success_url=f"{request.host_url}completed/success?transaction_id={transaction_id}&plan={plan_type}",
                            cancel_url=f"{request.host_url}completed/canceled?error=Payment%20canceled",
                            metadata={'username': username, 'transaction_id': transaction_id}
                        )
                        logger.info("Stripe payment initiated", username=username)
                        return jsonify({'success': True, 'session_id': intent.id})
                    except stripe.error.StripeError as e:
                        logger.error("Stripe payment error", error=str(e))
                        return jsonify({'error': f'Stripe error: {str(e)}'}), 400
                elif payment_method == 'paypal':
                    paypal_order_id = request.form.get('paypal_order_id')
                    if not paypal_order_id:
                        logger.warning("PayPal payment failed: missing order ID")
                        return jsonify({'error': 'PayPal order ID required'}), 400
                    try:
                        payment = paypalrestsdk.Order.find(paypal_order_id)
                        if payment.capture():
                            cursor.execute("UPDATE subscriptions SET plan = %s, employee_limit = %s, start_date = %s, end_date = %s WHERE organization_id = %s",
                                           (plan_type, employee_limit, date.today().isoformat(), (nairobi_tz.localize(datetime.now()) + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d'), username))
                            cursor.execute("UPDATE transactions SET status = %s WHERE transaction_id = %s",
                                           ('completed', transaction_id))
                            conn.commit()
                            logger.info("PayPal payment completed", username=username)
                            return jsonify({'success': True, 'order_id': paypal_order_id, 'plan': plan_type})
                        else:
                            logger.error("PayPal payment capture failed")
                            return jsonify({'error': 'PayPal payment failed'}), 400
                    except paypalrestsdk.exceptions.ResourceNotFound:
                        logger.error("PayPal order not found", order_id=paypal_order_id)
                        return jsonify({'error': 'Invalid PayPal order ID'}), 400
                elif payment_method == 'mpesa':
                    mpesa_number = request.form.get('mpesa_number')
                    if not mpesa_number or not re.match(r'^2547\d{8}$', mpesa_number):
                        logger.warning("M-Pesa payment failed: invalid phone number")
                        return jsonify({'error': 'Valid M-Pesa phone number required'}), 400
                    try:
                        access_token = get_mpesa_access_token()
                        if not access_token:
                            logger.error("Failed to get M-Pesa access token")
                            return jsonify({'error': 'M-Pesa access token error'}), 500
                        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                        password = base64.b64encode(f"{app.config['MPESA_SHORTCODE']}{app.config['MPESA_PASSKEY']}{timestamp}".encode()).decode()
                        api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
                        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                        payload = {
                            "BusinessShortCode": app.config['MPESA_SHORTCODE'],
                            "Password": password,
                            "Timestamp": timestamp,
                            "TransactionType": "CustomerPayBillOnline",
                            "Amount": amount,
                            "PartyA": mpesa_number,
                            "PartyB": app.config['MPESA_SHORTCODE'],
                            "PhoneNumber": mpesa_number,
                            "CallBackURL": f"{request.host_url}mpesa/callback",
                            "AccountReference": f"Sub-{username}-{plan_type}-{transaction_id}",
                            "TransactionDesc": f"Subscription to {plan_type} plan"
                        }
                        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
                        result = response.json()
                        if response.status_code == 200 and result.get('ResponseCode') == '0':
                            logger.info("M-Pesa payment request sent", username=username)
                            return jsonify({'success': True, 'message': 'M-Pesa payment request sent'})
                        else:
                            logger.error("M-Pesa payment initiation failed", error=result.get('errorMessage'))
                            return jsonify({'error': 'M-Pesa payment failed'}), 400
                    except Exception as e:
                        logger.error("M-Pesa payment error", error=str(e))
                        return jsonify({'error': f'M-Pesa error: {str(e)}'}), 500
                else:
                    logger.warning("Invalid payment method", method=payment_method)
                    return jsonify({'error': 'Invalid payment method'}), 400


@app.route('/subscribe/success')
@jwt_required()
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def subscribe_success():
    username = sanitize_input(get_jwt_identity())
    session_id = sanitize_input(request.args.get('session_id'))
    plan = sanitize_input(request.args.get('plan'))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM transactions WHERE transaction_id = %s", (session_id,))
            transaction = cursor.fetchone()
            if not transaction or transaction[0] == 'completed':
                flash('Invalid transaction.', 'danger')
                logger.warning("Invalid transaction", transaction_id=session_id)
                return redirect(url_for('dashboard'))
            cursor.execute("UPDATE transactions SET status = %s WHERE transaction_id = %s",
                           ('completed', session_id))
            cursor.execute("UPDATE subscriptions SET plan = %s, employee_limit = %s, start_date = %s, end_date = %s WHERE organization_id = %s",
                           (plan, SUBSCRIPTION_TIERS[plan]['employee_limit'], date.today().isoformat(), (nairobi_tz.localize(datetime.now()) + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d'), username))
            conn.commit()
            flash(f'Subscription upgraded to {plan}.', 'success')
            logger.info("Subscription upgraded", username=username)
            return redirect(url_for('dashboard'))

@app.route('/subscribe/cancel')
@jwt_required()
def subscribe_cancel():
    flash('Payment cancelled.', 'info')
    logger.info("Subscription payment cancelled", username=get_jwt_identity())
    return redirect(url_for('subscribe'))

@app.route('/subscribe/paypal/success')
@jwt_required()
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def subscribe_paypal_success():
    username = sanitize_input(get_jwt_identity())
    plan = sanitize_input(request.args.get('plan'))
    transaction_id = sanitize_input(request.args.get('transaction_id'))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT status FROM transactions WHERE transaction_id = %s", (transaction_id,))
            transaction = cursor.fetchone()
            if not transaction or transaction[0] == 'completed':
                flash('Invalid transaction.', 'danger')
                logger.warning("Invalid transaction", transaction_id=transaction_id)
                return redirect(url_for('dashboard'))
            cursor.execute("UPDATE transactions SET status = %s WHERE transaction_id = %s",
                           ('completed', transaction_id))
            cursor.execute("UPDATE subscriptions SET plan = %s, employee_limit = %s, start_date = %s, end_date = %s WHERE organization_id = %s",
                           (plan, SUBSCRIPTION_TIERS[plan]['employee_limit'], date.today().isoformat(), (nairobi_tz.localize(datetime.now()) + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d'), username))
            conn.commit()
            flash(f'Subscription upgraded to {plan}.', 'success')
            logger.info("PayPal subscription upgraded", username=username)
            return redirect(url_for('dashboard'))

@app.route('/subscribe/paypal/cancel')
@jwt_required()
def subscribe_paypal_cancel():
    flash('PayPal payment cancelled.', 'info')
    logger.info("PayPal subscription cancelled", username=get_jwt_identity())
    return redirect(url_for('subscribe'))

@app.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    if not validate_mpesa_signature(data):
        logger.error("Invalid M-Pesa callback signature")
        return jsonify({'error': 'Invalid signature'}), 400
    try:
        if data['Body']['stkCallback']['ResultCode'] == 0:
            callback_data = data['Body']['stkCallback']['CallbackMetadata']['Item']
            account_reference = next(item['Value'] for item in callback_data if item['Name'] == 'AccountReference')
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if account_reference.startswith('Booking-'):
                        guest_id = account_reference.split('-')[1]
                        cursor.execute("UPDATE bookings SET payment_status = %s WHERE guest_id = %s", ('completed', guest_id))
                        conn.commit()
                        logger.info("M-Pesa payment for booking processed", guest_id=guest_id)
                        return jsonify({'success': True, 'message': 'M-Pesa payment processed'})
                    elif account_reference.startswith('Sub-'):
                        _, username, plan, transaction_id = account_reference.split('-')
                        cursor.execute("SELECT status FROM transactions WHERE transaction_id = %s AND status = %s", (transaction_id, 'pending'))
                        transaction = cursor.fetchone()
                        if not transaction:
                            logger.warning("Invalid transaction", transaction_id=transaction_id)
                            return jsonify({'error': 'Invalid transaction'}), 400
                        cursor.execute("UPDATE transactions SET status = %s WHERE transaction_id = %s",
                                       ('completed', transaction_id))
                        cursor.execute("UPDATE subscriptions SET plan = %s, employee_limit = %s, start_date = %s, end_date = %s WHERE organization_id = %s",
                                       (plan, SUBSCRIPTION_TIERS[plan]['employee_limit'], date.today().isoformat(), (nairobi_tz.localize(datetime.now()) + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d'), username))
                        conn.commit()
                        logger.info("M-Pesa payment processed", username=username)
                        return jsonify({'success': True, 'message': 'M-Pesa payment processed'})
                    else:
                        logger.error("Invalid account reference", account_reference=account_reference)
                        return jsonify({'error': 'Invalid account reference'}), 400
        else:
            logger.error("M-Pesa payment failed", error=data.get('errorMessage'))
            return jsonify({'error': 'M-Pesa payment failed'}), 400
    except Exception as e:
        logger.error("M-Pesa callback error", error=str(e))
        return jsonify({'error': 'Callback processing failed'}), 500

@app.route('/attendance', methods=['GET'])
@jwt_required()
def get_attendance():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] not in ['admin', 'employee']:
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            start_date = sanitize_input(request.args.get('start_date'))
            end_date = sanitize_input(request.args.get('end_date'))
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            try:
                if start_date and end_date:
                    if not validate_date(start_date) or not validate_date(end_date):
                        logger.warning("Invalid date format")
                        return jsonify({'error': 'Invalid date format'}), 400
                    cursor.execute("SELECT COUNT(*) FROM attendance WHERE date BETWEEN %s AND %s", (start_date, end_date))
                    total_records = cursor.fetchone()[0]
                    cursor.execute("""
                        SELECT employee_id, name, date, time_in, time_out 
                        FROM attendance 
                        WHERE date BETWEEN %s AND %s 
                        ORDER BY timestamp DESC 
                        LIMIT %s OFFSET %s
                    """, (start_date, end_date, per_page, offset))
                else:
                    cursor.execute("SELECT COUNT(*) FROM attendance")
                    total_records = cursor.fetchone()[0]
                    cursor.execute("""
                        SELECT employee_id, name, date, time_in, time_out 
                        FROM attendance 
                        ORDER BY timestamp DESC 
                        LIMIT %s OFFSET %s
                    """, (per_page, offset))
                records = [dict(record) for record in cursor.fetchall()]
                response_data = {
                    'success': True,
                    'records': records,
                    'pagination': {
                        'current_page': page,
                        'per_page': per_page,
                        'total_items': total_records,
                        'total_pages': (total_records + per_page - 1) // per_page
                    }
                }
                logger.info("Attendance retrieved", username=username, page=page, total=total_records)
                return jsonify(response_data)
            except psycopg.Error as e:
                logger.error("Attendance error", error=str(e), exc_info=True)
                sentry_sdk.capture_exception(e)
                return jsonify({'error': 'Failed to retrieve attendance'}), 500

@app.route('/employees', methods=['GET'])
@jwt_required()
def employees():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            cursor.execute("SELECT COUNT(*) FROM employees WHERE organization_id = %s", (username,))
            total_employees = cursor.fetchone()[0]
            cursor.execute("""
                SELECT employee_id, name, email, role, fingerprint_template, photo_url 
                FROM employees 
                WHERE organization_id = %s 
                ORDER BY name 
                LIMIT %s OFFSET %s
            """, (username, per_page, offset))
            employees = cursor.fetchall()
            pagination = {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_employees,
                'total_pages': (total_employees + per_page - 1) // per_page
            }
            logger.info("Employees page rendered", username=username, page=page)
            return render_template(
                'employees.html',
                employees=employees,
                pagination=pagination,
                hasLoggedIn=True,
                username=username,
                userRole=user[0],
                current_year=datetime.now().year,
                datetime=datetime
            )
            

@app.route('/employees/api', methods=['GET'])
@jwt_required()
def get_employees():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            cursor.execute("SELECT COUNT(*) FROM employees WHERE organization_id = %s", (username,))
            total_employees = cursor.fetchone()[0]
            cursor.execute("""
                SELECT employee_id, name, email, role, fingerprint_template, photo_url 
                FROM employees 
                WHERE organization_id = %s 
                ORDER BY name 
                LIMIT %s OFFSET %s
            """, (username, per_page, offset))
            employees = [dict(emp) for emp in cursor.fetchall()]
            logger.info("Employees retrieved", username=username, page=page)
            return jsonify({
                'success': True,
                'employees': employees,
                'pagination': {
                    'current_page': page,
                    'per_page': per_page,
                    'total_items': total_employees,
                    'total_pages': (total_employees + per_page - 1) // per_page
                }
            })

@app.route('/employees/api/<employee_id>', methods=['PUT'])
@jwt_required()
def edit_employee(employee_id):
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response
            name = sanitize_input(request.form.get('name'))
            email = sanitize_input(request.form.get('email', ''))
            role_field = sanitize_input(request.form.get('role', 'employee'))
            fingerprint_template = sanitize_input(request.form.get('fingerprint_template'))
            biometric_data = sanitize_input(request.form.get('biometric_data'))
            photo = request.files.get('photo')
            photo_url = None
            biometric_hash = hashlib.sha256(biometric_data.encode()).hexdigest() if biometric_data else None
            if not all([name, fingerprint_template]):
                logger.warning("Employee edit failed: missing fields")
                return jsonify({'error': 'Name and fingerprint required'}), 400
            if email and not validate_email(email):
                logger.warning("Employee edit failed: invalid email")
                return jsonify({'error': 'Invalid email'}), 400
            if photo and allowed_file(photo.filename, photo.stream):
                photo.stream.seek(0, os.SEEK_END)
                file_size = photo.stream.tell()
                photo.stream.seek(0)
                if file_size > MAX_FILE_SIZE:
                    logger.warning("Employee edit failed: file too large")
                    return jsonify({'error': 'File size exceeds 5MB'}), 400
                filename = secure_filename(f"{employee_id}_{photo.filename}")
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(photo_path)
                photo_url = f"/static/uploads/{filename}"
                logger.info("Photo uploaded", employee_id=employee_id)
            cursor.execute("SELECT photo_url FROM employees WHERE employee_id = %s AND organization_id = %s", (employee_id, username))
            existing = cursor.fetchone()
            if not existing:
                logger.warning("Employee not found", employee_id=employee_id)
                return jsonify({'error': 'Employee not found'}), 404
            update_query = "UPDATE employees SET name = %s, email = %s, role = %s, fingerprint_template = %s"
            params = [name, email, role_field, fingerprint_template]
            if biometric_hash:
                update_query += ", biometric_hash = %s"
                params.append(biometric_hash)
            if photo_url:
                update_query += ", photo_url = %s"
                params.append(photo_url)
            update_query += " WHERE employee_id = %s AND organization_id = %s"
            params.extend([employee_id, username])
            cursor.execute(update_query, params)
            conn.commit()
            logger.info("Employee updated", employee_id=employee_id)
            return jsonify({'success': True, 'message': 'Employee updated'})

@app.route('/employees/api/<employee_id>', methods=['DELETE'])
@jwt_required()
def delete_employee(employee_id):
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response
            cursor.execute("SELECT employee_id FROM employees WHERE employee_id = %s AND organization_id = %s", (employee_id, username))
            if not cursor.fetchone():
                logger.warning("Employee not found", employee_id=employee_id)
                return jsonify({'error': 'Employee not found'}), 404
            cursor.execute("DELETE FROM employees WHERE employee_id = %s AND organization_id = %s", (employee_id, username))
            cursor.execute("DELETE FROM attendance WHERE employee_id = %s", (employee_id,))
            conn.commit()
            logger.info("Employee deleted", employee_id=employee_id)
            return jsonify({'success': True, 'message': 'Employee deleted'})

@app.route('/employees/bulk_import', methods=['POST'])
@jwt_required()
def bulk_import_employees():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response
            limit_ok, limit_error, current_count = verify_employee_limit(username)
            if not limit_ok:
                logger.warning("Bulk import failed: employee limit")
                return limit_error
            file = request.files.get('file')
            if not file or not file.filename.endswith('.csv'):
                logger.warning("Bulk import failed: invalid file")
                return jsonify({'error': 'CSV file required'}), 400
            try:
                df = pd.read_csv(file)
                required_columns = ['employee_id', 'name', 'fingerprint_template']
                if not all(col in df.columns for col in required_columns):
                    logger.warning("Bulk import failed: missing columns")
                    return jsonify({'error': 'CSV missing required columns'}), 400
                cursor.execute("SELECT employee_limit FROM subscriptions WHERE organization_id = %s", (username,))
                subscription = cursor.fetchone()
                if not subscription:
                    logger.error("No subscription found")
                    return jsonify({'error': 'No subscription found'}), 403
                employee_limit = subscription[0]
                if current_count + len(df) > employee_limit:
                    logger.warning("Bulk import failed: exceeds limit")
                    return jsonify({'error': 'Exceeds employee limit'}), 403
                cursor.execute("SELECT employee_id FROM employees WHERE organization_id = %s", (username,))
                existing_ids = {row[0] for row in cursor.fetchall()}
                count = 0
                for _, row in df.iterrows():
                    employee_id = str(row['employee_id']).strip()
                    if employee_id in existing_ids:
                        continue
                    name = sanitize_input(str(row['name']).strip())
                    fingerprint_template = sanitize_input(str(row['fingerprint_template']).strip())
                    biometric_data = sanitize_input(str(row.get('biometric_data', '')).strip())
                    email = sanitize_input(str(row.get('email', '')).strip())
                    role_field = sanitize_input(str(row.get('role', 'employee')).strip())
                    biometric_hash = hashlib.sha256(biometric_data.encode()).hexdigest() if biometric_data else None
                    if email and not validate_email(email):
                        logger.warning("Skipping employee: invalid email")
                        continue
                    cursor.execute("""
                        INSERT INTO employees (employee_id, name, email, role, fingerprint_template, biometric_hash, organization_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (employee_id, name, email, role_field, fingerprint_template, biometric_hash, username))
                    count += 1
                conn.commit()
                logger.info("Bulk import completed", imported_count=count)
                return jsonify({'success': True, 'message': f'{count} employees imported'})
            except Exception as e:
                logger.error("Bulk import error", error=str(e))
                return jsonify({'error': 'Import failed'}), 500

@app.route('/employees/bulk_delete', methods=['POST'])
@jwt_required()
def bulk_delete_employees():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                return error_response
            data = request.get_json()
            employee_ids = data.get('employee_ids', [])
            if not employee_ids:
                logger.warning("Bulk delete failed: no IDs")
                return jsonify({'error': 'No employee IDs'}), 400
            placeholders = ','.join(['%s'] * len(employee_ids))
            cursor.execute(f"SELECT employee_id FROM employees WHERE employee_id IN ({placeholders}) AND organization_id = %s", (*employee_ids, username))
            valid_ids = {row[0] for row in cursor.fetchall()}
            if not valid_ids:
                logger.warning("Bulk delete failed: no valid employees")
                return jsonify({'error': 'No valid employees'}), 404
            cursor.execute(f"DELETE FROM employees WHERE employee_id IN ({placeholders}) AND organization_id = %s", (*employee_ids, username))
            cursor.execute(f"DELETE FROM attendance WHERE employee_id IN ({placeholders})", employee_ids)
            conn.commit()
            logger.info("Bulk delete completed", deleted_count=len(valid_ids))
            return jsonify({'success': True, 'message': f'{len(valid_ids)} employees deleted'})

@app.route('/users', methods=['GET'])
@jwt_required()
def users():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            if request.headers.get('Accept') == 'application/json':
                cursor.execute("""
                    SELECT username 
                    FROM users 
                    ORDER BY username 
                    LIMIT %s OFFSET %s
                """, (per_page, offset))
                users = [dict(user) for user in cursor.fetchall()]
                logger.info("Users retrieved", username=username, page=page)
                return jsonify({
                    'success': True,
                    'users': users,
                    'pagination': {
                        'current_page': page,
                        'per_page': per_page,
                        'total_items': total_users,
                        'total_pages': (total_users + per_page - 1) // per_page
                    }
                })
            else:
                cursor.execute("""
                    SELECT username 
                    FROM users 
                    ORDER BY username 
                    LIMIT %s OFFSET %s
                """, (per_page, offset))
                users = cursor.fetchall()
                pagination = {
                    'current_page': page,
                    'per_page': per_page,
                    'total_items': total_users,
                    'total_pages': (total_users + per_page - 1) // per_page
                }
                logger.info("Users page rendered", username=username, page=page)
                return render_template(
                    'users.html',
                    users=users,
                    pagination=pagination,
                    config=app.config,
                    current_year=datetime.now().year,
                    datetime=datetime
                )


@app.route('/users/<username>', methods=['DELETE'])
@jwt_required()
def delete_user(target_username):
    current_user = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (current_user,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=current_user)
                return jsonify({'error': 'Access denied'}), 403
            target_username = sanitize_input(target_username)
            if current_user == target_username:
                logger.warning("Attempt to delete own account")
                return jsonify({'error': 'Cannot delete own account'}), 400
            try:
                cursor.execute("DELETE FROM users WHERE username = %s", (target_username,))
                cursor.execute("DELETE FROM subscriptions WHERE organization_id = %s", (target_username,))
                conn.commit()
                logger.info("User deleted", target_username=target_username)
                return jsonify({'success': True, 'message': 'User deleted'})
            except psycopg.Error as e:
                logger.error("Delete user error", error=str(e))
                return jsonify({'error': 'Failed to delete user'}), 500

@app.route('/guest_records', methods=['GET'])
@jwt_required()
def guest_records():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] not in ['admin', 'guest']:
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            try:
                cursor.execute("SELECT COUNT(*) FROM guests WHERE status = %s", ('checked_in',))
                total_guests = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT guest_id, name, room_id, check_in_date, check_out_date, status 
                    FROM guests 
                    WHERE status = %s 
                    ORDER BY check_in_date DESC 
                    LIMIT %s OFFSET %s
                """, ('checked_in', per_page, offset))
                guests = [dict(g) for g in cursor.fetchall()]
                for guest in guests:
                    guest['name'] = decrypt_guest_name(guest['name'])
                response_data = {
                    'success': True,
                    'records': guests,
                    'pagination': {
                        'current_page': page,
                        'per_page': per_page,
                        'total_items': total_guests,
                        'total_pages': (total_guests + per_page - 1) // per_page
                    }
                }
                logger.info("Guest records retrieved", username=username, page=page)
                return jsonify(response_data)
            except psycopg.Error as e:
                logger.error("Guest records error", error=str(e), exc_info=True)
                sentry_sdk.capture_exception(e)
                return jsonify({'error': 'Failed to retrieve guest records'}), 500


@app.route('/analytics')
@jwt_required()
def analytics():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'analytics')
            if not has_access:
                return error_response
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 30)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            try:
                end_date = nairobi_tz.localize(datetime.now()).date()
                start_date = end_date - timedelta(days=30)
                cursor.execute("""
                    SELECT COUNT(DISTINCT date) 
                    FROM attendance 
                    WHERE date BETWEEN %s AND %s
                """, (start_date.isoformat(), end_date.isoformat()))
                total_dates = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT date, COUNT(DISTINCT employee_id) as active_employees
                    FROM attendance
                    WHERE date BETWEEN %s AND %s
                    GROUP BY date
                    ORDER BY date
                    LIMIT %s OFFSET %s
                """, (start_date.isoformat(), end_date.isoformat(), per_page, offset))
                trends = [dict(trend) for trend in cursor.fetchall()]
                logger.info("Analytics retrieved", username=username, page=page)
                return jsonify({
                    'success': True,
                    'trends': trends,
                    'pagination': {
                        'current_page': page,
                        'per_page': per_page,
                        'total_items': total_dates,
                        'total_pages': (total_dates + per_page - 1) // per_page
                    }
                })
            except psycopg.Error as e:
                logger.error("Analytics error", error=str(e), exc_info=True)
                sentry_sdk.capture_exception(e)
                return jsonify({'error': 'Failed to retrieve analytics'}), 500


@app.route('/export', methods=['GET'])
@jwt_required()
def export_attendance():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'csv_export')
            if not has_access:
                return error_response
            try:
                cursor.execute("SELECT employee_id, name, date, time_in, time_out FROM attendance ORDER BY date DESC")
                records = cursor.fetchall()
                df = pd.DataFrame([dict(record) for record in records])
                csv_path = 'attendance_export.csv'
                df.to_csv(csv_path, index=False)
                logger.info("Attendance exported", username=username)
                return send_file(csv_path, as_attachment=True, download_name='attendance_export.csv')
            except psycopg.Error as e:
                logger.error("Export error", error=str(e))
                return jsonify({'error': 'Export failed'}), 500

@app.route('/scan', methods=['POST'])
@jwt_required()
def scan_fingerprint():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] not in ['admin', 'employee']:
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            data = request.get_json()
            scan_data = data.get('fingerprint_data')
            if not scan_data:
                logger.warning("Scan failed: no data")
                return jsonify({'error': 'No fingerprint data'}), 400
            try:
                cursor.execute("SELECT employee_id, name, biometric_hash FROM employees")
                employees = cursor.fetchall()
                for emp in employees:
                    if match_fingerprint(scan_data, emp[2]):
                        today = nairobi_tz.localize(datetime.now()).date().isoformat()
                        current_time = nairobi_tz.localize(datetime.now()).strftime('%H:%M:%S')
                        cursor.execute("SELECT time_in, time_out FROM attendance WHERE employee_id = %s AND date = %s", (emp[0], today))
                        record = cursor.fetchone()
                        if record and not record[1]:
                            cursor.execute("UPDATE attendance SET time_out = %s, timestamp = %s WHERE employee_id = %s AND date = %s",
                                           (current_time, nairobi_tz.localize(datetime.now()).isoformat(), emp[0], today))
                            action = 'check-out'
                        else:
                            cursor.execute("INSERT INTO attendance (employee_id, name, date, time_in, timestamp) VALUES (%s, %s, %s, %s, %s)",
                                           (emp[0], emp[1], today, current_time, nairobi_tz.localize(datetime.now()).isoformat()))
                            action = 'check-in'
                        conn.commit()
                        socketio.emit('employee_status', {
                            'employee_id': emp[0],
                            'name': emp[1],
                            'action': action,
                            'time': current_time,
                            'date': today
                        })
                        logger.info("Fingerprint scan successful", employee_id=emp[0])
                        return jsonify({'success': True, 'message': f'{emp[1]} {action} successful', 'action': action})
                logger.warning("Fingerprint not recognized")
                return jsonify({'error': 'Fingerprint not recognized'}), 404
            except psycopg.Error as e:
                logger.error("Scan error", error=str(e))
                return jsonify({'error': 'Server error'}), 500

@app.route('/room_status', methods=['GET'])
@jwt_required()
def room_status():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user:
                logger.warning("User not found", username=username)
                return jsonify({'error': 'User not found'}), 404
            has_access, error_response, _ = verify_subscription_feature(username, 'hotel_booking')
            if not has_access:
                return error_response
            try:
                page = int(sanitize_input(request.args.get('page', 1)))
                per_page = int(sanitize_input(request.args.get('per_page', 50)))
                if page < 1 or per_page < 1:
                    raise ValueError("Invalid pagination parameters")
            except ValueError as e:
                logger.warning("Invalid pagination parameters", error=str(e))
                return jsonify({'error': 'Invalid page or per_page parameter'}), 400
            offset = (page - 1) * per_page
            try:
                cursor.execute("SELECT COUNT(*) FROM rooms")
                total_rooms = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT room_id, room_type, status 
                    FROM rooms 
                    ORDER BY room_id 
                    LIMIT %s OFFSET %s
                """, (per_page, offset))
                rooms = [dict(room) for room in cursor.fetchall()]
                response_data = {
                    'success': True,
                    'rooms': rooms,
                    'pagination': {
                        'current_page': page,
                        'per_page': per_page,
                        'total_items': total_rooms,
                        'total_pages': (total_rooms + per_page - 1) // per_page
                    }
                }
                logger.info("Room statuses retrieved", username=username, page=page)
                return jsonify(response_data)
            except psycopg.Error as e:
                logger.error("Room status error", error=str(e), exc_info=True)
                sentry_sdk.capture_exception(e)
                return jsonify({'error': 'Failed to retrieve rooms'}), 500

@app.route('/book_room', methods=['POST'])
@jwt_required()
def book_room():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user:
                logger.warning("User not found", username=username)
                return jsonify({'error': 'User not found'}), 404
            has_access, error_response, _ = verify_subscription_feature(username, 'hotel_booking')
            if not has_access:
                return error_response
            data = request.get_json()
            guest_name = sanitize_input(data.get('guest_name'))
            room_id = sanitize_input(data.get('room_id'))
            check_in_date = sanitize_input(data.get('check_in_date'))
            check_out_date = sanitize_input(data.get('check_out_date'))
            payment_method = sanitize_input(data.get('payment_method'))
            if not all([guest_name, room_id, check_in_date, check_out_date, payment_method]):
                logger.warning("Booking failed: missing fields")
                return jsonify({'error': 'All fields required'}), 400
            if not validate_date(check_in_date) or not validate_date(check_out_date):
                logger.warning("Booking failed: invalid dates")
                return jsonify({'error': 'Invalid date format'}), 400
            try:
                check_in = parse_date(check_in_date).date()
                check_out = parse_date(check_out_date).date()
                if check_in >= check_out or check_in < date.today():
                    logger.warning("Booking failed: invalid date range")
                    return jsonify({'error': 'Invalid date range'}), 400
            except ValueError:
                logger.warning("Booking failed: date parsing error")
                return jsonify({'error': 'Invalid date format'}), 400
            try:
                cursor.execute("SELECT status, room_type FROM rooms WHERE room_id = %s", (room_id,))
                room = cursor.fetchone()
                if not room:
                    logger.warning("Room not found", room_id=room_id)
                    return jsonify({'error': 'Room not found'}), 404
                if room[0] != 'available':
                    logger.warning("Room not available", room_id=room_id)
                    return jsonify({'error': 'Room not available'}), 400
                cursor.execute("""
                    SELECT booking_id FROM bookings
                    WHERE room_id = %s AND status NOT IN ('cancelled', 'checked_out')
                    AND (check_in_date <= %s AND check_out_date >= %s)
                """, (room_id, check_out_date, check_in_date))
                if cursor.fetchone():
                    logger.warning("Room booked for dates", room_id=room_id)
                    return jsonify({'error': 'Room booked for selected dates'}), 400
                guest_id = str(uuid.uuid4())
                encrypted_name = encrypt_guest_name(guest_name)
                nights = (check_out - check_in).days
                amount = ROOM_PRICING[room[1]] * nights
                if payment_method == 'mpesa':
                    phone_number = sanitize_input(data.get('phone_number'))
                    if not phone_number or not re.match(r'^2547\d{8}$', phone_number):
                        logger.warning("M-Pesa booking failed: invalid phone")
                        return jsonify({'error': 'Valid phone number required'}), 400
                    access_token = get_mpesa_access_token()
                    if not access_token:
                        logger.error("Failed to get M-Pesa access token")
                        return jsonify({'error': 'M-Pesa access token error'}), 500
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    password = base64.b64encode(f"{app.config['MPESA_SHORTCODE']}{app.config['MPESA_PASSKEY']}{timestamp}".encode()).decode()
                    base_url = request.host_url or f"http://{os.getenv('APP_HOST', 'localhost')}:5000"
                    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
                    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                    payload = {
                        "BusinessShortCode": app.config['MPESA_SHORTCODE'],
                        "Password": password,
                        "Timestamp": timestamp,
                        "TransactionType": "CustomerPayBillOnline",
                        "Amount": amount,
                        "PartyA": phone_number,
                        "PartyB": app.config['MPESA_SHORTCODE'],
                        "PhoneNumber": phone_number,
                        "CallBackURL": f"{base_url}mpesa/callback",
                        "AccountReference": f"Booking-{guest_id}",
                        "TransactionDesc": f"Room booking for {guest_name}"
                    }
                    response = requests.post(api_url, json=payload, headers=headers, timeout=10)
                    result = response.json()
                    if response.status_code != 200 or result.get('ResponseCode') != '0':
                        logger.error("M-Pesa booking failed", error=result.get('errorMessage'))
                        return jsonify({'error': 'M-Pesa payment failed'}), 500
                cursor.execute("""
                    INSERT INTO bookings (guest_id, guest_name, room_id, check_in_date, check_out_date, payment_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (guest_id, encrypted_name, room_id, check_in_date, check_out_date, 'pending' if payment_method == 'mpesa' else 'completed'))
                cursor.execute("UPDATE rooms SET status = %s WHERE room_id = %s", ('occupied', room_id))
                cursor.execute("""
                    INSERT OR REPLACE INTO guests (guest_id, name, check_in_date, check_out_date, room_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (guest_id, encrypted_name, check_in_date, check_out_date, room_id, 'checked_in'))
                conn.commit()
                socketio.emit('room_status_update', {'room_id': room_id, 'status': 'occupied'})
                logger.info("Room booked", guest_id=guest_id)
                return jsonify({'success': True, 'message': 'Room booked'})
            except psycopg.Error as e:
                logger.error("Booking error", error=str(e))
                return jsonify({'error': 'Failed to book room'}), 500


@app.route('/check_in', methods=['POST'])
@jwt_required()
def check_in():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    employee_id = sanitize_input(data.get('employee_id'))
    name = sanitize_input(data.get('name'))
    if not employee_id or not name:
        return jsonify({'error': 'Missing employee_id or name'}), 400
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO attendance (employee_id, name, date, time_in, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                """, (employee_id, name, nairobi_tz.localize(datetime.now()).date().isoformat(),
                      nairobi_tz.localize(datetime.now()).time().strftime('%H:%M:%S'),
                      nairobi_tz.localize(datetime.now())))
                conn.commit()
                socketio.emit('attendance_update', {
                    'employee_id': employee_id,
                    'name': name,
                    'action': 'check-in',
                    'time_in': nairobi_tz.localize(datetime.now()).time().strftime('%H:%M:%S')
                })
                return jsonify({'success': True, 'message': 'Checked in successfully'})
            except psycopg.Error as e:
                logger.error("Check-in error", error=str(e))
                conn.rollback()
                return jsonify({'error': 'Failed to check in'}), 500
            
@app.route('/check_out', methods=['POST'])
@jwt_required()
def check_out():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    employee_id = sanitize_input(data.get('id'))
    if not employee_id:
        return jsonify({'error': 'Missing employee_id'}), 400
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE attendance 
                    SET time_out = %s 
                    WHERE employee_id = %s AND date = %s AND time_out IS NULL
                """, (nairobi_tz.localize(datetime.now()).time().strftime('%H:%M:%S'),
                      employee_id, nairobi_tz.localize(datetime.now()).date().isoformat()))
                conn.commit()
                socketio.emit('attendance_update', {
                    'employee_id': employee_id,
                    'action': 'check-out',
                    'time_out': nairobi_tz.localize(datetime.now()).time().strftime('%H:%M:%S')
                })
                return jsonify({'success': True, 'message': 'Checked out successfully'})
            except psycopg.Error as e:
                logger.error("Check-out error", error=str(e))
                conn.rollback()
                return jsonify({'error': 'Failed to check out'}), 500

@app.route('/guest_check_in', methods=['POST'])
@jwt_required()
def guest_check_in():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    name = sanitize_input(data.get('name'))
    if not guest_id or not name:
        return jsonify({'error': 'Missing guest_id or name'}), 400
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE guests 
                    SET status = %s, check_in_date = %s 
                    WHERE guest_id = %s
                """, ('checked_in', nairobi_tz.localize(datetime.now()).date().isoformat(), guest_id))
                conn.commit()
                socketio.emit('guest_update', {
                    'guest_id': guest_id,
                    'name': name,
                    'action': 'check-in',
                    'check_in_date': nairobi_tz.localize(datetime.now()).date().isoformat()
                })
                return jsonify({'success': True, 'message': 'Guest checked in successfully'})
            except psycopg.Error as e:
                logger.error("Guest check-in error", error=str(e))
                conn.rollback()
                return jsonify({'error': 'Failed to check in guest'}), 500

@app.route('/guest_check_out', methods=['POST'])
@jwt_required()
def guest_check_out():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    if not guest_id:
        return jsonify({'error': 'Missing guest_id'}), 400
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("""
                    UPDATE guests 
                    SET status = %s, check_out_date = %s 
                    WHERE guest_id = %s
                """, ('checked_out', nairobi_tz.localize(datetime.now()).date().isoformat(), guest_id))
                conn.commit()
                socketio.emit('guest_update', {
                    'guest_id': guest_id,
                    'action': 'check-out',
                    'check_out_date': nairobi_tz.localize(datetime.now()).date().isoformat()
                })
                return jsonify({'success': True, 'message': 'Guest checked out successfully'})
            except psycopg.Error as e:
                logger.error("Guest check-out error", error=str(e))
                conn.rollback()
                return jsonify({'error': 'Failed to check out guest'}), 500

@app.route('/qr_scan', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def qr_scan():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] not in ['admin', 'employee']:
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'qr_verification')
            if not has_access:
                return error_response
            data = request.get_json()
            qr_code = sanitize_input(data.get('qr_code'))
            if not qr_code:
                logger.warning("QR scan failed: no data")
                return jsonify({'error': 'No QR code provided'}), 400
            try:
                cursor.execute("""
                    SELECT user_id, user_type, used, expires_at
                    FROM qr_codes
                    WHERE qr_code = %s AND used = %s AND expires_at > %s
                """, (qr_code, False, datetime.datetime.now(nairobi_tz)))
                qr_data = cursor.fetchone()
                if not qr_data:
                    logger.warning("QR scan failed: invalid or expired")
                    return jsonify({'error': 'Invalid or expired QR code'}), 404
                user_id, user_type, _, _ = qr_data
                cursor.execute("UPDATE qr_codes SET used = %s WHERE qr_code = %s", (True, qr_code))
                if user_type == 'employee':
                    cursor.execute("SELECT name FROM employees WHERE employee_id = %s AND organization_id = %s", (user_id, username))
                    emp = cursor.fetchone()
                    if not emp:
                        logger.warning("Employee not found", employee_id=user_id)
                        return jsonify({'error': 'Employee not found'}), 404
                    today = nairobi_tz.localize(datetime.now()).date().isoformat()
                    current_time = nairobi_tz.localize(datetime.now()).strftime('%H:%M:%S')
                    cursor.execute("SELECT time_in, time_out FROM attendance WHERE employee_id = %s AND date = %s", (user_id, today))
                    record = cursor.fetchone()
                    if record and not record[1]:
                        cursor.execute("""
                            UPDATE attendance
                            SET time_out = %s, timestamp = %s
                            WHERE employee_id = %s AND date = %s
                        """, (current_time, nairobi_tz.localize(datetime.now()).isoformat(), user_id, today))
                        action = 'check-out'
                    else:
                        cursor.execute("""
                            INSERT INTO attendance (employee_id, name, date, time_in, timestamp)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (user_id, emp[0], today, current_time, nairobi_tz.localize(datetime.now()).isoformat()))
                        action = 'check-in'
                    conn.commit()
                    socketio.emit('employee_status', {
                        'employee_id': user_id,
                        'name': emp[0],
                        'action': action,
                        'time': current_time,
                        'date': today
                    })
                    logger.info("QR scan successful", employee_id=user_id, action=action)
                    return jsonify({'success': True, 'message': f'{emp[0]} {action} successful', 'action': action})
                elif user_type == 'guest':
                    cursor.execute("SELECT name, room_id, status FROM guests WHERE guest_id = %s", (user_id,))
                    guest = cursor.fetchone()
                    if not guest:
                        logger.warning("Guest not found", guest_id=user_id)
                        return jsonify({'error': 'Guest not found'}), 404
                    if guest[2] == 'checked_in':
                        logger.warning("Guest already checked in")
                        return jsonify({'error': 'Guest already checked in'}), 400
                    current_date = nairobi_tz.localize(datetime.now()).date().isoformat()
                    cursor.execute("UPDATE guests SET status = %s, check_in_date = %s WHERE guest_id = %s", ('checked_in', current_date, user_id))
                    cursor.execute("UPDATE bookings SET status = %s WHERE guest_id = %s", ('checked_in', user_id))
                    conn.commit()
                    socketio.emit('guest_status_update', {
                        'guest_id': user_id,
                        'name': decrypt_guest_name(guest[0]),
                        'action': 'check-in',
                        'date': current_date
                    })
                    logger.info("QR scan successful", guest_id=user_id, action='check-in')
                    return jsonify({'success': True, 'message': 'Guest check-in successful'})
                else:
                    logger.warning("Invalid QR user type", user_type=user_type)
                    return jsonify({'error': 'Invalid QR code type'}), 400
            except psycopg.Error as e:
                logger.error("QR scan error", error=str(e), exc_info=True)
                sentry_sdk.capture_exception(e)
                conn.rollback()
                return jsonify({'error': 'Server error'}), 500

@app.route('/generate_qr', methods=['POST'])
@jwt_required()
@limiter.limit("5 per minute")
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def generate_qr():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] != 'admin':
                logger.warning("Access denied", username=username)
                return jsonify({'error': 'Access denied'}), 403
            has_access, error_response, _ = verify_subscription_feature(username, 'qr_verification')
            if not has_access:
                return error_response
            data = request.get_json()
            user_id = sanitize_input(data.get('user_id'))
            user_type = sanitize_input(data.get('user_type'))
            if user_type not in ['employee', 'guest']:
                logger.warning("Invalid user type", user_type=user_type)
                return jsonify({'error': 'Invalid user type'}), 400
            if not user_id:
                logger.warning("QR generation failed: no user ID")
                return jsonify({'error': 'User ID required'}), 400
            try:
                if user_type == 'employee':
                    cursor.execute("SELECT employee_id FROM employees WHERE employee_id = %s AND organization_id = %s", (user_id, username))
                    if not cursor.fetchone():
                        logger.warning("Employee not found", employee_id=user_id)
                        return jsonify({'error': 'Employee not found'}), 404
                elif user_type == 'guest':
                    cursor.execute("SELECT guest_id FROM guests WHERE guest_id = %s", (user_id,))
                    if not cursor.fetchone():
                        logger.warning("Guest not found", guest_id=user_id)
                        return jsonify({'error': 'Guest not found'}), 404
                qr_code = str(uuid.uuid4())
                expires_at = nairobi_tz.localize(datetime.now()) + timedelta(hours=24)
                cursor.execute("""
                    INSERT INTO qr_codes (qr_code, user_id, user_type, expires_at)
                    VALUES (%s, %s, %s, %s)
                """, (qr_code, user_id, user_type, expires_at))
                conn.commit()
                logger.info("QR code generated", user_id=user_id, user_type=user_type)
                return jsonify({'success': True, 'qr_code': qr_code, 'expires_at': expires_at.isoformat()})
            except psycopg.Error as e:
                logger.error("QR generation error", error=str(e), exc_info=True)
                sentry_sdk.capture_exception(e)
                conn.rollback()
                return jsonify({'error': 'Server error'}), 500
            
@app.route('/completed/success')
@jwt_required()
def payment_success():
    username = sanitize_input(get_jwt_identity())
    transaction_id = sanitize_input(request.args.get('transaction_id'))
    plan = sanitize_input(request.args.get('plan'))
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("SELECT status FROM transactions WHERE transaction_id = %s", (transaction_id,))
                transaction = cursor.fetchone()
                if not transaction or transaction[0] == 'completed':
                    flash('Invalid or already processed transaction.', 'danger')
                    logger.warning("Invalid transaction", transaction_id=transaction_id)
                    return render_template('error.html', message='Invalid or already processed transaction.', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)
                cursor.execute("UPDATE transactions SET status = %s WHERE transaction_id = %s",
                              ('completed', transaction_id))
                cursor.execute("UPDATE subscriptions SET plan = %s, employee_limit = %s, start_date = %s, end_date = %s WHERE organization_id = %s",
                              (plan, SUBSCRIPTION_TIERS[plan]['employee_limit'], date.today().isoformat(), (nairobi_tz.localize(datetime.now()) + timedelta(days=app.config['SUBSCRIPTION_DURATION_DAYS'])).strftime('%Y-%m-%d'), username))
                conn.commit()
                flash(f'Subscription upgraded to {plan} successfully.', 'success')
                logger.info("Payment success", username=username)
                return render_template('success.html', message=f'Subscription upgraded to {plan} successfully.', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)
            except psycopg.Error as e:
                logger.error("Payment success processing error", error=str(e))
                sentry_sdk.capture_exception(e)
                flash('Error processing payment status.', 'danger')
                return render_template('error.html', message='Error processing payment status.', config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)

@socketio.on('subscribe_room_updates')
@socketio_limit("1 per second")
def subscribe_room_updates():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] not in ['admin', 'employee']:
                logger.warning("SocketIO access denied", username=username)
                emit('error', {'error': 'Access denied'})
                return
            has_access, error_response, _ = verify_subscription_feature(username, 'hotel_booking')
            if not has_access:
                emit('error', {'error': 'Feature not available'})
                return
            logger.info("Subscribed to room updates", client_id=request.sid)
            emit('subscription_status', {'success': True, 'message': 'Subscribed to room updates'})

@socketio.on('subscribe_employee_updates')
@socketio_limit("1 per second")
def subscribe_employee_updates():
    username = sanitize_input(get_jwt_identity())
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if not user or user[0] not in ['admin', 'employee']:
                logger.warning("SocketIO access denied", username=username)
                emit('error', {'error': 'Access denied'})
                return
            has_access, error_response, _ = verify_subscription_feature(username, 'employee_management')
            if not has_access:
                emit('error', {'error': 'Feature not available'})
                return
            logger.info("Subscribed to employee updates", client_id=request.sid)
            emit('subscription_status', {'success': True, 'message': 'Subscribed to employee updates'})

@socketio.on('connect')
def handle_connect(auth):
    if not auth or not verify_jwt_in_socketio(auth.get('token')):
        logger.warning("SocketIO connection denied: invalid JWT")
        disconnect()
        return
    logger.info("SocketIO client connected", client_id=request.sid)
    emit('connection_status', {'success': True, 'message': 'Connected'})
        
@app.route('/completed/canceled')
@jwt_required()
def payment_cancel():
    username = get_jwt_identity()
    error_message = request.args.get('error', 'Payment was canceled.')
    flash(error_message, 'info')
    return render_template('error.html', message=error_message, config=app.config, hasLoggedIn=True, username=username, userRole='admin', current_year=datetime.now().year, datetime=datetime)

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db:
        db.close()
        logger.info("Database connection closed")

# Graceful shutdown handler
def shutdown_handler():
    logger.info("Shutting down application")
    if 'db' in g:
        g.db.close()
    logger.info("Shutdown complete")
    
if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)