from flask import Blueprint, render_template, current_app, redirect, url_for
from flask_login import login_required, current_user
from ..db import db
from ..models import User, Employee, Attendance, Room, Booking, Guest, Transaction

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@dashboard_bp.route('/')
@login_required
def dashboard():
    try:
        # Access current user
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        # Use raw count queries to avoid column selection issues
        total_users = db.session.query(User).count()
        total_employees = db.session.query(Employee).count()
        total_attendance = db.session.query(Attendance).count()
        total_rooms = db.session.query(Room).count()
        total_bookings = db.session.query(Booking).count()
        total_guests = db.session.query(Guest).count()
        total_transactions = db.session.query(Transaction).count()

        return render_template('dashboard.html',
                              total_users=total_users,
                              total_employees=total_employees,
                              total_attendance=total_attendance,
                              total_rooms=total_rooms,
                              total_bookings=total_bookings,
                              total_guests=total_guests,
                              total_transactions=total_transactions,
                              config=current_app.config,
                              current_year=current_app.config.get('CURRENT_YEAR', 2025))
    except Exception as e:
        print(f"Dashboard error: {str(e)}")
        return str(e), 500