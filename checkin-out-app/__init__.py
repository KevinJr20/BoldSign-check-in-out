import os
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_jwt_extended import JWTManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_assets import Environment
from flask_migrate import Migrate
from .config import configure_app
from .models import db, User
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

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()  # Define at module level

def get_remote_address():
    return request.remote_addr

def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    configure_app(app)
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', app.config['SECRET_KEY'])
    
    db.init_app(app)
    migrate.init_app(app)
    Migrate(app, db)
    socketio.init_app(app, async_mode='threading')
    jwt = JWTManager(app)  # Initialize with a variable
    login_manager = LoginManager()  # Initialize LoginManager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # Redirect to login if not authenticated
    CSRFProtect(app)
    Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")
    Environment(app)

    with app.app_context():
        db.create_all()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id)) 

    @app.context_processor
    def inject_user():
        from flask_login import current_user
        return dict(current_user=current_user)
    
    @jwt.user_identity_loader
    def user_identity_loader(user):
        return {'username': user.username, 'role': user.role}

    @jwt.user_lookup_loader
    def user_lookup_loader(jwt_header, jwt_data):
        identity = jwt_data['sub']
        return User.query.filter_by(username=identity['username']).first()

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

if __name__ == "__main__":
    app = create_app()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)