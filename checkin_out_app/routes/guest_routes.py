from flask import Blueprint, render_template, request, jsonify, flash
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Guest, User
from ..utils import sanitize_input, encrypt_data, decrypt_data, get_current_time
from flask_socketio import socketio
import logging

guest_bp = Blueprint('guest', __name__, url_prefix='/guests')

# Configure logging
logger = logging.getLogger(__name__)

@guest_bp.route('/records', methods=['GET'])
@jwt_required()
def guest_records_api():
    username = sanitize_input(get_jwt_identity())
    with db.session() as session:
        try:
            user = session.query(User).filter_by(username=username).first()
            if not user or user.role not in ['admin', 'guest']:
                return jsonify({'status': 'error', 'message': 'Access denied'}), 403
            page = max(1, int(sanitize_input(request.args.get('page', 1))))  # Prevent negative page
            per_page = min(100, max(1, int(sanitize_input(request.args.get('per_page', 50)))))  # Cap at 100
            offset = (page - 1) * per_page
            total_guests = session.query(Guest).filter_by(status='checked_in').count()
            guests = (session.query(Guest)
                      .filter_by(status='checked_in')
                      .order_by(Guest.check_in_date.desc())
                      .limit(per_page)
                      .offset(offset)
                      .all())
            guests_data = []
            for guest in guests:
                decrypted_name = decrypt_data(guest.name) or "Unknown"  # Handle decryption failure
                guests_data.append({
                    'guest_id': guest.guest_id,
                    'name': decrypted_name,
                    'check_in_date': guest.check_in_date,
                    'check_out_date': guest.check_out_date,
                    'room_id': guest.room_id,
                    'status': guest.status
                })
            pagination = {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_guests,
                'total_pages': (total_guests + per_page - 1) // per_page
            }
            return jsonify({'status': 'success', 'records': guests_data, 'pagination': pagination})
        except ValueError as e:
            return jsonify({'status': 'error', 'message': 'Invalid page or per_page parameter'}), 400
        except Exception as e:
            logger.error(f"Error in guest_records_api: {str(e)}")
            return jsonify({'status': 'error', 'message': 'An error occurred'}), 500

@guest_bp.route('/guest_records', methods=['GET'])
@jwt_required()
def guest_records():
    username = sanitize_input(get_jwt_identity())
    with db.session() as session:
        try:
            user = session.query(User).filter_by(username=username).first()
            if not user or user.role not in ['admin', 'guest']:
                return jsonify({'status': 'error', 'message': 'Access denied'}), 403
            page = max(1, int(sanitize_input(request.args.get('page', 1))))
            per_page = min(100, max(1, int(sanitize_input(request.args.get('per_page', 50)))))
            offset = (page - 1) * per_page
            total_guests = session.query(Guest).filter_by(status='checked_in').count()
            guests = (session.query(Guest)
                      .filter_by(status='checked_in')
                      .order_by(Guest.check_in_date.desc())
                      .limit(per_page)
                      .offset(offset)
                      .all())
            for guest in guests:
                guest.name = decrypt_data(guest.name) or "Unknown"  # Handle decryption failure
            pagination = {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_guests,
                'total_pages': (total_guests + per_page - 1) // per_page
            }
            return render_template('guest_records.html', records=guests, pagination=pagination, hasLoggedIn=True, userRole=user.role)
        except ValueError as e:
            flash('Invalid page or per_page parameter.', 'danger')
            return render_template('guest_records.html', records=[], pagination={}, hasLoggedIn=True, userRole=user.role)
        except Exception as e:
            logger.error(f"Error in guest_records: {str(e)}")
            flash('An error occurred while loading records.', 'danger')
            return render_template('guest_records.html', records=[], pagination={}, hasLoggedIn=True, userRole=user.role)

@guest_bp.route('/check_in', methods=['POST'])
@jwt_required()
def guest_check_in():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    name = sanitize_input(data.get('name'))
    if not all([guest_id, name]):
        return jsonify({'status': 'error', 'message': 'Missing guest_id or name'}), 400
    with db.session() as session:
        try:
            guest = session.query(Guest).filter_by(guest_id=guest_id).first()
            if not guest:
                return jsonify({'status': 'error', 'message': 'Guest not found'}), 404
            if guest.status != 'checked_out':  # Prevent re-check-in
                return jsonify({'status': 'error', 'message': 'Guest is already checked in'}), 400
            guest.status = 'checked_in'
            guest.check_in_date = get_current_time().date().isoformat()
            guest.name = encrypt_data(name) if not guest.name else guest.name  # Update name if provided
            session.commit()
            socketio.emit('guest_update', {
                'guest_id': guest_id,
                'name': decrypt_data(guest.name),
                'action': 'check-in',
                'check_in_date': guest.check_in_date
            })
            logger.info(f"Guest {guest_id} checked in by {username}")
            return jsonify({'status': 'success', 'message': 'Guest checked in successfully'})
        except Exception as e:
            session.rollback()
            logger.error(f"Error in guest_check_in for {guest_id}: {str(e)}")
            return jsonify({'status': 'error', 'message': 'An error occurred'}), 500

@guest_bp.route('/check_out', methods=['POST'])
@jwt_required()
def guest_check_out():
    username = sanitize_input(get_jwt_identity())
    data = request.get_json()
    guest_id = sanitize_input(data.get('guest_id'))
    if not guest_id:
        return jsonify({'status': 'error', 'message': 'Missing guest_id'}), 400
    with db.session() as session:
        try:
            guest = session.query(Guest).filter_by(guest_id=guest_id).first()
            if not guest:
                return jsonify({'status': 'error', 'message': 'Guest not found'}), 404
            if guest.status != 'checked_in':  # Prevent re-check-out
                return jsonify({'status': 'error', 'message': 'Guest is not checked in'}), 400
            guest.status = 'checked_out'
            guest.check_out_date = get_current_time().date().isoformat()
            session.commit()
            socketio.emit('guest_update', {
                'guest_id': guest_id,
                'action': 'check-out',
                'check_out_date': guest.check_out_date
            })
            logger.info(f"Guest {guest_id} checked out by {username}")
            return jsonify({'status': 'success', 'message': 'Guest checked out successfully'})
        except Exception as e:
            session.rollback()
            logger.error(f"Error in guest_check_out for {guest_id}: {str(e)}")
            return jsonify({'status': 'error', 'message': 'An error occurred'}), 500