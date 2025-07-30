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

# Set Nairobi timezone
nairobi_tz = pytz.timezone('Africa/Nairobi')

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
    return cipher.encrypt(data)  # Return bytes

def decrypt_data(encrypted_data):
    global cipher
    if not cipher:
        cipher = get_cipher()
    try:
        # Handle memoryview objects from BYTEA columns
        if isinstance(encrypted_data, memoryview):
            encrypted_data = encrypted_data.tobytes()
        elif not isinstance(encrypted_data, bytes):
            encrypted_data = encrypted_data.encode()
        decrypted = cipher.decrypt(encrypted_data)
        return decrypted.decode('utf-8')
    except (base64.binascii.Error, ValueError):
        return None

def allowed_file(filename, file_stream):
    """Check if the file is an allowed image type based on extension and MIME."""
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
    """Validate email address with detailed error handling."""
    try:
      validation = validate_email_base(email)  
      return validation.email
    except EmailNotValidError as e:
        return False

def validate_date(date_str):
    """Validate date string with flexible parsing."""
    try:
        parsed_date = parse_date(date_str, fuzzy=True)
        return parsed_date
    except ValueError:
        return None

def sanitize_input(value):
    """Sanitize input to prevent XSS and basic injection with enhanced filtering."""
    if not value or not isinstance(value, str):
        return ""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', value.strip())
    return sanitized[:255]  # Limit length to prevent overflow

def match_fingerprint(scan_data, stored_hash):
    """Match fingerprint scan data against stored hash."""
    try:
        scan_hash = hashlib.sha256(scan_data.encode('utf-8')).hexdigest()
        return scan_hash == stored_hash
    except (AttributeError, UnicodeEncodeError):
        return False

def get_current_time():
    """Get the current time in Nairobi timezone."""
    return nairobi_tz.localize(datetime.now())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def get_mpesa_access_token():
    """Fetch M-Pesa access token with retry logic."""
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (os.getenv('MPESA_CONSUMER_KEY'), os.getenv('MPESA_CONSUMER_SECRET'))
    try:
        response = requests.get(api_url, auth=auth, timeout=10, verify=True)
        response.raise_for_status()
        return response.json().get('access_token')
    except requests.RequestException as e:
        return None

def validate_mpesa_signature(data):
    """Validate M-Pesa signature (placeholder implementation)."""
    # Implement actual signature validation using M-Pesa docs
    # This is a placeholder; replace with real logic using MPESA_PASSKEY
    return True  # Temporary return

def secure_filename_with_hash(filename):
    """Generate a secure filename with a hash to prevent collisions."""
    secure_name = secure_filename(filename)
    name, ext = os.path.splitext(secure_name)
    hash_suffix = hashlib.md5(filename.encode()).hexdigest()[:8]
    return f"{name}_{hash_suffix}{ext}"