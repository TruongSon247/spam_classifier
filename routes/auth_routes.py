from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from auth import User
from database.db import get_user_by_email, update_last_login
from routes import main_bp


@main_bp.route("/login", methods=["GET", "POST"])
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
            flash("Tài khoản đã bị vô hiệu hóa. Vui lòng liên hệ Admin.", "danger")
        elif not row or not check_password_hash(row["password_hash"], password):
            flash("Email hoặc mật khẩu không chính xác.", "danger")
        else:
            login_user(User(row), remember=remember)
            update_last_login(row["id"])
            next_url = request.args.get("next", "")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("index")
            return redirect(next_url)

    return render_template("login.html", email=email)


@main_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Bạn đã đăng xuất khỏi hệ thống.", "success")
    return redirect(url_for("login"))
