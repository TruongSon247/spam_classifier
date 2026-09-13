import csv
import hashlib
import unicodedata

import pandas as pd
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth import admin_required
from database.db import (
    approve_feedback,
    count_quarantined_messages_by_user,
    get_feedback_statistics,
    get_mail_message_for_user,
    get_pending_training_feedback,
    get_quarantine_statistics,
    get_quarantined_messages_by_user,
    get_training_feedback_for_review,
    is_training_text_hash_approved,
    reject_feedback,
    save_mail_feedback,
)
from routes import main_bp


FEEDBACK_DATASET_PATH = "dataset/spam_dataset.csv"


def normalize_training_text(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").split()).strip()


def feedback_training_text(feedback):
    return normalize_training_text(
        " ".join(filter(None, [
            feedback["subject"],
            feedback["body_text"] or feedback["snippet"],
        ]))
    )


@main_bp.route("/mail/message/<int:message_id>/feedback", methods=["POST"])
@login_required
def submit_mail_feedback(message_id):
    if not get_mail_message_for_user(message_id, int(current_user.id)):
        abort(403)
    try:
        save_mail_feedback(
            int(current_user.id),
            message_id,
            request.form.get("label", ""),
            request.form.get("allow_training") == "1",
        )
        flash("Đã ghi nhận phản hồi của bạn.", "success")
    except ValueError as error:
        flash(str(error), "danger")
    return redirect(url_for("mail_message_detail", message_id=message_id))


@main_bp.route("/quarantine")
@login_required
def quarantine():
    user_id = int(current_user.id)
    search = request.args.get("search", "").strip()
    selected_filter = request.args.get("filter", "all").strip().lower()
    if selected_filter not in {
        "all", "unchecked", "confirmed_spam", "false_positive", "low"
    }:
        selected_filter = "all"
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    total = count_quarantined_messages_by_user(user_id, selected_filter, search)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    return render_template(
        "quarantine.html",
        messages=get_quarantined_messages_by_user(
            user_id, selected_filter, search, page, per_page
        ),
        statistics=get_quarantine_statistics(user_id),
        search=search,
        selected_filter=selected_filter,
        page=page,
        total_pages=total_pages,
    )


@main_bp.route("/admin/feedback")
@admin_required
def admin_feedback():
    return render_template(
        "admin_feedback.html",
        feedback_items=get_pending_training_feedback(),
        statistics=get_feedback_statistics(),
    )


@main_bp.route("/admin/feedback/<int:feedback_id>/approve", methods=["POST"])
@admin_required
def approve_mail_feedback(feedback_id):
    feedback = get_training_feedback_for_review(feedback_id)
    if not feedback:
        abort(404)

    training_text = feedback_training_text(feedback)
    if not training_text:
        flash("Nội dung Email rỗng, không thể thêm vào Dataset.", "danger")
        return redirect(url_for("admin_feedback"))

    text_hash = hashlib.sha256(training_text.encode("utf-8")).hexdigest()
    duplicate = is_training_text_hash_approved(text_hash)
    try:
        dataset = pd.read_csv(FEEDBACK_DATASET_PATH)
        if not {"label", "text"}.issubset(dataset.columns):
            raise ValueError("Dataset phải có hai cột label và text.")
        if not duplicate:
            duplicate = any(
                normalize_training_text(str(value)) == training_text
                for value in dataset["text"].dropna()
            )
        if not duplicate:
            with open(
                FEEDBACK_DATASET_PATH, "a+", encoding="utf-8", newline=""
            ) as file:
                file.seek(0)
                existing_content = file.read()
                if existing_content and not existing_content.endswith(("\n", "\r")):
                    file.write("\n")
                csv.writer(file).writerow(
                    [feedback["corrected_label"], training_text]
                )
        if not approve_feedback(feedback_id, int(current_user.id), text_hash):
            raise ValueError("Phản hồi đã được xử lý trước đó.")
    except (OSError, pd.errors.ParserError, ValueError) as error:
        flash(f"Không thể duyệt phản hồi: {error}", "danger")
        return redirect(url_for("admin_feedback"))

    if duplicate:
        flash("Đã duyệt; nội dung trùng nên không append lại Dataset.", "info")
    else:
        flash(
            "Đã duyệt và bổ sung Email vào Dataset. Model cần train lại.",
            "success",
        )
    return redirect(url_for("admin_feedback"))


@main_bp.route("/admin/feedback/<int:feedback_id>/reject", methods=["POST"])
@admin_required
def reject_mail_feedback(feedback_id):
    if not reject_feedback(feedback_id, int(current_user.id)):
        abort(404)
    flash("Đã từ chối phản hồi. Dataset không thay đổi.", "info")
    return redirect(url_for("admin_feedback"))
