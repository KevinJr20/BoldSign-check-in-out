from flask import Flask
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from dotenv import load_dotenv  
import os  
from .db import db
from .models import User
from .config import configure_app

load_dotenv()

socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    configure_app(app)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://username:password@localhost/dbname')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['WTF_CSRF_SECRET_KEY'] = os.getenv('SECRET_KEY')

    db.init_app(app)
    socketio.init_app(app)

    # Initialize Flask-Migrate
    migrate = Migrate(app, db)

    # Initialize CSRFProtect
    csrf = CSRFProtect(app)
    csrf.exempt('employee')

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    from .routes.auth_routes import auth_bp
    from .routes.dashboard_routes import dashboard_bp
    from .routes.qr_routes import qr_bp
    from .routes.room_routes import room_bp
    from .routes.main_route import main_bp
    from .routes.employee_routes import employee_bp
    from .routes.guest_routes import guest_bp
    from .routes.payment_routes import payment_bp
    from .routes.analytics_routes import analytics_bp
    from .routes.attendance_routes import attendance_bp

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

if __name__ == '__main__':
    app = create_app()
    socketio.run(app, debug=True)