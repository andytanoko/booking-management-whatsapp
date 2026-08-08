from flask import Blueprint, render_template, request, redirect, session, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required
from app.models import User, db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                if not user.active:
                    error = 'Username atau password salah.'
                    return render_template('login.html', error=error)
                    
                login_user(user)
                session['user_id'] = user.id
                session['role'] = user.role
                return redirect(url_for('dashboard'))
                
            error = 'Username atau password salah.'
        except Exception as e:
            current_app.logger.error(f'Login error: {e}')
            error = 'Terjadi kesalahan pada sistem.'
            
    return render_template('login.html', error=error)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('user_id', None)
    session.pop('role', None)
    return redirect(url_for('auth.login'))
