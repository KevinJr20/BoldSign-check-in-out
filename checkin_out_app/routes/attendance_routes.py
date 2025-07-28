from flask import Blueprint, jsonify, send_file, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Attendance, Employee, User
from ..utils import sanitize_input, validate_date, get_current_time
import pandas as pd
from flask_socketio import socketio

attendance_bp = Blueprint('attendance', __name__, url_prefix='/attendance')

@attendance_bp.route('/', methods=['GET'])
@jwt_required()
def get_attendance():
    username = sanitize_input(get_jwt_identity())
    session = db.session
    try:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role not in ['admin', 'employee']:
            return jsonify({'error': 'Access denied'}), 403
        start_date = sanitize_input(request.args.get('start_date'))
        end_date = sanitize_input(request.args.get('end_date'))
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 50)))
        offset = (page - 1) * per_page
        if start_date and end_date:
            if not validate_date(start_date) or not validate_date(end_date):
                return jsonify({'error': 'Invalid date format'}), 400
            total_records = session.query(Attendance).filter(Attendance.date.between(start_date, end_date)).count()
            records = session.query(Attendance).filter(Attendance.date.between(start_date, end_date)).order_by(Attendance.timestamp.desc()).limit(per_page).offset(offset).all()
        else:
            total_records = session.query(Attendance).count()
            records = session.query(Attendance).order_by(Attendance.timestamp.desc()).limit(per_page).offset(offset).all()
        pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_records, 'total_pages': (total_records + per_page - 1) // per_page}
        # Convert records to list of dictionaries for template
        records_list = [record._asdict() for record in records]
    finally:
        session.close()
    return render_template('attendance.html', records=records_list, pagination=pagination, hasLoggedIn=True, username=username, userRole=user.role, start_date=start_date, end_date=end_date)

@attendance_bp.route('/export', methods=['GET'])
@jwt_required()
def export_attendance():
    username = sanitize_input(get_jwt_identity())
    session = db.session
    try:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        records = session.query(Attendance).order_by(Attendance.date.desc()).all()
        df = pd.DataFrame([record._asdict() for record in records])
        csv_path = 'attendance_export.csv'
        df.to_csv(csv_path, index=False)
    finally:
        session.close()
    return send_file(csv_path, as_attachment=True, download_name='attendance_export.csv')

@attendance_bp.route('/check_in', methods=['POST'])
@jwt_required()
def check_in():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    employee_id = sanitize_input(data.get('employee_id'))
    name = sanitize_input(data.get('name'))
    if not employee_id or not name:
        return jsonify({'error': 'Missing employee_id or name'}), 400
    session = db.session
    try:
        new_attendance = Attendance(employee_id=employee_id, name=name, date=get_current_time().date().isoformat(), time_in=get_current_time().strftime('%H:%M:%S'), timestamp=get_current_time())
        session.add(new_attendance)
        session.commit()
        socketio.emit('attendance_update', {
            'employee_id': employee_id,
            'name': name,
            'action': 'check-in',
            'time_in': get_current_time().strftime('%H:%M:%S')
        })
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
    return jsonify({'success': True, 'message': 'Checked in successfully'})

@attendance_bp.route('/check_out', methods=['POST'])
@jwt_required()
def check_out():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    employee_id = sanitize_input(data.get('id'))
    if not employee_id:
        return jsonify({'error': 'Missing employee_id'}), 400
    session = db.session
    try:
        attendance = session.query(Attendance).filter_by(employee_id=employee_id, date=get_current_time().date().isoformat(), time_out=None).first()
        if attendance:
            attendance.time_out = get_current_time().strftime('%H:%M:%S')
            session.commit()
            socketio.emit('attendance_update', {
                'employee_id': employee_id,
                'action': 'check-out',
                'time_out': get_current_time().strftime('%H:%M:%S')
            })
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
    return jsonify({'success': True, 'message': 'Checked out successfully'})