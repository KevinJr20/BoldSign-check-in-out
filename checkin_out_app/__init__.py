import os
from flask import Flask, request
from flask_socketio import SocketIO
from flask_jwt_extended import JWTManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_assets import Environment
from flask_migrate import Migrate
from .config import configure_app
from .routes.main_route import main_bp
from dotenv import load_dotenv
from .routes.auth_routes import auth_bp
from .routes.dashboard_routes import dashboard_bp
from .routes.employee_routes import employee_bp
from .routes.guest_routes import guest_bp
from .routes.payment_routes import payment_bp
from .routes.analytics_routes import analytics_bp
from .routes.room_routes import room_bp
from .routes.qr_routes import qr_bp
from .routes.attendance_routes import attendance_bp
from flask_login import LoginManager
from .db import db  # Import db from db.py

# Move SocketIO to module level
socketio = SocketIO()

load_dotenv()

def create_app():
    csrf = CSRFProtect()
    login_manager = LoginManager()

    app = Flask(__name__, template_folder='templates', static_folder='static')
    configure_app(app)
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', app.config['SECRET_KEY'])
    
    # Initialize extensions with app
    db.init_app(app)
    migrate = Migrate(app, db)
    socketio.init_app(app, async_mode='threading')
    jwt = JWTManager(app)
    
    
    
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    csrf.init_app(app)
    Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")
    Environment(app)
    
    @jwt.token_in_blocklist_loader
    def check_if_token_in_blocklist(jwt_header, jwt_payload):
        return False  # Placeholder; implement token revocation if needed

    # Import models after db is initialized
    from .models import User, VerificationToken, Employee, AuditLog, Attendance, Subscription, Room, Booking, Guest, Transaction, Configuration, QrCode

    @login_manager.user_loader
    def load_user(user_id):
        print(f"Loading user with user_id: {user_id}, type: {type(user_id)}")  # Debug print
        if isinstance(user_id, bool):
            print("Warning: user_id is boolean, returning None")
            return None  # Prevent invalid query
        user = db.session.get(User, str(user_id))
        if not user:
            guest = db.session.get(Guest, str(user_id))
            return guest
        return user

    @app.context_processor
    def inject_user():
        from flask_login import current_user
        return dict(current_user=current_user)
    
    @jwt.user_identity_loader
    def user_identity_loader(user):
        """Return a simple identifier for the user."""
        return user.username if hasattr(user, 'username') else user.get('guest_id') if hasattr(user, 'guest_id') else user.get('username')

    @jwt.user_lookup_loader
    def user_lookup_loader(jwt_header, jwt_data):
        """Fetch the user object based on the identity."""
        identity = jwt_data["sub"]
        user = User.query.filter_by(username=identity).first()
        if not user:
            guest = Guest.query.filter_by(guest_id=identity).first()
            return guest
        return user

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(guest_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(room_bp)
    app.register_blueprint(qr_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(main_bp)

    return app

def get_remote_address():
    return request.remote_addr

if __name__ == "__main__":
    app = create_app()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)