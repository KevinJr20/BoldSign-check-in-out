from flask import Blueprint, render_template, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Attendance, Room, Guest
from ..utils import sanitize_input, get_current_time

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@dashboard_bp.route('/', methods=['GET'])
@jwt_required()
def dashboard():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        role = user.role
        today = get_current_time().date().isoformat()
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 50)))
        offset = (page - 1) * per_page

        attendance = session.query(Attendance).filter_by(date=today).order_by(Attendance.timestamp.desc()).limit(per_page).offset(offset).all()
        total_attendance = session.query(Attendance).filter_by(date=today).count()
        attendance_pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_attendance, 'total_pages': (total_attendance + per_page - 1) // per_page}

        rooms = session.query(Room).order_by(Room.room_id).limit(per_page).offset(offset).all()
        total_rooms = session.query(Room).count()
        rooms_pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_rooms, 'total_pages': (total_rooms + per_page - 1) // per_page}

        guests = session.query(Guest).filter_by(status='checked_in').order_by(Guest.check_in_date.desc()).limit(per_page).offset(offset).all()
        for guest in guests:
            guest.name = decrypt_guest_name(guest.name)
        total_guests = session.query(Guest).filter_by(status='checked_in').count()
        guests_pagination = {'current_page': page, 'per_page': per_page, 'total_items': total_guests, 'total_pages': (total_guests + per_page - 1) // per_page}

    return render_template(
        'dashboard.html',
        records=attendance,
        records_pagination=attendance_pagination,
        rooms=rooms,
        rooms_pagination=rooms_pagination,
        guests=guests,
        guests_pagination=guests_pagination,
        config=app.config,
        current_year=datetime.now().year,
        datetime=datetime,
        current_time=get_current_time().strftime('%H:%M:%S'),
        hasLoggedIn=True,
        username=username,
        userRole=role
    )