from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, User, Employee, Guest, QrCode
from ..utils import sanitize_input, get_current_time

qr_bp = Blueprint('qr', __name__, url_prefix='/qr')

@qr_bp.route('/scan', methods=['POST'])
@jwt_required()
def qr_scan():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role not in ['admin', 'employee']:
            return jsonify({'error': 'Access denied'}), 403
        data = request.get_json()
        qr_code = sanitize_input(data.get('qr_code'))
        if not qr_code:
            return jsonify({'error': 'No QR code provided'}), 400
        qr = session.query(QrCode).filter_by(qr_code=qr_code, used=False, expires_at=get_current_time()).first()
        if not qr:
            return jsonify({'error': 'Invalid or expired QR code'}), 404
        qr.used = True
        session.commit()
        user_id, user_type = qr.user_id, qr.user_type
        if user_type == 'employee':
            employee = session.query(Employee).filter_by(employee_id=user_id, organization_id=username).first()
            if not employee:
                return jsonify({'error': 'Employee not found'}), 404
            today = get_current_time().date().isoformat()
            current_time = get_current_time().strftime('%H:%M:%S')
            attendance = session.query(Attendance).filter_by(employee_id=user_id, date=today).first()
            if attendance and not attendance.time_out:
                attendance.time_out = current_time
                action = 'check-out'
            else:
                new_attendance = Attendance(employee_id=user_id, name=employee.name, date=today, time_in=current_time, timestamp=get_current_time())
                session.add(new_attendance)
                action = 'check-in'
            session.commit()
            socketio.emit('employee_status', {
                'employee_id': user_id,
                'name': employee.name,
                'action': action,
                'time': current_time,
                'date': today
            })
            return jsonify({'success': True, 'message': f'{employee.name} {action} successful', 'action': action})
        elif user_type == 'guest':
            guest = session.query(Guest).filter_by(guest_id=user_id).first()
            if not guest or guest.status == 'checked_in':
                return jsonify({'error': 'Guest not found or already checked in'}), 404
            guest.status = 'checked_in'
            guest.check_in_date = get_current_time().date().isoformat()
            session.query(Booking).filter_by(guest_id=user_id).update({'status': 'checked_in'})
            session.commit()
            socketio.emit('guest_status_update', {
                'guest_id': user_id,
                'name': decrypt_guest_name(guest.name),
                'action': 'check-in',
                'date': guest.check_in_date
            })
            return jsonify({'success': True, 'message': 'Guest check-in successful'})
        return jsonify({'error': 'Invalid QR code type'}), 400

@qr_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_qr():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        data = request.get_json()
        user_id = sanitize_input(data.get('user_id'))
        user_type = sanitize_input(data.get('user_type'))
        if user_type not in ['employee', 'guest']:
            return jsonify({'error': 'Invalid user type'}), 400
        if user_type == 'employee' and not session.query(Employee).filter_by(employee_id=user_id, organization_id=username).first():
            return jsonify({'error': 'Employee not found'}), 404
        elif user_type == 'guest' and not session.query(Guest).filter_by(guest_id=user_id).first():
            return jsonify({'error': 'Guest not found'}), 404
        qr_code = str(uuid.uuid4())
        expires_at = get_current_time() + timedelta(hours=24)
        new_qr = QrCode(qr_code=qr_code, user_id=user_id, user_type=user_type, expires_at=expires_at)
        session.add(new_qr)
        session.commit()
    return jsonify({'success': True, 'qr_code': qr_code, 'expires_at': expires_at.isoformat()})