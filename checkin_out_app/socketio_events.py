from flask_socketio import emit, join_room, leave_room, disconnect
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from . import socketio  # Import socketio from the package
from .utils import sanitize_input, get_current_time
from .models import db, Room, Attendance, Guest, Employee, QrCode, User 

@socketio.on('connect')
def handle_connect(auth):
    if not auth or not verify_jwt_in_request():
        disconnect()
        return
    username = sanitize_input(get_jwt_identity())
    join_room(username)
    emit('connection_status', {'success': True, 'message': 'Connected'}, room=username)

@socketio.on('subscribe_room_updates')
def subscribe_room_updates():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role not in ['admin', 'employee']:
            emit('error', {'error': 'Access denied'}, room=username)
            return
        rooms = session.query(Room).all()
        emit('room_update', {'rooms': [room._asdict() for room in rooms]}, room=username)

@socketio.on('subscribe_employee_updates')
def subscribe_employee_updates():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role not in ['admin', 'employee']:
            emit('error', {'error': 'Access denied'}, room=username)
            return
        employees = session.query(Employee).filter_by(organization_id=username).all()
        emit('employee_update', {'employees': [emp._asdict() for emp in employees]}, room=username)