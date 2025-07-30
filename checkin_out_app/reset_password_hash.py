import os
from dotenv import load_dotenv
from passlib.hash import bcrypt
from utils import encrypt_data

# Load .env with explicit path
env_path = "C:/Users/KevinOchiengOmondi/Desktop/BOSGN Check In-Out/Python/boldsign-checkinout-demo/.env"
load_dotenv(env_path)

password = "Admin123!"
password_hash = encrypt_data(bcrypt.hash(password))  # Returns bytes
print(password_hash.hex())  # Convert bytes to hex string