from flask import Blueprint, jsonify, render_template, request, current_app
from flask_login import login_required, current_user
from ..models import db, Room, Booking, Guest, User 
from ..utils import sanitize_input, get_current_time, encrypt_data, validate_date, parse_date
from ..utils import get_mpesa_access_token, validate_mpesa_signature
import requests
import re
import uuid
import base64
from flask_socketio import socketio
from datetime import date  

room_bp = Blueprint('room', __name__, url_prefix='/rooms')

@room_bp.route('/status', methods=['GET'])
@login_required
def room_status():
    if not current_user.is_authenticated:
        return jsonify({'error': 'User not found'}), 404
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        page = int(sanitize_input(request.args.get('page', '1'))) if request.args.get('page', '1').isdigit() else 1
        per_page = int(sanitize_input(request.args.get('per_page', '50'))) if request.args.get('per_page', '50').isdigit() else 50
        offset = (page - 1) * per_page
        total_rooms = session.query(Room).count()
        rooms = session.query(Room).order_by(Room.room_id).limit(per_page).offset(offset).all()
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return jsonify({
        'success': True,
        'rooms': [room._asdict() for room in rooms],
        'pagination': {
            'current_page': page,
            'per_page': per_page,
            'total_items': total_rooms,
            'total_pages': (total_rooms + per_page - 1) // per_page
        }
    })

@room_bp.route('/book', methods=['POST'])
@login_required
def book_room():
    if not current_user.is_authenticated:
        return jsonify({'error': 'User not found'}), 404
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        data = request.get_json()
        guest_name = sanitize_input(data.get('guest_name'))
        room_id = sanitize_input(data.get('room_id'))
        check_in_date = sanitize_input(data.get('check_in_date'))
        check_out_date = sanitize_input(data.get('check_out_date'))
        payment_method = sanitize_input(data.get('payment_method'))
        if not all([guest_name, room_id, check_in_date, check_out_date, payment_method]):
            return jsonify({'error': 'All fields required'}), 400
        if not validate_date(check_in_date) or not validate_date(check_out_date):
            return jsonify({'error': 'Invalid date format'}), 400
        check_in = parse_date(check_in_date).date()
        check_out = parse_date(check_out_date).date()
        if check_in >= check_out or check_in < date.today():
            return jsonify({'error': 'Invalid date range'}), 400
        room = session.query(Room).filter_by(room_id=room_id).first()
        if not room or room.status != 'available':
            return jsonify({'error': 'Room not available'}), 400
        if session.query(Booking).filter(Booking.room_id == room_id, Booking.status.notin_(['cancelled', 'checked_out']), Booking.check_in_date <= check_out_date, Booking.check_out_date >= check_in_date).first():
            return jsonify({'error': 'Room booked for selected dates'}), 400
        guest_id = str(uuid.uuid4())
        encrypted_name = encrypt_data(guest_name)  # Corrected function name
        nights = (check_out - check_in).days
        amount = current_app.config['ROOM_PRICING'][room.room_type] * nights
        if payment_method == 'mpesa':
            phone_number = sanitize_input(data.get('phone_number'))
            if not phone_number or not re.match(r'^2547\d{8}$', phone_number):
                return jsonify({'error': 'Valid phone number required'}), 400
            access_token = get_mpesa_access_token()
            if not access_token:
                return jsonify({'error': 'M-Pesa access token error'}), 500
            timestamp = get_current_time().strftime('%Y%m%d%H%M%S')
            password = base64.b64encode(f"{current_app.config['MPESA_SHORTCODE']}{current_app.config['MPESA_PASSKEY']}{timestamp}".encode()).decode()
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            payload = {
                "BusinessShortCode": current_app.config['MPESA_SHORTCODE'],
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": phone_number,
                "PartyB": current_app.config['MPESA_SHORTCODE'],
                "PhoneNumber": phone_number,
                "CallBackURL": f"{request.host_url}mpesa/callback",
                "AccountReference": f"Booking-{guest_id}",
                "TransactionDesc": f"Room booking for {guest_name}"
            }
            response = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if os.getenv('FLASK_ENV') != 'production' else "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=payload, headers=headers, timeout=10)
            result = response.json()
            if response.status_code != 200 or result.get('ResponseCode') != '0':
                return jsonify({'error': 'M-Pesa payment failed'}), 500
        new_booking = Booking(guest_id=guest_id, guest_name=encrypted_name, room_id=room_id, check_in_date=check_in_date, check_out_date=check_out_date, payment_status='pending' if payment_method == 'mpesa' else 'completed')
        room.status = 'occupied'
        new_guest = Guest(guest_id=guest_id, name=encrypted_name, check_in_date=check_in_date, check_out_date=check_out_date, room_id=room_id, status='checked_in')
        session.add_all([new_booking, new_guest])
        session.commit()
        socketio.emit('room_status_update', {'room_id': room_id, 'status': 'occupied'})
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return jsonify({'success': True, 'message': 'Room booked'})

@room_bp.route('/', methods=['GET'], endpoint='room')  # New route for 'room.room'
@login_required
def room_home():
    if not current_user.is_authenticated:
        return jsonify({'error': 'User not found'}), 404
    
    username = sanitize_input(current_user.username)
    session = db.session  # Use session directly
    try:
        rooms = session.query(Room).all()
    finally:
        session.close()  # Optional: Close session if not using autocommit
    return render_template('room.html', rooms=rooms, hasLoggedIn=True, username=username, userRole=current_user.role)