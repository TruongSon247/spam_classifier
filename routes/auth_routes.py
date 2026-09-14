from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from auth import User
from database.db import get_user_by_email, update_last_login
from extensions import limiter
from routes import main_bp
from services.audit_service import log_audit


@main_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    "5 per minute",
    methods=["POST"],
    exempt_when=lambda: current_app.testing
    and not current_app.config.get("RATELIMIT_TEST_ENABLED", False),
)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"
        row = get_user_by_email(email)

        if row and not bool(row["is_active"]):
            log_audit("LOGIN_FAILED", "auth", target_type="user", target_id=row["id"], description="Login failed: disabled account.", status="failed")
            flash("Tài khoản đã bị vô hiệu hóa. Vui lòng liên hệ Admin.", "danger")
        elif not row or not check_password_hash(row["password_hash"], password):
            log_audit("LOGIN_FAILED", "auth", target_type="user", target_id=row["id"] if row else None, description="Login failed: invalid credentials.", status="failed")
            flash("Email hoặc mật khẩu không chính xác.", "danger")
        else:
            login_user(User(row), remember=remember)
            session.permanent = True
            update_last_login(row["id"])
            log_audit("LOGIN_SUCCESS", "auth", user_id=row["id"], target_type="user", target_id=row["id"], description="Login successful.")
            next_url = request.args.get("next", "")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("index")
            return redirect(next_url)

    return render_template("login.html", email=email)


@main_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    user_id = int(current_user.id)
    log_audit("LOGOUT", "auth", user_id=user_id, target_type="user", target_id=user_id, description="User logged out.")
    logout_user()
    flash("Bạn đã đăng xuất khỏi hệ thống.", "success")
    return redirect(url_for("login"))
