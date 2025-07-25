import os
import json
from datetime import timedelta
from dotenv import load_dotenv
import structlog
from cryptography.fernet import Fernet
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

load_dotenv()

def configure_app(app):
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.stdlib.add_log_level, structlog.processors.JSONRenderer()],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()

    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '').strip()
    if not ENCRYPTION_KEY:
        ENCRYPTION_KEY = Fernet.generate_key().decode()
        with open('.env', 'a') as f:
            f.write(f"\nENCRYPTION_KEY={ENCRYPTION_KEY}")
        logger.info("Generated new encryption key")
    else:
        try:
            Fernet(ENCRYPTION_KEY.encode())
            logger.info("Encryption key validated")
        except ValueError as e:
            logger.error("Invalid encryption key", error=str(e))
            raise ValueError("Invalid ENCRYPTION_KEY format")

    required_env_vars = ['STRIPE_SECRET_KEY', 'STRIPE_PUBLISHABLE_KEY', 'PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET',
                        'MPESA_CONSUMER_KEY', 'MPESA_CONSUMER_SECRET', 'MPESA_SHORTCODE', 'MPESA_PASSKEY', 'SECRET_KEY',
                        'DATABASE_URL']
    for var in required_env_vars:
        if not os.getenv(var):
            logger.error("Missing environment variable", variable=var)
            raise EnvironmentError(f"Environment variable {var} required")

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
    app.config['JWT_COOKIE_CSRF_PROTECT'] = os.getenv('FLASK_ENV') != 'development'
    app.config['JWT_COOKIE_SECURE'] = os.getenv('FLASK_ENV') != 'development'
    app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
    app.config['JWT_COOKIE_SAMESITE'] = 'Lax'
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=12)
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['STRIPE_PUBLISHABLE_KEY'] = os.getenv('STRIPE_PUBLISHABLE_KEY')
    app.config['MPESA_CONSUMER_KEY'] = os.getenv('MPESA_CONSUMER_KEY')
    app.config['MPESA_CONSUMER_SECRET'] = os.getenv('MPESA_CONSUMER_SECRET')
    app.config['MPESA_SHORTCODE'] = os.getenv('MPESA_SHORTCODE')
    app.config['MPESA_PASSKEY'] = os.getenv('MPESA_PASSKEY')
    app.config['DATABASE_URL'] = os.getenv('DATABASE_URL')
    # app.config['REDIS_URL'] = os.getenv('REDIS_URL')
    # app.config['SENTRY_DSN'] = os.getenv('SENTRY_DSN')
    app.config['SUBSCRIPTION_DURATION_DAYS'] = int(os.getenv('SUBSCRIPTION_DURATION_DAYS', 30))
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'your-email@gmail.com')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'your-app-password')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}
    app.config['MAX_FILE_SIZE'] = 5 * 1024 * 1024
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # if app.config['SENTRY_DSN']:
    #     sentry_sdk.init(
    #         dsn=app.config['SENTRY_DSN'],
    #         integrations=[FlaskIntegration()],
    #         traces_sample_rate=0.1
    #     )
    #     logger.info("Sentry initialized")

    try:
        with open('config.json', 'r') as config_file:
            app.config.update(json.load(config_file))
    except FileNotFoundError:
        logger.error("Config file not found")
        raise

    app.config['ORGANIZATION_TYPES'] = {
        'hotel': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management', 'qr_verification'], 'default_plan': 'pro'},
        'school': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations'], 'default_plan': 'pro'},
        'retail': {'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'bulk_operations', 'analytics'], 'default_plan': 'pro'}
    }
    app.config['SUBSCRIPTION_TIERS'] = {
        'free': {'price': 0, 'employee_limit': 10, 'features': ['dashboard', 'attendance', 'employee_management'], 'duration_days': 30},
        'starter': {'price': 25, 'employee_limit': 50, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'hotel_booking', 'guest_management'], 'duration_days': 30},
        'pro': {'price': 35, 'employee_limit': 500, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management', 'qr_verification'], 'duration_days': 30},
        'enterprise': {'price': 99, 'employee_limit': 10000, 'features': ['dashboard', 'attendance', 'employee_management', 'csv_export', 'analytics', 'bulk_operations', 'hotel_booking', 'guest_management', 'qr_verification', 'custom'], 'duration_days': 30}
    }
    app.config['ROOM_PRICING'] = {'standard': 50, 'deluxe': 80, 'suite': 150}