from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, Attendance
from ..utils import sanitize_input, get_current_time

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

@analytics_bp.route('/', methods=['GET'])
@jwt_required()
def analytics():
    username = sanitize_input(get_jwt_identity())
    with db.session as session:
        user = session.query(User).filter_by(username=username).first()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Access denied'}), 403
        page = int(sanitize_input(request.args.get('page', 1)))
        per_page = int(sanitize_input(request.args.get('per_page', 30)))
        offset = (page - 1) * per_page
        end_date = get_current_time().date()
        start_date = end_date - timedelta(days=30)
        total_dates = session.query(Attendance.date.distinct().count()).filter(Attendance.date.between(start_date.isoformat(), end_date.isoformat())).scalar()
        trends = session.query(Attendance.date, db.func.count(db.distinct(Attendance.employee_id)).label('active_employees')).filter(Attendance.date.between(start_date.isoformat(), end_date.isoformat())).group_by(Attendance.date).order_by(Attendance.date).limit(per_page).offset(offset).all()
    return jsonify({
        'success': True,
        'trends': [{'date': trend[0], 'active_employees': trend[1]} for trend in trends],
        'pagination': {
            'current_page': page,
            'per_page': per_page,
            'total_items': total_dates,
            'total_pages': (total_dates + per_page - 1) // per_page
        }
    })