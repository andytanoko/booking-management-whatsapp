from flask import Flask, render_template
from flask_login import LoginManager
from app.models import db, User
from app.blueprints.auth import auth_bp
from app.blueprints.bookings import bookings_bp
from app.blueprints.whatsapp import whatsapp_bp
from app.blueprints.settings import settings_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(settings_bp)

    @app.route('/')
    @app.route('/dashboard')
    def dashboard():
        return render_template('dashboard.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
