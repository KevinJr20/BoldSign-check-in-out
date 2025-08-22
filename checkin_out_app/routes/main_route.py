from flask import Blueprint, redirect, url_for
from flask_login import login_required

main_bp = Blueprint('main', __name__, template_folder='templates')

@main_bp.route('/')
def home():
    return redirect(url_for('dashboard.dashboard'))
