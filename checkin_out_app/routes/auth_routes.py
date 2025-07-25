from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response, current_app
from flask_jwt_extended import jwt_required, create_access_token, set_access_cookies, unset_jwt_cookies, get_jwt_identity
from flask_login import login_user, logout_user, login_required, current_user
from passlib.hash import bcrypt
from uuid import uuid4
from datetime import datetime, timedelta
from ..db import db  # Import db from db.py
from ..models import User, VerificationToken, Guest, Subscription
from ..utils import sanitize_input, validate_email, get_current_time
from flask_wtf.csrf import CSRFProtect

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
csrf = CSRFProtect()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        username = sanitize_input(request.form.get('username'))
        password = request.form.get('password')
        login_type = sanitize_input(request.form.get('login_type'))
        if not all([username, password, login_type]):
            flash('All fields are required.', 'danger')
            return render_template('login.html', config=current_app.config, current_year=datetime.now().year)
        with db.session() as session:  # Use session within a context
            try:
                if login_type == 'employee':
                    user = session.query(User).filter_by(username=username).first()
                    if user and bcrypt.verify(password, user.password_hash):
                        login_user(user)
                        access_token = create_access_token(identity={'username': username, 'role': user.role})
                        response = make_response(redirect(url_for('dashboard.dashboard')))
                        set_access_cookies(response, access_token)
                        flash('Login successful!', 'success')
                        return response
                elif login_type == 'guest':
                    guest = session.query(Guest).filter_by(guest_id=username).first()
                    if guest:
                        login_user(guest)
                        access_token = create_access_token(identity={'username': username, 'role': 'guest'})
                        response = make_response(redirect(url_for('dashboard.dashboard')))
                        set_access_cookies(response, access_token)
                        flash('Guest login successful!', 'success')
                        return response
                flash('Invalid credentials.', 'danger')
            finally:
                session.close()  # Ensure session is closed
        return render_template('login.html', config=current_app.config, current_year=datetime.now().year)
    return render_template('login.html', config=current_app.config, current_year=datetime.now().year)

@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    response = make_response(redirect(url_for('auth.login')))
    unset_jwt_cookies(response)
    flash('Logged out.', 'success')
    return response

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        if request.form:
            username = sanitize_input(request.form.get('username'))
            email = sanitize_input(request.form.get('email'))
            password = request.form.get('password')
            organization_type = sanitize_input(request.form.get('organization_type'))
            if not all([username, email, password, organization_type]):
                flash('All fields are required.', 'danger')
                return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year)
            if not validate_email(email) or organization_type not in current_app.config['ORGANIZATION_TYPES']:
                flash('Invalid email or organization type.', 'danger')
                return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year)
            with db.session() as session:  # Use session within a context
                try:
                    if session.query(User).filter_by(username=username).first() or session.query(User).filter_by(email=email).first():
                        flash('Username or email already exists.', 'danger')
                        return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year)
                    password_hash = bcrypt.hash(password)
                    new_user = User(username=username, email=email, password_hash=password_hash, organization_type=organization_type, role='admin')
                    session.add(new_user)
                    default_plan = current_app.config['ORGANIZATION_TYPES'][organization_type]['default_plan']
                    employee_limit = current_app.config['SUBSCRIPTION_TIERS'][default_plan]['employee_limit']
                    subscription = Subscription(organization_id=username, plan=default_plan, employee_limit=employee_limit, start_date=get_current_time().date().isoformat())
                    session.add(subscription)
                    token = VerificationToken(user_id=username, token=str(uuid4()), expires_at=get_current_time() + timedelta(days=1))
                    session.add(token)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    flash(f'Error during registration: {str(e)}', 'danger')
                    return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year)
            flash('Registration successful! Please verify your email.', 'success')
            return redirect(url_for('auth.login'))
        elif request.method == 'POST' and request.is_json:
            data = request.get_json()
            username = sanitize_input(data.get('username'))
            email = sanitize_input(data.get('email'))
            password = data.get('password')
            organization_type = sanitize_input(data.get('organization_type'))
            if not all([username, email, password, organization_type]):
                return jsonify({'status': 'error', 'message': 'All fields are required.'}), 400
            if not validate_email(email) or organization_type not in current_app.config['ORGANIZATION_TYPES']:
                return jsonify({'status': 'error', 'message': 'Invalid email or organization type.'}), 400
            with db.session() as session:  # Use session within a context
                try:
                    if session.query(User).filter_by(username=username).first() or session.query(User).filter_by(email=email).first():
                        return jsonify({'status': 'error', 'message': 'Username or email already exists.'}), 400
                    password_hash = bcrypt.hash(password)
                    new_user = User(username=username, email=email, password_hash=password_hash, organization_type=organization_type, role='admin')
                    session.add(new_user)
                    default_plan = current_app.config['ORGANIZATION_TYPES'][organization_type]['default_plan']
                    employee_limit = current_app.config['SUBSCRIPTION_TIERS'][default_plan]['employee_limit']
                    subscription = Subscription(organization_id=username, plan=default_plan, employee_limit=employee_limit, start_date=get_current_time().date().isoformat())
                    session.add(subscription)
                    token = VerificationToken(user_id=username, token=str(uuid4()), expires_at=get_current_time() + timedelta(days=1))
                    session.add(token)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    return jsonify({'status': 'error', 'message': f'Registration failed: {str(e)}'}), 500
            return jsonify({'status': 'success', 'message': 'Registration successful! Please verify your email.'}), 200
    return render_template('register.html', organization_types=current_app.config['ORGANIZATION_TYPES'], current_year=datetime.now().year)

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html', config=current_app.config, current_year=datetime.now().year)
    elif request.method == 'POST':
        email_or_username = sanitize_input(request.form.get('email_or_username'))
        if not email_or_username:
            flash('Email or username is required.', 'danger')
            return render_template('forgot_password.html', config=current_app.config, current_year=datetime.now().year)
        with db.session() as session:  # Use session within a context
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
                    flash('A password reset link has been sent to your email.', 'success')
                    # TODO: Implement email sending logic here
                else:
                    flash('No account found with that email or username.', 'danger')
            except Exception as e:
                session.rollback()
                flash(f'Error processing request: {str(e)}', 'danger')
        return render_template('forgot_password.html', config=current_app.config, current_year=datetime.now().year)
