import os
import qrcode
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response, current_app
from flask_login import login_user, logout_user, login_required, current_user
from passlib.hash import bcrypt
from uuid import uuid4
from flask_wtf import FlaskForm
from datetime import datetime, timedelta
from webauthn import generate_authentication_options, verify_authentication_response, generate_registration_options, verify_registration_response
from ..db import db
from ..models import User, VerificationToken, Guest, Subscription, QrCode, Employee, AuditLog, Room, Booking
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email
from ..utils import sanitize_input, validate_email, get_current_time, encrypt_data, decrypt_data
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail, Message
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
csrf = CSRFProtect()
mail = Mail()

def log_audit(user_id, action):
    """Logs an audit event to the AuditLog table."""
    try:
        audit = AuditLog(
            employee_id=user_id if user_id and isinstance(user_id, str) and len(user_id) <= 50 else None,
            user_id=user_id,
            action=action
        )
        db.session.add(audit)
        db.session.commit()
        logger.debug(f"Audit log created for {user_id}: {action}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to log audit for {user_id}: {str(e)}", exc_info=True)
        
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        user = User.query.filter_by(email=email).first()
        if user:
            try:
                # Try decrypting password_hash (Fernet)
                decrypted_hash = decrypt_data(user.password_hash)
                if decrypted_hash and password == decrypted_hash:  # Plaintext comparison
                    login_user(user)
                    logger.info(f"User {email} logged in at {get_current_time()}")
                    log_audit(user.username, 'Login as admin')
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('dashboard.dashboard'))
            except (ValueError, TypeError, cryptography.fernet.InvalidToken):
                # Fall back to bcrypt if Fernet fails
                if user.password_hash and bcrypt.verify(password, user.password_hash.decode('utf-8') if isinstance(user.password_hash, bytes) else user.password_hash):
                    login_user(user)
                    logger.info(f"User {email} logged in at {get_current_time()}")
                    log_audit(user.username, 'Login as admin')
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('dashboard.dashboard'))
            flash('Invalid email or password', 'danger')
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html', form=form, config=current_app.config, current_year=datetime.now().year)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username'))
        email = sanitize_input(request.form.get('email'))
        password = request.form.get('password')
        role = sanitize_input(request.form.get('role'))
        logger.debug(f"Registration attempt: username={username}, email={email}, role={role}")
        if not all([username, email, password, role]):
            flash('All fields are required.', 'danger')
            return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])
        if not validate_email(email) or role not in ['admin', 'employee', 'guest']:
            flash('Invalid email or role.', 'danger')
            return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])
        if len(password) < 8 or not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
            flash('Password must be at least 8 characters with uppercase, lowercase, and a number.', 'danger')
            return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])
        with db.session() as session:
            try:
                if session.query(User).filter_by(username=username).first() or session.query(User).filter_by(email=email).first():
                    flash('Username or email already exists.', 'danger')
                    return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])
                try:
                    password_hash = encrypt_data(bcrypt.hash(password))
                    logger.debug(f"Encrypted password hash: {password_hash[:10]}...")  # Partial for security
                except ValueError as e:
                    logger.error(f"Encryption error for {username}: {str(e)}")
                    flash('Encryption key issue. Contact support.', 'danger')
                    return redirect(url_for('auth.register'))
                if role == 'admin':
                    organization_type = request.form.get('organization_type')
                    if not organization_type or organization_type not in current_app.config['ORGANIZATION_TYPES']:
                        flash('Invalid organization type.', 'danger')
                        return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])
                    default_plan = current_app.config['ORGANIZATION_TYPES'][organization_type]['default_plan']
                    employee_limit = current_app.config['SUBSCRIPTION_TIERS'][default_plan]['employee_limit']
                    subscription = Subscription(organization_id=username, plan=default_plan, employee_limit=employee_limit, start_date=get_current_time(), end_date=get_current_time() + timedelta(days=current_app.config['SUBSCRIPTION_DURATION_DAYS']))
                    session.add(subscription)
                new_user = User(username=username, email=email, password_hash=password_hash, role=role, organization_type=role=='admin' and organization_type or None, is_verified=False)
                session.add(new_user)
                token = VerificationToken(user_id=username, token=str(uuid4()), expires_at=get_current_time() + timedelta(days=1))
                session.add(token)
                session.commit()
                send_verification_email(email, token.token)
                logger.info(f"Registration successful for {username} as {role}")
                flash('Registration successful! Please check your email to verify.', 'success')
                return redirect(url_for('auth.login'))
            except Exception as e:
                session.rollback()
                flash('An error occurred during registration. Please try again.', 'danger')
                logger.error(f"Registration error for {username}: {str(e)}", exc_info=True)
                return redirect(url_for('auth.login'))
        return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])
    return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year, roles=['admin', 'employee', 'guest'])

@auth_bp.route('/verify_email/<token>', methods=['GET'])
def verify_email(token):
    with db.session() as session:
        verification_token = session.query(VerificationToken).filter_by(token=token).first()
        logger.debug(f"Verification token query: {verification_token}")
        if verification_token and verification_token.expires_at > get_current_time():
            user = session.query(User).filter_by(username=verification_token.user_id).first()
            if user:
                user.is_verified = True
                session.delete(verification_token)
                session.commit()
                logger.info(f"Email verified for {user.username}")
                flash('Email verified successfully. You can now log in.', 'success')
                return redirect(url_for('auth.login'))
            logger.debug(f"User not found for token {token}")
            flash('User not found.', 'danger')
        else:
            logger.debug(f"Token {token} expired or invalid")
            flash('Verification token expired or invalid.', 'danger')
    return redirect(url_for('auth.login'))

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html', config=current_app.config, current_year=datetime.now().year)
    elif request.method == 'POST':
        email_or_username = sanitize_input(request.form.get('email_or_username'))
        logger.debug(f"Forgot password request for: {email_or_username}")
        if not email_or_username:
            flash('Email or username is required.', 'danger')
            return render_template('forgot_password.html', config=current_app.config, current_year=datetime.now().year)
        with db.session() as session:
            try:
                user = session.query(User).filter_by(username=email_or_username).first()
                if not user:
                    user = session.query(User).filter_by(email=email_or_username).first()
                if user:
                    token = str(uuid4())
                    expires_at = get_current_time() + timedelta(hours=1)
                    verification_token = VerificationToken(user_id=user.username, token=token, expires_at=expires_at)
                    session.add(verification_token)
                    session.commit()
                    send_reset_email(user.email, token)
                    logger.info(f"Password reset token generated for {user.username}")
                    flash('A password reset link has been sent to your email.', 'success')
                else:
                    logger.debug(f"No user found for {email_or_username}")
                    flash('No account found with that email or username.', 'danger')
            except Exception as e:
                session.rollback()
                flash('An error occurred. Please try again.', 'danger')
                logger.error(f"Forgot password error for {email_or_username}: {str(e)}", exc_info=True)
        return render_template('forgot_password.html', config=current_app.config, current_year=datetime.now().year)

@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    with db.session() as session:
        verification_token = session.query(VerificationToken).filter_by(token=token).first()
        logger.debug(f"Reset token query: {verification_token}")
        if not verification_token or verification_token.expires_at < get_current_time():
            flash('Invalid or expired reset token.', 'danger')
            return redirect(url_for('auth.login'))
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            if len(new_password) < 8 or not any(c.isupper() for c in new_password) or not any(c.islower() for c in new_password) or not any(c.isdigit() for c in new_password):
                flash('Password must be at least 8 characters with uppercase, lowercase, and a number.', 'danger')
                return render_template('reset_password.html', token=token)
            user = session.query(User).filter_by(username=verification_token.user_id).first()
            if user:
                try:
                    user.password_hash = encrypt_data(bcrypt.hash(new_password))
                    session.delete(verification_token)
                    session.commit()
                    logger.info(f"Password reset successful for {user.username}")
                    flash('Password reset successful. You can now log in.', 'success')
                except ValueError as e:
                    session.rollback()
                    logger.error(f"Encryption error during reset for {user.username}: {str(e)}")
                    flash('Encryption key issue. Contact support.', 'danger')
                    return redirect(url_for('auth.login'))
                return redirect(url_for('auth.login'))
            flash('User not found.', 'danger')
            return redirect(url_for('auth.login'))
        return render_template('reset_password.html', token=token)

@auth_bp.route('/change_credentials', methods=['GET', 'POST'])
@login_required
def change_credentials():
    if current_user.role not in ['admin', 'employee']:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_username = sanitize_input(request.form.get('new_username'))
        new_password = request.form.get('new_password')
        logger.debug(f"Credential change attempt for {current_user.username}: new_username={new_username}")
        if not all([current_password, new_username, new_password]):
            flash('All fields are required.', 'danger')
            return render_template('change_credentials.html')
        if len(new_password) < 8 or not any(c.isupper() for c in new_password) or not any(c.islower() for c in new_password) or not any(c.isdigit() for c in new_password):
            flash('New password must be at least 8 characters with uppercase, lowercase, and a number.', 'danger')
            return render_template('change_credentials.html')
        with db.session() as session:
            try:
                user = session.query(User).filter_by(username=current_user.username).first()
                if user and bcrypt.verify(current_password, decrypt_data(user.password_hash)):
                    if session.query(User).filter_by(username=new_username).first() and new_username != current_user.username:
                        flash('Username already exists.', 'danger')
                        return render_template('change_credentials.html')
                    user.username = new_username
                    user.password_hash = encrypt_data(bcrypt.hash(new_password))
                    session.commit()
                    log_audit(user.username, "Credentials updated")
                    flash('Credentials updated successfully.', 'success')
                    return redirect(url_for('dashboard.dashboard'))
                flash('Current password incorrect.', 'danger')
                log_audit(user.username if user else None, "Failed credential update attempt")
            except Exception as e:
                session.rollback()
                flash('An error occurred. Please try again.', 'danger')
                logger.error(f"Credential update error for {current_user.username}: {str(e)}", exc_info=True)
        return render_template('change_credentials.html')
    return render_template('change_credentials.html')

@auth_bp.route('/biometric_register/start', methods=['GET'])
@login_required
def biometric_register_start():
    if current_user.role not in ['admin', 'employee']:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    options = generate_registration_options(
        rp_id=current_app.config['WEBAUTHN_RP_ID'],
        rp_name=current_app.config['company_name'] or 'Hospitality',
        user_id=current_user.username,
        user_name=current_user.username,
        challenge=str(uuid4())
    )
    logger.debug(f"Biometric registration options generated for {current_user.username}")
    return jsonify(options)

@auth_bp.route('/biometric_register/finish', methods=['POST'])
@login_required
def biometric_register_finish():
    if current_user.role not in ['admin', 'employee']:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    data = request.get_json()
    with db.session() as session:
        user = session.query(User).filter_by(username=current_user.username).first()
        if user:
            try:
                credential = verify_registration_response(
                    credential_creation_options=data,
                    expected_challenge=data['challenge'],
                    expected_rp_id=current_app.config['WEBAUTHN_RP_ID'],
                    expected_origin=request.host_url
                )
                user.webauthn_credential_id = credential.credential_id
                user.webauthn_public_key = credential.public_key
                session.commit()
                logger.info(f"Biometric registration successful for {user.username}")
                flash('Biometric registration successful.', 'success')
                log_audit(user.username, "Biometric registration completed")
            except Exception as e:
                flash('Biometric registration failed. Please try again.', 'danger')
                logger.error(f"Biometric registration error for {user.username}: {str(e)}", exc_info=True)
            return redirect(url_for('dashboard.dashboard'))
        flash('User not found.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

@auth_bp.route('/biometric_login/start', methods=['GET'])
def biometric_login_start():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    username = request.args.get('username')
    logger.debug(f"Biometric login start for {username}")
    with db.session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or not user.webauthn_credential_id:
            flash('Biometric not set up for this user. Please register first.', 'danger')
            return redirect(url_for('auth.login'))
        options = generate_authentication_options(
            rp_id=current_app.config['WEBAUTHN_RP_ID'],
            challenge=str(uuid4()),
            allow_credentials=[{'id': user.webauthn_credential_id, 'type': 'public-key'}]
        )
        return jsonify(options)

@auth_bp.route('/biometric_login/finish', methods=['POST'])
def biometric_login_finish():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    data = request.get_json()
    username = data.get('username')
    credential = data.get('credential')
    logger.debug(f"Biometric login finish for {username}")
    with db.session() as session:
        user = session.query(User).filter_by(username=username).first()
        if user and verify_authentication_response(
            credential=credential,
            expected_challenge=data.get('challenge'),
            credential_id=user.webauthn_credential_id,
            credential_public_key=user.webauthn_public_key,
            rp_id=current_app.config['WEBAUTHN_RP_ID']
        ):
            login_user(user)
            log_audit(user.username, "Biometric login successful")
            return redirect(url_for('dashboard.dashboard'))
        flash('Biometric authentication failed. Please try again or use password login.', 'danger')
        log_audit(username, "Failed biometric login attempt")
        return redirect(url_for('auth.login'))

@auth_bp.route('/qr_login/start')
def qr_login_start():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    session_id = str(uuid4())
    qr_code = f"http://k3v0jr1techcorp.com/auth/qr_login/finish?session={session_id}"
    expires_at = get_current_time() + timedelta(minutes=5)
    logger.debug(f"QR login start with session_id={session_id}")
    with db.session() as session:
        qr_record = QrCode(qr_code=qr_code, user_id=session_id, user_type='guest', expires_at=expires_at)
        session.add(qr_record)
        session.commit()
    qr = qrcode.make(qr_code)
    img_io = BytesIO()
    qr.save(img_io, 'PNG')
    img_io.seek(0)
    response = make_response(img_io.read())
    response.headers['Content-Type'] = 'image/png'
    return response

@auth_bp.route('/qr_login/finish', methods=['GET'])
def qr_login_finish():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    session_id = request.args.get('session')
    logger.debug(f"QR login finish for session_id={session_id}")
    with db.session() as session:
        try:
            qr_record = session.query(QrCode).filter_by(user_id=session_id).first()
            if qr_record and not qr_record.used and qr_record.expires_at > get_current_time():
                guest = session.query(Guest).filter_by(guest_id=session_id).first()
                if guest:
                    qr_record.used = True
                    login_user(guest)
                    log_audit(session_id, "QR login successful")
                    session.commit()
                    return redirect(url_for('dashboard.dashboard'))
            flash('Invalid or expired QR code.', 'danger')
            log_audit(session_id, "Failed QR login attempt")
        except Exception as e:
            flash('An error occurred. Please try again.', 'danger')
            logger.error(f"QR login error for session {session_id}: {str(e)}", exc_info=True)
    return redirect(url_for('auth.login'))

@auth_bp.route('/book_guest', methods=['GET', 'POST'])
@login_required
def book_guest():
    if current_user.role not in ['admin', 'employee']:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        guest_id = sanitize_input(request.form.get('guest_id'))
        name = sanitize_input(request.form.get('name'))
        room_id = sanitize_input(request.form.get('room_id'))
        if not all([guest_id, name, room_id]):
            flash('All fields are required.', 'danger')
            return render_template('book_guest.html')
        with db.session() as session:
            try:
                new_guest = Guest(guest_id=guest_id, name=name, check_in_date=get_current_time(), room_id=room_id, status='checked_in')
                session.add(new_guest)
                session.commit()
                flash('Guest booked successfully.', 'success')
                return redirect(url_for('dashboard.dashboard'))
            except Exception as e:
                session.rollback()
                flash('An error occurred while booking guest. Please try again.', 'danger')
                logger.error(f"Guest booking error for {guest_id}: {str(e)}", exc_info=True)
        return render_template('book_guest.html')
    return render_template('book_guest.html')

@auth_bp.route('/resend_reset', methods=['POST'])
def resend_reset():
    data = request.get_json()
    token = data.get('token')
    logger.debug(f"Resend reset request for token={token}")
    with db.session() as session:
        verification_token = session.query(VerificationToken).filter_by(token=token).first()
        if verification_token and verification_token.expires_at > get_current_time():
            user = session.query(User).filter_by(username=verification_token.user_id).first()
            if user:
                send_reset_email(user.email, token)
                return jsonify({'status': 'success', 'message': 'Reset link resent successfully.'}), 200
    return jsonify({'status': 'error', 'message': 'Invalid or expired token.'}), 400

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/add_employee', methods=['GET', 'POST'])
@login_required
def add_employee():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        employee_id = sanitize_input(request.form.get('employee_id'))
        name = sanitize_input(request.form.get('name'))
        email = sanitize_input(request.form.get('email'))
        role = sanitize_input(request.form.get('role'))
        fingerprint_template = request.form.get('fingerprint_template')
        if not all([employee_id, name, email, role]):
            flash('All fields except fingerprint are required.', 'danger')
            return render_template('add_edit_employee.html', employee=None)
        if not validate_email(email) or role not in ['employee', 'manager']:
            flash('Invalid email or role.', 'danger')
            return render_template('add_edit_employee.html', employee=None)
        with db.session() as session:
            try:
                if session.query(Employee).filter_by(employee_id=employee_id).first():
                    flash('Employee ID already exists.', 'danger')
                    return render_template('add_edit_employee.html', employee=None)
                password_hash = encrypt_data(bcrypt.hash('defaultpassword123'))  # Default password
                new_employee = Employee(employee_id=employee_id, name=name, email=email, role=role, fingerprint_template=fingerprint_template, password_hash=password_hash)
                session.add(new_employee)
                session.commit()
                logger.info(f"Employee {employee_id} added by {current_user.username}")
                flash('Employee added successfully.', 'success')
                return redirect(url_for('dashboard.dashboard'))
            except Exception as e:
                session.rollback()
                flash('An error occurred while adding employee. Please try again.', 'danger')
                logger.error(f"Employee addition error for {employee_id}: {str(e)}", exc_info=True)
        return render_template('add_edit_employee.html', employee=None)
    return render_template('add_edit_employee.html', employee=None)  # Render empty form for GET

@auth_bp.route('/edit_employee/<employee_id>', methods=['GET', 'POST'])
@login_required
def edit_employee(employee_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    with db.session() as session:
        employee = session.query(Employee).filter_by(employee_id=employee_id).first()
        if not employee:
            flash('Employee not found.', 'danger')
            return redirect(url_for('dashboard.dashboard'))
        if request.method == 'POST':
            name = sanitize_input(request.form.get('name'))
            email = sanitize_input(request.form.get('email'))
            role = sanitize_input(request.form.get('role'))
            fingerprint_template = request.form.get('fingerprint_template')
            if not all([name, email, role]):
                flash('All fields except fingerprint are required.', 'danger')
                return render_template('add_edit_employee.html', employee=employee)
            if not validate_email(email) or role not in ['employee', 'manager']:
                flash('Invalid email or role.', 'danger')
                return render_template('add_edit_employee.html', employee=employee)
            try:
                employee.name = name
                employee.email = email
                employee.role = role
                employee.fingerprint_template = fingerprint_template
                session.commit()
                logger.info(f"Employee {employee_id} updated by {current_user.username}")
                flash('Employee updated successfully.', 'success')
                return redirect(url_for('dashboard.dashboard'))
            except Exception as e:
                session.rollback()
                flash('An error occurred while updating employee. Please try again.', 'danger')
                logger.error(f"Employee update error for {employee_id}: {str(e)}", exc_info=True)
            return render_template('add_edit_employee.html', employee=employee)
        return render_template('add_edit_employee.html', employee=employee)

@auth_bp.route('/book_room', methods=['GET', 'POST'])
@login_required
def book_room():
    if current_user.role != 'guest':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    with db.session() as session:
        available_rooms = session.query(Room).filter_by(status='available').all()
        if request.method == 'POST':
            room_id = sanitize_input(request.form.get('room_id'))
            room = session.query(Room).filter_by(room_id=room_id, status='available').first()
            if room:
                booking = Booking(guest_id=current_user.guest_id or current_user.username, room_id=room_id, check_in_date=get_current_time(), check_out_date=get_current_time() + timedelta(days=1), status='booked')
                session.add(booking)
                room.status = 'occupied'
                session.commit()
                logger.info(f"Room {room_id} booked by guest {current_user.guest_id or current_user.username}")
                flash('Room booked successfully.', 'success')
                return redirect(url_for('dashboard.dashboard'))
            flash('Room not available.', 'danger')
            return render_template('book_room.html', available_rooms=available_rooms)
        return render_template('book_room.html', available_rooms=available_rooms)

def send_verification_email(email, token):
    try:
        msg = Message('Verify Your Email', sender=current_app.config['MAIL_USERNAME'], recipients=[email])
        msg.body = f'Click this link to verify your email: {url_for("auth.verify_email", token=token, _external=True)}'
        mail.send(msg)
        logger.debug(f"Verification email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send verification email to {email}: {str(e)}")

def send_reset_email(email, token):
    try:
        msg = Message('Reset Your Password', sender=current_app.config['MAIL_USERNAME'], recipients=[email])
        msg.body = f'Click this link to reset your password: {url_for("auth.reset_password", token=token, _external=True)}'
        mail.send(msg)
        logger.debug(f"Reset email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send reset email to {email}: {str(e)}")

def check_subscription(organization_id):
    subscription = Subscription.query.filter_by(organization_id=organization_id).first()
    result = subscription and datetime.combine(subscription.end_date, datetime.min.time()).replace(tzinfo=get_current_time().tzinfo) > get_current_time()
    logger.debug(f"Subscription check for {organization_id}: {result}")
    return result

def log_audit(user_id, action):
    try:
        from .models import db, AuditLog  # Deferred import
        audit = AuditLog(employee_id=user_id, user_id=user_id, action=action, timestamp=get_current_time())
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to log audit for {user_id}: {str(e)}", exc_info=True)