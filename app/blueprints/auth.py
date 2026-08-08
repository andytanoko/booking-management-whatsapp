from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required
from app.models import User, db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                if not user.active:
                    flash('Akun Anda tidak aktif.', 'danger')
                    return render_template('login.html')
                    
                login_user(user)
                return redirect(url_for('dashboard'))
                
            flash('Username atau password salah.', 'danger')
        except Exception as e:
            current_app.logger.error(f'Login error: {e}')
            flash('Terjadi kesalahan pada sistem.', 'danger')
            
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
