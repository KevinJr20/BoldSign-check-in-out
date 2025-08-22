import os
import re
import hashlib
import base64
from cryptography.fernet import Fernet
from email_validator import validate_email as validate_email_base, EmailNotValidError
from dateutil.parser import parse as parse_date
from werkzeug.utils import secure_filename
import magic
import pytz
from tenacity import retry, stop_after_attempt, wait_exponential
import requests
from datetime import datetime
import logging

# Set Nairobi timezone
nairobi_tz = pytz.timezone('Africa/Nairobi')

# Configure logging
logger = logging.getLogger(__name__)

# Function to get or initialize the cipher
def get_cipher():
    encryption_key = os.getenv("ENCRYPTION_KEY")
    if not encryption_key:
        raise ValueError("ENCRYPTION_KEY not set in environment")
    return Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

# Initialize cipher lazily
cipher = None

def encrypt_data(data):
    global cipher
    if not cipher:
        cipher = get_cipher()
    if not isinstance(data, bytes):
        data = str(data).encode()
    return cipher.encrypt(data)

def decrypt_data(encrypted_data):
    global cipher
    if not cipher:
        cipher = get_cipher()
    try:
        if isinstance(encrypted_data, memoryview):
            encrypted_data = encrypted_data.tobytes()
        elif not isinstance(encrypted_data, bytes):
            encrypted_data = encrypted_data.encode()
        decrypted = cipher.decrypt(encrypted_data)
        return decrypted.decode('utf-8')
    except (base64.binascii.Error, ValueError):
        return None

def allowed_file(filename, file_stream):
    if not filename or '.' not in filename:
        return False
    allowed_extensions = {'png', 'jpg', 'jpeg'}
    if filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return False
    mime = magic.Magic(mime=True)
    file_stream.seek(0)
    file_mime = mime.from_buffer(file_stream.read(2048))
    file_stream.seek(0)
    return file_mime in ['image/png', 'image/jpeg']

def validate_email(email):
    try:
        validation = validate_email_base(email)
        return validation.email
    except EmailNotValidError as e:
        return False

def validate_date(date_str):
    try:
        parsed_date = parse_date(date_str, fuzzy=True)
        return parsed_date
    except ValueError:
        return None

def sanitize_input(value):
    if not value or not isinstance(value, str):
        return ""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', value.strip())
    return sanitized[:255]

def match_fingerprint(scan_data, stored_hash):
    try:
        scan_hash = hashlib.sha256(scan_data.encode('utf-8')).hexdigest()
        return scan_hash == stored_hash
    except (AttributeError, UnicodeEncodeError):
        return False

def get_current_time():
    return nairobi_tz.localize(datetime.now())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def get_mpesa_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (os.getenv('MPESA_CONSUMER_KEY'), os.getenv('MPESA_CONSUMER_SECRET'))
    try:
        response = requests.get(api_url, auth=auth, timeout=10, verify=True)
        response.raise_for_status()
        return response.json().get('access_token')
    except requests.RequestException as e:
        return None

def validate_mpesa_signature(data):
    return True  # Placeholder

def secure_filename_with_hash(filename):
    secure_name = secure_filename(filename)
    name, ext = os.path.splitext(secure_name)
    hash_suffix = hashlib.md5(filename.encode()).hexdigest()[:8]
    return f"{name}_{hash_suffix}{ext}"

def log_audit(user_id, action):
    try:
        from .models import db, AuditLog  # Deferred import to avoid circular dependency
        audit = AuditLog(
            employee_id=user_id if user_id and isinstance(user_id, str) and len(user_id) <= 50 else None,
            user_id=user_id,
            action=action,
            timestamp=get_current_time()
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to log audit for {user_id}: {str(e)}", exc_info=True)