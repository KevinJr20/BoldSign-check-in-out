from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from ..db import db  # Import db from db.py
from datetime import datetime

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    username = db.Column(db.Text, primary_key=True)
    email = db.Column(db.Text, nullable=False)
    name = db.Column(db.Text)
    password_hash = db.Column(db.LargeBinary)
    organization_type = db.Column(db.Text, nullable=True)
    role = db.Column(db.Text, server_default='admin', nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    webauthn_credential_id = db.Column(db.LargeBinary, nullable=True)
    webauthn_public_key = db.Column(db.LargeBinary, nullable=True)
    __table_args__ = (db.Index('idx_users_username', 'username'),)

    def is_active(self):
        """Return True if the user is active."""
        return True

    def get_id(self):
        """Return the username as the ID."""
        return str(self.username)

class VerificationToken(db.Model):
    __tablename__ = 'verification_tokens'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('users.username'), nullable=False)
    token = db.Column(db.String(36), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    __table_args__ = (db.Index('idx_verification_tokens_user_id', 'user_id'),)
    user = db.relationship('User', backref='verification_tokens')

class Employee(db.Model):
    __tablename__ = 'employees'
    employee_id = db.Column(db.Text, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text)
    role = db.Column(db.Text)
    organization_id = db.Column(db.Text, db.ForeignKey('users.username'), nullable=False)
    fingerprint_template = db.Column(db.Text)
    biometric_hash = db.Column(db.String(64), nullable=True)
    photo_url = db.Column(db.Text)
    __table_args__ = (db.Index('idx_employees_organization_id', 'organization_id'),)

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String, db.ForeignKey('employees.employee_id', ondelete='SET NULL'), nullable=True)
    user_id = db.Column(db.String, db.ForeignKey('users.username', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    from ..utils import get_current_time  # Local import
    timestamp = db.Column(db.DateTime, default=get_current_time)  # Use get_current_time here

    def __init__(self, employee_id=None, user_id=None, action=None):
        self.employee_id = employee_id
        self.user_id = user_id
        self.action = action

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Text, db.ForeignKey('employees.employee_id'), nullable=False)
    name = db.Column(db.Text)
    date = db.Column(db.DateTime, nullable=True)
    time_in = db.Column(db.DateTime, nullable=True)
    time_out = db.Column(db.DateTime, nullable=True)
    organization_id = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=True)
    __table_args__ = (db.Index('idx_attendance_employee_id', 'employee_id'),)

class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    organization_id = db.Column(db.Text, db.ForeignKey('users.username'), primary_key=True)
    plan = db.Column(db.Text, nullable=False)
    employee_limit = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    __table_args__ = (db.Index('idx_subscriptions_organization_id', 'organization_id'),)

class Room(db.Model):
    __tablename__ = 'rooms'
    room_id = db.Column(db.Text, primary_key=True)
    room_type = db.Column(db.Text, nullable=False)
    status = db.Column(db.Text, server_default='available', nullable=False)
    __table_args__ = (db.Index('idx_rooms_room_id', 'room_id'),)

class Booking(db.Model):
    __tablename__ = 'bookings'
    booking_id = db.Column(db.Integer, primary_key=True)
    guest_id = db.Column(db.Text)
    guest_name = db.Column(db.Text, nullable=False)
    room_id = db.Column(db.Text, db.ForeignKey('rooms.room_id'), nullable=True)
    check_in_date = db.Column(db.DateTime, nullable=False)
    check_out_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.Text, server_default='pending', nullable=False)
    payment_status = db.Column(db.Text, server_default='pending', nullable=False)
    __table_args__ = (db.Index('idx_bookings_room_id', 'room_id'),)

class Guest(db.Model, UserMixin):
    __tablename__ = 'guests'
    guest_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.Text, nullable=False)
    check_in_date = db.Column(db.DateTime, nullable=True)
    check_out_date = db.Column(db.DateTime, nullable=True)
    room_id = db.Column(db.Text, db.ForeignKey('rooms.room_id'), nullable=True)
    status = db.Column(db.Text, server_default='completed', nullable=False)
    password_hash = db.Column(db.Text, nullable=True)
    __table_args__ = (db.Index('idx_guests_room_id', 'room_id'),)

    def is_active(self):
        """Return True if the guest is active."""
        return True

    def get_id(self):
        """Return the guest_id as the ID."""
        return str(self.guest_id)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    transaction_id = db.Column(db.Text, primary_key=True)
    username = db.Column(db.Text, db.ForeignKey('users.username'), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    plan = db.Column(db.Text)
    payment_method = db.Column(db.Text)
    status = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    __table_args__ = (db.Index('idx_transactions_username', 'username'),)

class Configuration(db.Model):
    __tablename__ = 'configurations'
    config_key = db.Column(db.Text, primary_key=True)
    config_value = db.Column(db.Text, nullable=False)
    __table_args__ = (db.Index('idx_configurations_config_key', 'config_key'),)

class QrCode(db.Model):
    __tablename__ = 'qr_codes'
    id = db.Column(db.Integer, primary_key=True)
    qr_code = db.Column(db.Text, unique=True, nullable=False)
    user_id = db.Column(db.Text, nullable=False)
    user_type = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    __table_args__ = (
        db.Index('idx_qr_codes_qr_code', 'qr_code', unique=True),
    )