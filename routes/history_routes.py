from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from database.db import get_connection
from routes import main_bp


@main_bp.route("/history")
@login_required
def history():
    conn = get_connection()
    if current_user.role == "admin":
        predictions = conn.execute("""
            SELECT predictions.*, users.name AS user_name, users.email AS user_email
            FROM predictions
            LEFT JOIN users ON users.id = predictions.user_id
            ORDER BY predictions.id DESC
        """).fetchall()
    else:
        predictions = conn.execute("""
            SELECT predictions.*, users.name AS user_name, users.email AS user_email
            FROM predictions
            LEFT JOIN users ON users.id = predictions.user_id
            WHERE predictions.user_id = ?
            ORDER BY predictions.id DESC
        """, (int(current_user.id),)).fetchall()
    conn.close()

    total_predictions = len(predictions)
    spam_predictions = sum(
        1 for item in predictions if item["prediction"].lower() == "spam"
    )
    ham_predictions = sum(
        1 for item in predictions if item["prediction"].lower() == "ham"
    )
    return render_template(
        "history.html",
        predictions=predictions,
        total_predictions=total_predictions,
        spam_predictions=spam_predictions,
        ham_predictions=ham_predictions,
    )


@main_bp.route("/history/delete/<int:id>", methods=["POST"])
@login_required
def delete_history(id):
    conn = get_connection()
    cursor = conn.cursor()
    if current_user.role == "admin":
        cursor.execute("DELETE FROM predictions WHERE id = ?", (id,))
    else:
        cursor.execute(
            "DELETE FROM predictions WHERE id = ? AND user_id = ?",
            (id, int(current_user.id)),
        )
    conn.commit()
    conn.close()

    if cursor.rowcount:
        flash("Đã xóa lịch sử dự đoán.", "success")
    else:
        flash("Không tìm thấy lịch sử hoặc bạn không có quyền xóa.", "danger")
    return redirect(url_for("history"))


@main_bp.route("/history/delete-all", methods=["POST"])
@login_required
def delete_all_history():
    conn = get_connection()
    cursor = conn.cursor()
    if current_user.role == "admin":
        cursor.execute("DELETE FROM predictions")
    else:
        cursor.execute(
            "DELETE FROM predictions WHERE user_id = ?",
            (int(current_user.id),),
        )
    conn.commit()
    conn.close()
    flash("Đã xóa lịch sử dự đoán trong phạm vi tài khoản.", "success")
    return redirect(url_for("history"))
