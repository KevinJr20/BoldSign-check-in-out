import os
import re
import hashlib
import base64
import magic
from cryptography.fernet import Fernet
from email_validator import validate_email
from dateutil.parser import parse as parse_date
from werkzeug.utils import secure_filename
import pytz
from tenacity import retry, stop_after_attempt, wait_exponential
import requests

nairobi_tz = pytz.timezone('Africa/Nairobi')
cipher = Fernet(os.getenv('ENCRYPTION_KEY').encode())

def allowed_file(filename, file_stream):
    if not '.' in filename or filename.rsplit('.', 1)[1].lower() not in {'png', 'jpg', 'jpeg'}:
        return False
    mime = magic.Magic(mime=True)
    file_stream.seek(0)
    file_mime = mime.from_buffer(file_stream.read(2048))
    file_stream.seek(0)
    return file_mime in ['image/png', 'image/jpeg']

def validate_email(email):
    try:
        validate_email(email)
        return True
    except Exception:
        return False

def validate_date(date_str):
    try:
        parse_date(date_str)
        return True
    except ValueError:
        return False

def encrypt_guest_name(name):
    return cipher.encrypt(name.encode()).decode()

def decrypt_guest_name(encrypted_name):
    try:
        return cipher.decrypt(encrypted_name.encode()).decode()
    except Exception:
        return "Unknown"

def sanitize_input(value):
    if isinstance(value, str):
        return re.sub(r'[^\w\s-]', '', value.strip())
    return value

def match_fingerprint(scan_data, stored_hash):
    try:
        scan_hash = hashlib.sha256(scan_data.encode()).hexdigest()
        return scan_hash == stored_hash
    except Exception:
        return False

def get_current_time():
    return nairobi_tz.localize(datetime.now())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def get_mpesa_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (os.getenv('MPESA_CONSUMER_KEY'), os.getenv('MPESA_CONSUMER_SECRET'))
    try:
        response = requests.get(api_url, auth=auth, timeout=10)
        response.raise_for_status()
        return response.json().get('access_token')
    except requests.RequestException:
        return None

def validate_mpesa_signature(data):
    return True  # Placeholder; implement actual signature validation