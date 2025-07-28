from flask import Blueprint, render_template, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Attendance, User
from ..utils import sanitize_input, get_current_time
from datetime import timedelta

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

@analytics_bp.route('/', methods=['GET'])
@jwt_required()
def analytics():
    username = sanitize_input(get_jwt_identity())
    session = db.session
    try:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return render_template('error.html', message='Access denied', code=403), 403
        
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 30)))
        offset = (page - 1) * per_page
        end_date = get_current_time().date()
        start_date = end_date - timedelta(days=30)
        total_dates = session.query(db.func.count(db.distinct(Attendance.date))).filter(Attendance.organization_id == username, Attendance.date.between(start_date, end_date)).scalar()
        trends = session.query(Attendance.date, db.func.count(db.distinct(Attendance.employee_id)).label('active_employees')).filter(Attendance.organization_id == username, Attendance.date.between(start_date, end_date)).group_by(Attendance.date).order_by(Attendance.date).limit(per_page).offset(offset).all()
    finally:
        session.close()
    
    trends_data = [{'date': trend[0].isoformat(), 'active_employees': trend[1]} for trend in trends]
    pagination = {
        'current_page': page,
        'per_page': per_page,
        'total_items': total_dates,
        'total_pages': (total_dates + per_page - 1) // per_page
    }
    return render_template(
        'analytics.html',
        trends=trends_data,
        pagination=pagination,
        hasLoggedIn=True,
        username=username,
        userRole=user.role,
        current_year=get_current_time().year
    )