from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Employee
from ..utils import sanitize_input, allowed_file, match_fingerprint
import os
import pandas as pd

employee_bp = Blueprint('employee', __name__, url_prefix='/employees')

@employee_bp.route('/', methods=['GET'])
@jwt_required()
def employees():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 50)))
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
        userRole=user.role,
        current_year=datetime.now().year,
        datetime=datetime
    )

@employee_bp.route('/api', methods=['GET'])
@jwt_required()
def get_employees():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 50)))
        offset = (page - 1) * per_page
        total_employees = session.query(Employee).filter_by(organization_id=username).count()
        employees = [emp._asdict() for emp in session.query(Employee).filter_by(organization_id=username).order_by(Employee.name).limit(per_page).offset(offset).all()]
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
@jwt_required()
def edit_employee(employee_id):
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
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
            if photo.stream.tell() > app.config['MAX_FILE_SIZE']:
                return jsonify({'error': 'File size exceeds 5MB'}), 400
            photo.stream.seek(0)
            filename = secure_filename(f"{employee_id}_{photo.filename}")
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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
    return jsonify({'success': True, 'message': 'Employee updated'})

@employee_bp.route('/api/<employee_id>', methods=['DELETE'])
@jwt_required()
def delete_employee(employee_id):
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        employee = session.query(Employee).filter_by(employee_id=employee_id, organization_id=username).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        session.delete(employee)
        session.query(Attendance).filter_by(employee_id=employee_id).delete()
        session.commit()
    return jsonify({'success': True, 'message': 'Employee deleted'})

@employee_bp.route('/bulk_import', methods=['POST'])
@jwt_required()
def bulk_import_employees():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
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
    return jsonify({'success': True, 'message': f'{count} employees imported'})

@employee_bp.route('/bulk_delete', methods=['POST'])
@jwt_required()
def bulk_delete_employees():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        employee_ids = request.get_json().get('employee_ids', [])
        if not employee_ids:
            return jsonify({'error': 'No employee IDs'}), 400
        valid_ids = {emp.employee_id for emp in session.query(Employee.employee_id).filter(Employee.employee_id.in_(employee_ids), Employee.organization_id==username).all()}
        if not valid_ids:
            return jsonify({'error': 'No valid employees'}), 404
        session.query(Employee).filter(Employee.employee_id.in_(employee_ids), Employee.organization_id==username).delete()
        session.query(Attendance).filter(Attendance.employee_id.in_(employee_ids)).delete()
        session.commit()
    return jsonify({'success': True, 'message': f'{len(valid_ids)} employees deleted'})