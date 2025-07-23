from .__init__ import create_app
from flask_socketio import SocketIO
if __name__ == "__main__":
    app = create_app()
    socketio = SocketIO(app, message_queue=app.config.get('REDIS_URL'), async_mode='eventlet')
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)