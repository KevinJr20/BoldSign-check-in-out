from flask import Blueprint, render_template, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Guest, User  # Added User
from ..utils import sanitize_input, decrypt_guest_name, get_current_time
from flask_socketio import socketio  # Ensure socketio is imported

guest_bp = Blueprint('guest', __name__, url_prefix='/guests')

@guest_bp.route('/records', methods=['GET'])
@jwt_required()
def guest_records_api():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role not in ['admin', 'guest']:
            return jsonify({'error': 'Access denied'}), 403
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 50)))
        offset = (page - 1) * per_page
        total_guests = session.query(Guest).filter_by(status='checked_in').count()
        guests = session.query(Guest).filter_by(status='checked_in').order_by(Guest.check_in_date.desc()).limit(per_page).offset(offset).all()
        for guest in guests:
            guest.name = decrypt_guest_name(guest.name)
        pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_guests, 'total_pages': (total_guests + per_page - 1) // per_page}
    return jsonify({
        'status': 'success',
        'records': [guest._asdict() for guest in guests],
        'pagination': pagination
    })

@guest_bp.route('/guest_records', methods=['GET'])  # New HTML route
@jwt_required()
def guest_records():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role not in ['admin', 'guest']:
            return jsonify({'error': 'Access denied'}), 403
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 50)))
        offset = (page - 1) * per_page
        total_guests = session.query(Guest).filter_by(status='checked_in').count()
        guests = session.query(Guest).filter_by(status='checked_in').order_by(Guest.check_in_date.desc()).limit(per_page).offset(offset).all()
        for guest in guests:
            guest.name = decrypt_guest_name(guest.name)
        pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_guests, 'total_pages': (total_guests + per_page - 1) // per_page}
    return render_template('guest_records.html', records=guests, pagination=pagination, hasLoggedIn=True, userRole=user.role)

@guest_bp.route('/check_in', methods=['POST'])
@jwt_required()
def guest_check_in():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    name = sanitize_input(data.get('name'))
    if not guest_id or not name:
        return jsonify({'error': 'Missing guest_id or name'}), 400
    with db.session as session:
        guest = session.query(Guest).filter_by(guest_id=guest_id).first()
        if not guest:
            return jsonify({'error': 'Guest not found'}), 404
        guest.status = 'checked_in'
        guest.check_in_date = get_current_time().date().isoformat()
        session.commit()
        socketio.emit('guest_update', {
            'guest_id': guest_id,
            'name': decrypt_guest_name(guest.name),
            'action': 'check-in',
            'check_in_date': guest.check_in_date
        })
    return jsonify({'success': True, 'message': 'Guest checked in successfully'})

@guest_bp.route('/check_out', methods=['POST'])
@jwt_required()
def guest_check_out():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    if not guest_id:
        return jsonify({'error': 'Missing guest_id'}), 400
    with db.session as session:
        guest = session.query(Guest).filter_by(guest_id=guest_id).first()
        if not guest:
            return jsonify({'error': 'Guest not found'}), 404
        guest.status = 'checked_out'
        guest.check_out_date = get_current_time().date().isoformat()
        session.commit()
        socketio.emit('guest_update', {
            'guest_id': guest_id,
            'action': 'check-out',
            'check_out_date': guest.check_out_date
        })
    return jsonify({'success': True, 'message': 'Guest checked out successfully'})