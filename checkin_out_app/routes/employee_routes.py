import os
import hashlib
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from flask_wtf import CSRFProtect
from ..models import db, User, Employee, Attendance, Subscription
from ..utils import sanitize_input, allowed_file, match_fingerprint
from werkzeug.utils import secure_filename
from email_validator import validate_email, EmailNotValidError
import pandas as pd
from datetime import datetime

employee_bp = Blueprint('employee', __name__, url_prefix='/employees')
csrf = CSRFProtect()

@employee_bp.route('/', methods=['GET', 'POST'], endpoint='employee')
@login_required
def employees():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    username = sanitize_input(current_user.username)
    session = db.session
    try:
        print("Request method:", request.method)  # Debug log
        print("Request form data:", request.form)  # Debug form data
        if request.method == 'POST' and 'action' in request.form and request.form['action'] == 'add':
            employee_id = sanitize_input(request.form.get('employeeId'))
            name = sanitize_input(request.form.get('employeeName'))
            fingerprint_template = sanitize_input(request.form.get('fingerprintTemplate'))
            email = sanitize_input(request.form.get('email', ''))
            role = sanitize_input(request.form.get('role', 'employee'))
            biometric_data = sanitize_input(request.form.get('biometricData', ''))
            photo = request.files.get('photo')
            if not all([employee_id, name, fingerprint_template]):
                return jsonify({'success': False, 'message': 'Employee ID, name, and fingerprint template are required.'}), 400
            if Employee.query.filter_by(employee_id=employee_id, organization_id=username).first():
                return jsonify({'success': False, 'message': 'Employee ID already exists!'}), 400
            if email and not validate_email(email):
                return jsonify({'success': False, 'message': 'Invalid email!'}), 400
            if photo and not allowed_file(photo.filename, photo.stream):
                return jsonify({'success': False, 'message': 'Invalid file type!'}), 400
            else:
                if photo:
                    photo.stream.seek(0, os.SEEK_END)
                    if photo.stream.tell() > current_app.config['MAX_FILE_SIZE']:
                        return jsonify({'success': False, 'message': 'File size exceeds 5MB!'}), 400
                    photo.stream.seek(0)
                    filename = secure_filename(f"{employee_id}_{photo.filename}")
                    photo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    photo.save(photo_path)
                    photo_url = f"/static/uploads/{filename}"
                else:
                    photo_url = None
                # Corrected default hash logic
                biometric_hash = hashlib.sha256(biometric_data.encode() if biometric_data else b'').hexdigest()
                new_employee = Employee(
                    employee_id=employee_id, name=name, email=email, role=role,
                    fingerprint_template=fingerprint_template, biometric_hash=biometric_hash,
                    photo_url=photo_url, organization_id=username
                )
                session.add(new_employee)
                session.commit()
                return jsonify({'success': True, 'message': 'Employee added successfully!'})

        # GET request handling
        page = int(sanitize_input(request.args.get('page', '1'))) if request.args.get('page', '1').isdigit() else 1
        per_page = int(sanitize_input(request.args.get('per_page', '50'))) if request.args.get('per_page', '50').isdigit() else 50
        offset = (page - 1) * per_page
        total_employees = session.query(Employee).filter_by(organization_id=username).count()
        employees = session.query(Employee).filter_by(organization_id=username).order_by(Employee.name).limit(per_page).offset(offset).all()
        pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_employees, 'total_pages': (total_employees + per_page - 1) // per_page}

        return render_template(
            'employees.html',
            employees=employees,
            pagination=pagination,
            hasLoggedIn=True,
            username=username,
            userRole=current_user.role,
            current_year=datetime.now().year,
            datetime=datetime
        )
    except Exception as e:
        session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        session.close()

@employee_bp.route('/api', methods=['GET'])
@login_required
def get_employees():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        page = int(sanitize_input(request.args.get('page', '1'))) if request.args.get('page', '1').isdigit() else 1
        per_page = int(sanitize_input(request.args.get('per_page', '50'))) if request.args.get('per_page', '50').isdigit() else 50
        offset = (page - 1) * per_page
        total_employees = session.query(Employee).filter_by(organization_id=username).count()
        employees = [emp._asdict() for emp in session.query(Employee).filter_by(organization_id=username).order_by(Employee.name).limit(per_page).offset(offset).all()]
    finally:
        session.close()  # Optional: Close session if not using autocommit
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

@employee_bp.route('/api/<employee_id>', methods=['PUT'])
@login_required
def edit_employee(employee_id):
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        employee = session.query(Employee).filter_by(employee_id=employee_id, organization_id=username).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        name = sanitize_input(request.form.get('name'))
        email = sanitize_input(request.form.get('email', ''))
        role = sanitize_input(request.form.get('role', 'employee'))
        fingerprint_template = sanitize_input(request.form.get('fingerprint_template'))
        biometric_data = sanitize_input(request.form.get('biometric_data'))
        photo = request.files.get('photo')
        if not all([name, fingerprint_template]):
            return jsonify({'error': 'Name and fingerprint required'}), 400
        if email and not validate_email(email):
            return jsonify({'error': 'Invalid email'}), 400
        if photo and allowed_file(photo.filename, photo.stream):
            photo.stream.seek(0, os.SEEK_END)
            if photo.stream.tell() > current_app.config['MAX_FILE_SIZE']:
                return jsonify({'error': 'File size exceeds 5MB'}), 400
            photo.stream.seek(0)
            filename = secure_filename(f"{employee_id}_{photo.filename}")
            photo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            photo.save(photo_path)
            photo_url = f"/static/uploads/{filename}"
        else:
            photo_url = employee.photo_url
        biometric_hash = hashlib.sha256(biometric_data.encode()).hexdigest() if biometric_data else employee.biometric_hash
        employee.name = name
        employee.email = email
        employee.role = role
        employee.fingerprint_template = fingerprint_template
        employee.biometric_hash = biometric_hash
        employee.photo_url = photo_url
        session.commit()
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return jsonify({'success': True, 'message': 'Employee updated'})

@employee_bp.route('/api/<employee_id>', methods=['DELETE'])
@login_required
def delete_employee(employee_id):
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        employee = session.query(Employee).filter_by(employee_id=employee_id, organization_id=username).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        session.delete(employee)
        session.query(Attendance).filter_by(employee_id=employee_id).delete()
        session.commit()
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return jsonify({'success': True, 'message': 'Employee deleted'})

@employee_bp.route('/bulk_import', methods=['POST'])
@login_required
def bulk_import_employees():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            return jsonify({'error': 'CSV file required'}), 400
        df = pd.read_csv(file)
        required_columns = ['employee_id', 'name', 'fingerprint_template']
        if not all(col in df.columns for col in required_columns):
            return jsonify({'error': 'CSV missing required columns'}), 400
        subscription = session.query(Subscription).filter_by(organization_id=username).first()
        if not subscription:
            return jsonify({'error': 'No subscription found'}), 403
        employee_limit = subscription.employee_limit
        current_count = session.query(Employee).filter_by(organization_id=username).count()
        if current_count + len(df) > employee_limit:
            return jsonify({'error': 'Exceeds employee limit'}), 403
        existing_ids = {emp.employee_id for emp in session.query(Employee.employee_id).filter_by(organization_id=username).all()}
        count = 0
        for _, row in df.iterrows():
            employee_id = str(row['employee_id']).strip()
            if employee_id in existing_ids:
                continue
            name = sanitize_input(str(row['name']).strip())
            fingerprint_template = sanitize_input(str(row['fingerprint_template']).strip())
            biometric_data = sanitize_input(str(row.get('biometric_data', '')).strip())
            email = sanitize_input(str(row.get('email', '')).strip())
            role = sanitize_input(str(row.get('role', 'employee')).strip())
            biometric_hash = hashlib.sha256(biometric_data.encode()).hexdigest() if biometric_data else None
            if email and not validate_email(email):
                continue
            new_employee = Employee(employee_id=employee_id, name=name, email=email, role=role, fingerprint_template=fingerprint_template, biometric_hash=biometric_hash, organization_id=username)
            session.add(new_employee)
            count += 1
        session.commit()
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return jsonify({'success': True, 'message': f'{count} employees imported'})

@employee_bp.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete_employees():
    if not current_user.is_authenticated or current_user.role != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        employee_ids = request.get_json().get('employee_ids', [])
        if not employee_ids:
            return jsonify({'error': 'No employee IDs'}), 400
        valid_ids = {emp.employee_id for emp in session.query(Employee.employee_id).filter(Employee.employee_id.in_(employee_ids), Employee.organization_id==username).all()}
        if not valid_ids:
            return jsonify({'error': 'No valid employees'}), 404
        session.query(Employee).filter(Employee.employee_id.in_(employee_ids), Employee.organization_id==username).delete()
        session.query(Attendance).filter(Attendance.employee_id.in_(employee_ids)).delete()
        session.commit()
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return jsonify({'success': True, 'message': f'{len(valid_ids)} employees deleted'})