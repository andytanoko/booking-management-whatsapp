from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from app.services.settings_store import get_many, set_setting
from typing import Dict

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def manage_settings():
    try:
        if request.method == 'POST':
            # Logic to update settings
            flash('Pengaturan berhasil diperbarui.', 'success')
            return redirect(url_for('settings.manage_settings'))
        
        settings = get_many(['daily_capacity', 'operating_start', 'operating_end'])
        return render_template('settings/manage.html', settings=settings)
    except Exception as e:
        current_app.logger.error(f'Error in manage_settings: {e}')
        flash('Gagal memuat pengaturan.', 'danger')
        return redirect(url_for('dashboard'))

@settings_bp.route('/maintenance', methods=['GET', 'POST'])
@login_required
def maintenance():
    return render_template('settings/maintenance.html')
