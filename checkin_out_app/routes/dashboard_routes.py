from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from ..db import db
from ..models import Employee, Room, Booking, AuditLog, Guest
from ..utils import get_current_time, log_audit
from datetime import timedelta
import logging

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def log_audit(user_id, action):
    """Logs an audit event to the AuditLog table."""
    try:
        audit = AuditLog(
            employee_id=user_id if user_id and isinstance(user_id, str) and len(user_id) <= 50 else None,
            user_id=user_id,
            action=action
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to log audit for {user_id}: {str(e)}", exc_info=True)

@dashboard_bp.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    with db.session() as session:
        if current_user.role == 'admin':
            employees = session.query(Employee).all()
            rooms = session.query(Room).all()
            guests = session.query(Guest).all()
            return render_template('dashboard.html', records=employees, rooms=rooms, guests=guests)
        elif current_user.role == 'employee':
            employees = session.query(Employee).filter_by(employee_id=current_user.username).all()
            return render_template('dashboard.html', records=employees)
        elif current_user.role == 'guest':
            bookings = session.query(Booking).filter_by(guest_id=current_user.guest_id).all()
            rooms = session.query(Room).all()
            return render_template('dashboard.html', bookings=bookings, rooms=rooms)
    return render_template('dashboard.html')

@dashboard_bp.route('/add_employee', methods=['POST'])
@login_required
def add_employee():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Access denied.'}), 403
    employee_id = request.form.get('employee_id')
    name = request.form.get('name')
    email = request.form.get('email')
    role = request.form.get('role')
    fingerprint_template = request.form.get('fingerprint_template')
    if not all([employee_id, name, email, role]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400
    with db.session() as session:
        try:
            if session.query(Employee).filter_by(employee_id=employee_id).first():
                return jsonify({'success': False, 'message': 'Employee ID already exists.'}), 400
            new_employee = Employee(employee_id=employee_id, name=name, email=email, role=role, fingerprint_template=fingerprint_template)
            session.add(new_employee)
            session.commit()
            logger.info(f"Employee {employee_id} added by {current_user.username}")
            log_audit(current_user.username, f"Added employee {employee_id}")
            return jsonify({'success': True, 'message': 'Employee added successfully.'})
        except Exception as e:
            session.rollback()
            logger.error(f"Error adding employee {employee_id}: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'message': 'An error occurred while adding employee.'}), 500

@dashboard_bp.route('/delete_employee/<employee_id>', methods=['POST'])
@login_required
def delete_employee(employee_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    with db.session() as session:
        employee = session.query(Employee).filter_by(employee_id=employee_id).first()
        if employee:
            session.delete(employee)
            session.commit()
            flash('Employee deleted successfully.', 'success')
        else:
            flash('Employee not found.', 'danger')
    return redirect(url_for('dashboard.dashboard'))

@dashboard_bp.route('/book_room', methods=['POST'])
@login_required
def book_room():
    if current_user.role != 'guest':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    room_id = request.form.get('room_id')
    with db.session() as session:
        room = session.query(Room).filter_by(room_id=room_id, status='available').first()
        if room:
            booking = Booking(guest_id=current_user.guest_id, room_id=room_id, check_in_date=get_current_time(), check_out_date=get_current_time() + timedelta(days=1), status='booked')
            session.add(booking)
            room.status = 'occupied'
            session.commit()
            flash('Room booked successfully.', 'success')
        else:
            flash('Room not available.', 'danger')
    return redirect(url_for('dashboard.dashboard'))