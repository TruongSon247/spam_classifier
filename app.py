from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash
import click
import csv
import getpass
import hashlib
import json
import pandas as pd
import os
import unicodedata
import uuid
from dotenv import load_dotenv

load_dotenv()

from auth import User, admin_required, login_manager
from database.db import (
    count_active_admins,
    create_user,
    create_email_account,
    disconnect_email_account,
    get_email_account_for_user,
    get_email_accounts_by_user,
    get_all_users,
    get_connection,
    get_user_by_email,
    get_user_by_id,
    get_mail_message_for_user,
    get_mail_messages_by_user,
    get_mail_statistics,
    count_mail_messages_by_user,
    count_quarantined_messages_by_user,
    get_feedback_by_message,
    get_feedback_statistics,
    get_pending_training_feedback,
    get_quarantine_statistics,
    get_quarantined_messages_by_user,
    get_training_feedback_for_review,
    init_db,
    approve_feedback,
    is_training_text_hash_approved,
    reject_feedback,
    save_mail_feedback,
    save_prediction as save_prediction_to_db,
    set_user_active,
    update_last_login,
    update_user_role,
)
from ml.predict import predict_batch_emails, predict_email
from ml.compare_models import compare_models
from ml.train import train_model
from ml.evaluate import evaluate_model
from services.encryption_service import (
    CredentialConfigurationError,
    encrypt_value,
)
from services.gmail_service import (
    GmailConfigurationError,
    credentials_to_json,
    exchange_callback_code,
    get_authorization_url,
    get_profile_from_credentials,
    revoke_gmail_credentials,
)
from services.imap_service import IMAPConnectionError, test_imap_connection
from services.mail_service import ModelUnavailableError, sync_email_account


FEEDBACK_DATASET_PATH = "dataset/spam_dataset.csv"


def normalize_training_text(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").split()).strip()


def feedback_training_text(feedback):
    return normalize_training_text(
        " ".join(filter(None, [feedback["subject"], feedback["body_text"] or feedback["snippet"]]))
    )

def get_model_status():

    dataset_path = FEEDBACK_DATASET_PATH
    preprocessing_path = "ml/preprocessing.py"
    train_path = "ml/train.py"
    model_path = "model/model.pkl"
    vectorizer_path = "model/vectorizer.pkl"

    if (
        not os.path.exists(model_path)
        or not os.path.exists(vectorizer_path)
    ):
        return {
            "trained": False,
            "outdated": True,
            "message": "Mô hình chưa được huấn luyện."
        }

    try:
        model_time = min(
            os.path.getmtime(model_path),
            os.path.getmtime(vectorizer_path)
        )
        source_times = [
            os.path.getmtime(path)
            for path in (dataset_path, preprocessing_path, train_path)
            if os.path.exists(path)
        ]
        outdated = max(source_times) > model_time

        if outdated:
            message = (
                "Dataset hoặc cấu hình AI đã thay đổi. "
                "Cần huấn luyện lại mô hình."
            )
        else:
            message = "Mô hình đã sẵn sàng."

        return {
            "trained": True,
            "outdated": outdated,
            "message": message
        }
    except (OSError, ValueError) as error:
        print("Model status error:", error)
        return {
            "trained": False,
            "outdated": True,
            "message": "Không thể kiểm tra trạng thái mô hình."
        }


def get_model_info():

    path = "model/model_info.json"

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as metadata_file:
            return json.load(metadata_file)
    except (OSError, json.JSONDecodeError):
        return None


def get_prediction_statistics(user_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    where_clause = ""
    params = ()
    if user_id is not None:
        where_clause = "WHERE user_id = ?"
        params = (user_id,)

    cursor.execute("""
        SELECT
            COUNT(*) AS total_predictions,
            COALESCE(SUM(CASE WHEN prediction = 'spam' THEN 1 ELSE 0 END), 0)
                AS spam_predictions,
            COALESCE(SUM(CASE WHEN prediction = 'ham' THEN 1 ELSE 0 END), 0)
                AS ham_predictions
        FROM predictions
        {where_clause}
    """.format(where_clause=where_clause), params)
    counts = cursor.fetchone()

    cursor.execute("""
        SELECT *
        FROM predictions
        {where_clause}
        ORDER BY id DESC
        LIMIT 5
    """.format(where_clause=where_clause), params)
    recent_predictions = cursor.fetchall()

    conn.close()

    return {
        "total_predictions": counts["total_predictions"],
        "spam_predictions": counts["spam_predictions"],
        "ham_predictions": counts["ham_predictions"],
        "recent_predictions": recent_predictions
    }

def save_prediction(subject, message, result, user_id):
    save_prediction_to_db(
        subject,
        message,
        result["prediction"],
        result["spam_probability"],
        result["ham_probability"],
        user_id,
    )


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY",
    os.environ.get(
        "SECRET_KEY",
        "dev-change-this-secret-key",
    ),
)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
login_manager.init_app(app)

init_db()


@app.cli.command("create-admin")
def create_admin_command():
    """Create the first administrator without storing a plain-text password."""
    name = click.prompt("Tên Admin").strip()
    email = click.prompt("Email").strip().lower()
    click.echo(
        "Lưu ý: mật khẩu sẽ không hiện ký tự hoặc dấu * khi nhập. "
        "Hãy gõ bình thường rồi nhấn Enter."
    )
    try:
        password = getpass.getpass("Mật khẩu (tối thiểu 8 ký tự): ")
        confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    except (EOFError, KeyboardInterrupt) as error:
        raise click.ClickException(
            "Không thể đọc mật khẩu. Hãy chạy lệnh trong Terminal PowerShell "
            "của VS Code, không chạy trong Output hoặc Debug Console."
        ) from error

    if password != confirmation:
        raise click.ClickException("Mật khẩu xác nhận không khớp.")
    try:
        create_user(name, email, password, "admin")
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Đã tạo tài khoản Admin: {email}")


@app.context_processor
def inject_global_data():

    return {
        "global_model_status": get_model_status()
    }


@app.route("/login", methods=["GET", "POST"])
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


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Bạn đã đăng xuất khỏi hệ thống.", "success")
    return redirect(url_for("login"))


@app.route("/mail")
@login_required
def mail():
    user_id = int(current_user.id)
    search = request.args.get("search", "").strip()
    selected_filter = request.args.get("filter", "all").strip().lower()
    if selected_filter not in {"all", "spam", "ham", "low"}:
        selected_filter = "all"
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    total_messages = count_mail_messages_by_user(
        user_id, selected_filter, search
    )
    total_pages = max(1, (total_messages + per_page - 1) // per_page)
    page = min(page, total_pages)
    messages = get_mail_messages_by_user(
        user_id, selected_filter, search, page, per_page
    )
    return render_template(
        "mail.html",
        accounts=get_email_accounts_by_user(user_id),
        messages=messages,
        statistics=get_mail_statistics(user_id),
        search=search,
        selected_filter=selected_filter,
        page=page,
        total_pages=total_pages,
        model_status=get_model_status(),
    )


@app.route("/mail/message/<int:message_id>")
@login_required
def mail_message_detail(message_id):
    message = get_mail_message_for_user(message_id, int(current_user.id))
    if not message:
        flash("Không tìm thấy Email hoặc bạn không có quyền truy cập.", "danger")
        return redirect(url_for("mail"))
    return render_template(
        "mail_detail.html",
        message=message,
        feedback=get_feedback_by_message(int(current_user.id), message_id),
    )


@app.route("/mail/message/<int:message_id>/feedback", methods=["POST"])
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


@app.route("/quarantine")
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
    total = count_quarantined_messages_by_user(
        user_id, selected_filter, search
    )
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


@app.route("/admin/feedback")
@admin_required
def admin_feedback():
    return render_template(
        "admin_feedback.html",
        feedback_items=get_pending_training_feedback(),
        statistics=get_feedback_statistics(),
    )


@app.route("/admin/feedback/<int:feedback_id>/approve", methods=["POST"])
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


@app.route("/admin/feedback/<int:feedback_id>/reject", methods=["POST"])
@admin_required
def reject_mail_feedback(feedback_id):
    if not reject_feedback(feedback_id, int(current_user.id)):
        abort(404)
    flash("Đã từ chối phản hồi. Dataset không thay đổi.", "info")
    return redirect(url_for("admin_feedback"))


@app.route("/mail/sync/<int:account_id>", methods=["POST"])
@login_required
def sync_mail_account(account_id):
    account = get_email_account_for_user(account_id, int(current_user.id))
    if not account:
        flash("Không tìm thấy tài khoản Email hoặc bạn không có quyền.", "danger")
        return redirect(url_for("mail"))

    model_status = get_model_status()
    if not model_status["trained"]:
        flash("Mô hình chưa được huấn luyện. Không thể phân loại Email.", "danger")
        return redirect(url_for("mail"))
    if model_status["outdated"]:
        flash("Model hiện tại cần được huấn luyện lại.", "warning")

    try:
        result = sync_email_account(account)
        if result["new"] == 0:
            flash("Không có Email mới.", "info")
        else:
            flash(
                f"Đồng bộ thành công: {result['new']} Email mới, "
                f"{result['existing']} Email đã tồn tại.",
                "success",
            )
    except (CredentialConfigurationError, GmailConfigurationError,
            IMAPConnectionError, ModelUnavailableError, ValueError) as error:
        flash(str(error), "danger")
    except Exception as error:
        print("Mailbox sync error:", type(error).__name__)
        flash("Không thể đồng bộ hộp thư. Vui lòng thử lại sau.", "danger")
    return redirect(url_for("mail"))


@app.route("/mail/disconnect/<int:account_id>", methods=["POST"])
@login_required
def disconnect_mail_account(account_id):
    user_id = int(current_user.id)
    account = get_email_account_for_user(account_id, user_id)
    if not account:
        flash("Không tìm thấy tài khoản Email hoặc bạn không có quyền.", "danger")
        return redirect(url_for("mail"))
    if account["provider"] == "gmail":
        revoke_gmail_credentials(account)
    disconnect_email_account(account_id, user_id)
    flash("Đã ngắt kết nối. Email đã đồng bộ vẫn được giữ lại.", "success")
    return redirect(url_for("mail"))


@app.route("/mail/connect/imap", methods=["GET", "POST"])
@login_required
def connect_imap():
    values = {
        "email_address": "",
        "imap_host": "",
        "imap_port": "993",
        "imap_username": "",
        "display_name": "",
    }
    if request.method == "POST":
        values = {
            key: request.form.get(key, "").strip()
            for key in values
        }
        password = request.form.get("app_password", "")
        try:
            try:
                port = int(values["imap_port"])
            except (TypeError, ValueError) as error:
                raise ValueError("Cổng IMAP phải là một số từ 1-65535.") from error
            if not 1 <= port <= 65535:
                raise ValueError("Cổng IMAP phải nằm trong khoảng 1-65535.")
            if not all((values["email_address"], values["imap_host"],
                        values["imap_username"], password)):
                raise ValueError("Vui lòng nhập đầy đủ thông tin kết nối IMAP.")
            test_imap_connection(
                values["imap_host"], port, values["imap_username"], password
            )
            credential = encrypt_value(password)
            create_email_account(
                int(current_user.id), "imap", values["email_address"], credential,
                values["display_name"], values["imap_host"], port,
                values["imap_username"],
            )
            flash("Kết nối tài khoản IMAP thành công.", "success")
            return redirect(url_for("mail"))
        except (ValueError, IMAPConnectionError,
                CredentialConfigurationError) as error:
            flash(str(error), "danger")
    return render_template("connect_imap.html", values=values)


@app.route("/mail/google/connect")
@login_required
def connect_google():
    try:
        authorization_url, state, code_verifier = get_authorization_url()
        session["google_oauth_state"] = state
        session["google_oauth_user_id"] = int(current_user.id)
        session["google_oauth_code_verifier"] = code_verifier
        return redirect(authorization_url)
    except (GmailConfigurationError, CredentialConfigurationError) as error:
        flash(str(error), "danger")
        return redirect(url_for("mail"))


@app.route("/mail/google/callback")
@login_required
def google_callback():
    expected_state = session.pop("google_oauth_state", None)
    oauth_user_id = session.pop("google_oauth_user_id", None)
    code_verifier = session.pop("google_oauth_code_verifier", None)
    received_state = request.args.get("state")
    if (
        not expected_state
        or received_state != expected_state
        or oauth_user_id != int(current_user.id)
        or not code_verifier
    ):
        flash("Phiên kết nối Google không hợp lệ hoặc đã hết hạn.", "danger")
        return redirect(url_for("mail"))
    if request.args.get("error"):
        flash("Bạn đã hủy quyền truy cập Gmail.", "warning")
        return redirect(url_for("mail"))
    stage = "token_exchange"
    try:
        credentials = exchange_callback_code(
            request.args.get("code", ""), expected_state, code_verifier
        )
        stage = "gmail_profile"
        profile = get_profile_from_credentials(credentials)
        email_address = profile.get("emailAddress", "").strip().lower()
        if not email_address:
            raise ValueError("Google không trả về địa chỉ Gmail.")
        stage = "credential_encryption"
        credential = encrypt_value(credentials_to_json(credentials))
        stage = "database_save"
        create_email_account(
            int(current_user.id), "gmail", email_address, credential,
            display_name=email_address,
        )
        flash("Kết nối Gmail thành công.", "success")
    except (GmailConfigurationError, CredentialConfigurationError,
            ValueError) as error:
        flash(str(error), "danger")
    except Exception as error:
        response = getattr(error, "response", None)
        api_response = getattr(error, "resp", None)
        status = (
            getattr(response, "status_code", None)
            or getattr(api_response, "status", None)
        )
        app.logger.error(
            "Google OAuth failed at %s: %s (HTTP %s)",
            stage,
            type(error).__name__,
            status or "unknown",
        )
        stage_messages = {
            "token_exchange": (
                "Không thể đổi mã xác thực với Google. "
                "Hãy kiểm tra Client Secret và thử kết nối lại."
            ),
            "gmail_profile": (
                "Đã xác thực nhưng Gmail API từ chối đọc hồ sơ. "
                "Hãy kiểm tra Gmail API đã được bật trong Google Cloud."
            ),
            "credential_encryption": (
                "Không thể mã hóa credential. Hãy kiểm tra Fernet key."
            ),
            "database_save": "Không thể lưu kết nối Gmail vào database.",
        }
        suffix = f" (HTTP {status})" if status else ""
        flash(stage_messages[stage] + suffix, "danger")
    return redirect(url_for("mail"))


@app.route("/users")
@admin_required
def users():
    return render_template("users.html", users=get_all_users())


@app.route("/users/create", methods=["POST"])
@admin_required
def create_user_route():
    try:
        create_user(
            request.form.get("name", ""),
            request.form.get("email", ""),
            request.form.get("password", ""),
            request.form.get("role", "user"),
        )
        flash("Đã tạo tài khoản mới.", "success")
    except ValueError as error:
        flash(str(error), "danger")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_user_active(user_id):
    row = get_user_by_id(user_id)
    if not row:
        flash("Không tìm thấy tài khoản.", "danger")
    elif user_id == int(current_user.id):
        flash("Bạn không thể vô hiệu hóa tài khoản đang đăng nhập.", "danger")
    elif row["role"] == "admin" and row["is_active"] and count_active_admins() <= 1:
        flash("Hệ thống phải còn ít nhất một Admin đang hoạt động.", "danger")
    else:
        set_user_active(user_id, not bool(row["is_active"]))
        flash("Đã cập nhật trạng thái tài khoản.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def change_user_role(user_id):
    row = get_user_by_id(user_id)
    role = request.form.get("role", "").strip().lower()
    if not row:
        flash("Không tìm thấy tài khoản.", "danger")
    elif role not in {"admin", "user"}:
        flash("Vai trò không hợp lệ.", "danger")
    elif (
        user_id == int(current_user.id)
        and role == "user"
        and count_active_admins(exclude_user_id=user_id) == 0
    ):
        flash("Không thể hạ quyền Admin cuối cùng của hệ thống.", "danger")
    else:
        update_user_role(user_id, role)
        flash("Đã cập nhật vai trò tài khoản.", "success")
    return redirect(url_for("users"))


@app.route("/")
@login_required
def index():

    df = pd.read_csv("dataset/spam_dataset.csv")

    # Chuẩn hóa label
    df["label"] = df["label"].str.lower().str.strip()

    total = len(df)

    spam_count = len(
        df[df["label"] == "spam"]
    )

    ham_count = len(
        df[df["label"] == "ham"]
    )

    # Giá trị mặc định
    accuracy = 0
    precision = 0
    recall = 0
    f1 = 0

    tn = 0
    fp = 0
    fn = 0
    tp = 0

    try:

        evaluation = evaluate_model()

        accuracy = round(
            evaluation["accuracy"] * 100,
            2
        )

        precision = round(
            evaluation["precision"] * 100,
            2
        )

        recall = round(
            evaluation["recall"] * 100,
            2
        )

        f1 = round(
            evaluation["f1"] * 100,
            2
        )

        tn = evaluation["tn"]
        fp = evaluation["fp"]
        fn = evaluation["fn"]
        tp = evaluation["tp"]

    except Exception:
        pass

    model_status = get_model_status()
    statistics_user_id = None
    if current_user.role != "admin":
        statistics_user_id = int(current_user.id)
    prediction_stats = get_prediction_statistics(statistics_user_id)

    return render_template(
        "index.html",
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1=f1,
        tn=tn,
        fp=fp,
        fn=fn,
        tp=tp,
        model_status=model_status,
        total_predictions=prediction_stats["total_predictions"],
        spam_predictions=prediction_stats["spam_predictions"],
        ham_predictions=prediction_stats["ham_predictions"],
        recent_predictions=prediction_stats["recent_predictions"]
    )

@app.route("/predict", methods=["GET", "POST"])
@login_required
def predict():

    result = None
    subject = ""
    message = ""
    error = None

    if request.method == "POST":

        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        if not message:

            error = "Vui lòng nhập nội dung email."

        else:

            result = predict_email(message)

            if result is None:

                error = (
                    "Mô hình chưa được huấn luyện. "
                    "Vui lòng vào trang Huấn luyện trước."
                )

            else:

                save_prediction(
                    subject,
                    message,
                    result,
                    int(current_user.id),
                )

    model_status = get_model_status()

    return render_template(
        "predict.html",
        result=result,
        subject=subject,
        message=message,
        error=error,
        model_status=model_status
    )


@app.route("/predict/batch", methods=["GET", "POST"])
@login_required
def batch_predict():
    results = None
    total = 0
    spam_count = 0
    ham_count = 0
    download_file = None
    error = None
    model_status = get_model_status()

    if request.method == "POST":
        if not model_status["trained"]:
            error = "Mô hình chưa được huấn luyện."
        elif "file" not in request.files:
            error = "Vui lòng chọn file CSV."
        else:
            file = request.files["file"]

            if file.filename == "":
                error = "Vui lòng chọn file CSV."
            elif not file.filename.lower().endswith(".csv"):
                error = "Chỉ chấp nhận file định dạng CSV."
            else:
                try:
                    df = pd.read_csv(file)

                    if "text" not in df.columns:
                        error = "File CSV phải có cột 'text'."
                    else:
                        if "subject" not in df.columns:
                            df["subject"] = ""

                        df = df[["subject", "text"]].copy()
                        df["subject"] = (
                            df["subject"].fillna("").astype(str).str.strip()
                        )
                        df["text"] = (
                            df["text"].fillna("").astype(str).str.strip()
                        )
                        df = df[df["text"] != ""].reset_index(drop=True)

                        max_batch_rows = 500
                        if len(df) == 0:
                            error = "File CSV không có Email hợp lệ."
                        elif len(df) > max_batch_rows:
                            error = (
                                f"Chỉ cho phép tối đa {max_batch_rows} "
                                "Email mỗi lần."
                            )
                        else:
                            predictions = predict_batch_emails(
                                df["text"].tolist()
                            )

                            if predictions is None:
                                error = "Không thể tải mô hình dự đoán."
                            else:
                                df["prediction"] = [
                                    item["prediction"] for item in predictions
                                ]
                                df["spam_probability"] = [
                                    round(item["spam_probability"] * 100, 2)
                                    for item in predictions
                                ]
                                df["ham_probability"] = [
                                    round(item["ham_probability"] * 100, 2)
                                    for item in predictions
                                ]
                                df["confidence"] = [
                                    round(item["confidence"] * 100, 2)
                                    for item in predictions
                                ]

                                total = len(df)
                                spam_count = int(
                                    df["prediction"].str.lower().eq("spam").sum()
                                )
                                ham_count = int(
                                    df["prediction"].str.lower().eq("ham").sum()
                                )

                                os.makedirs("temp", exist_ok=True)
                                download_file = (
                                    f"batch_result_{uuid.uuid4()}.csv"
                                )
                                df.to_csv(
                                    os.path.join("temp", download_file),
                                    index=False,
                                    encoding="utf-8-sig"
                                )
                                results = df.to_dict(orient="records")
                except (OSError, UnicodeError, pd.errors.ParserError) as error_detail:
                    print("Batch prediction error:", error_detail)
                    error = (
                        "Không thể xử lý file CSV. "
                        "Hãy kiểm tra lại định dạng file."
                    )

    return render_template(
        "batch_predict.html",
        results=results,
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        download_file=download_file,
        error=error,
        model_status=model_status
    )


@app.route("/predict/batch/download/<filename>")
@login_required
def download_batch_result(filename):
    prefix = "batch_result_"
    suffix = ".csv"

    if not filename.startswith(prefix) or not filename.endswith(suffix):
        return "File không hợp lệ.", 400

    identifier = filename[len(prefix):-len(suffix)]
    try:
        if str(uuid.UUID(identifier)) != identifier.lower():
            raise ValueError
    except ValueError:
        return "File không hợp lệ.", 400

    return send_from_directory("temp", filename, as_attachment=True)

@app.route("/dataset")
@admin_required
def dataset():

    df = pd.read_csv("dataset/spam_dataset.csv")

    # Giữ lại vị trí dòng gốc để thao tác xóa đúng sau khi lọc.
    df = df.reset_index()

    # Nhận từ khóa tìm kiếm
    search = request.args.get("search", "").strip()

    # Nhận bộ lọc label
    label = request.args.get("label", "all")

    # Nhận số trang
    page = request.args.get("page", 1, type=int)

    # Số email mỗi trang
    per_page = 20

    # =========================
    # TÌM KIẾM
    # =========================
    if search:
        df = df[
            df["text"].str.contains(
                search,
                case=False,
                na=False
            )
        ]

    # =========================
    # LỌC SPAM / HAM
    # =========================
    if label in ["spam", "ham"]:
        df = df[df["label"] == label]

    # Tổng số email sau khi lọc
    total = len(df)

    # =========================
    # PHÂN TRANG
    # =========================
    total_pages = max(
        1,
        (total + per_page - 1) // per_page
    )

    # Không cho page vượt quá giới hạn
    if page < 1:
        page = 1

    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page

    df_page = df.iloc[start:end]

    emails = df_page.to_dict(orient="records")

    return render_template(
        "dataset.html",
        emails=emails,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        label=label,
        start_index=start
    )
@app.route(
    "/train",
    methods=["GET", "POST"]
)
@admin_required
def train():

    result = None

    df = pd.read_csv(
        "dataset/spam_dataset.csv"
    )

    total = len(df)

    spam_count = len(
        df[
            df["label"].str.lower()
            == "spam"
        ]
    )

    ham_count = len(
        df[
            df["label"].str.lower()
            == "ham"
        ]
    )


    if request.method == "POST":

        try:

            result = train_model()

            flash(
                "Huấn luyện mô hình Naïve Bayes thành công.",
                "success"
            )

        except Exception as e:

            print(
                "Training Error:",
                e
            )

            flash(
                "Có lỗi xảy ra trong quá trình huấn luyện.",
                "danger"
            )


    model_status = get_model_status()
    model_info = get_model_info()

    return render_template(
        "train.html",
        result=result,
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        model_status=model_status,
        model_info=model_info
    )

@app.route("/evaluate")
@admin_required
def evaluate():

    result = evaluate_model()

    return render_template(
        "evaluate.html",
        result=result
    )


@app.route("/compare", methods=["GET", "POST"])
@admin_required
def compare():
    comparison = None
    best_model = None
    error = None
    chart_labels = []
    chart_accuracy = []
    chart_precision = []
    chart_recall = []
    chart_f1 = []

    if request.method == "POST":
        try:
            comparison = compare_models()
            results = comparison["results"]

            if results:
                best_model = results[0]
                chart_labels = [item["short_name"] for item in results]
                chart_accuracy = [
                    round(item["accuracy"] * 100, 2) for item in results
                ]
                chart_precision = [
                    round(item["precision"] * 100, 2) for item in results
                ]
                chart_recall = [
                    round(item["recall"] * 100, 2) for item in results
                ]
                chart_f1 = [
                    round(item["f1"] * 100, 2) for item in results
                ]
        except Exception as error_detail:
            print("Compare models error:", error_detail)
            error = "Không thể thực hiện so sánh thuật toán."

    return render_template(
        "compare.html",
        comparison=comparison,
        best_model=best_model,
        error=error,
        chart_labels=chart_labels,
        chart_accuracy=chart_accuracy,
        chart_precision=chart_precision,
        chart_recall=chart_recall,
        chart_f1=chart_f1
    )

@app.route("/history")
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
        1
        for item in predictions
        if item["prediction"].lower() == "spam"
    )

    ham_predictions = sum(
        1
        for item in predictions
        if item["prediction"].lower() == "ham"
    )

    return render_template(
        "history.html",
        predictions=predictions,
        total_predictions=total_predictions,
        spam_predictions=spam_predictions,
        ham_predictions=ham_predictions
    )

@app.route(
    "/history/delete/<int:id>",
    methods=["POST"]
)
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

    return redirect(
        url_for("history")
    )

@app.route(
    "/history/delete-all",
    methods=["POST"]
)
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

    return redirect(
        url_for("history")
    )

@app.route("/algorithm")
@login_required
def algorithm():

    total = 0
    spam_count = 0
    ham_count = 0

    try:

        df = pd.read_csv(
            "dataset/spam_dataset.csv"
        )

        df = df.dropna(
            subset=["label", "text"]
        )

        df["label"] = (
            df["label"]
            .astype(str)
            .str.lower()
            .str.strip()
        )

        total = len(df)
        spam_count = len(
            df[df["label"] == "spam"]
        )
        ham_count = len(
            df[df["label"] == "ham"]
        )

    except (OSError, KeyError, ValueError) as error:

        print(
            "Algorithm dataset error:",
            error
        )

    return render_template(
        "algorithm.html",
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        model_info=get_model_info()
    )

@app.route("/dataset/add", methods=["POST"])
@admin_required
def add_dataset():

    label = request.form.get(
        "label",
        ""
    ).strip().lower()

    text = request.form.get(
        "text",
        ""
    ).strip()

    # Kiểm tra label
    if label not in ["spam", "ham"]:

        flash(
            "Nhãn email không hợp lệ.",
            "danger"
        )

        return redirect(
            url_for("dataset")
        )

    # Kiểm tra nội dung
    if not text:

        flash(
            "Nội dung email không được để trống.",
            "warning"
        )

        return redirect(
            url_for("dataset")
        )

    path = "dataset/spam_dataset.csv"

    df = pd.read_csv(path)

    new_row = pd.DataFrame([
        {
            "label": label,
            "text": text
        }
    ])

    df = pd.concat(
        [df, new_row],
        ignore_index=True
    )

    df.to_csv(
        path,
        index=False
    )

    flash(
        "Thêm email vào Dataset thành công.",
        "success"
    )

    return redirect(
        url_for("dataset")
    )

@app.route(
    "/dataset/delete/<int:index>",
    methods=["POST"]
)
@admin_required
def delete_dataset(index):

    path = "dataset/spam_dataset.csv"

    df = pd.read_csv(path)

    if 0 <= index < len(df):

        df = df.drop(
            df.index[index]
        )

        df = df.reset_index(
            drop=True
        )

        df.to_csv(
            path,
            index=False
        )

        flash(
            "Xóa email khỏi Dataset thành công.",
            "success"
        )

    else:

        flash(
            "Không tìm thấy email cần xóa.",
            "danger"
        )

    return redirect(
        url_for("dataset")
    )

@app.route(
    "/dataset/import",
    methods=["POST"]
)
@admin_required
def import_dataset():

    if "file" not in request.files:

        flash(
            "Không tìm thấy file upload.",
            "danger"
        )

        return redirect(
            url_for("dataset")
        )


    file = request.files["file"]


    if file.filename == "":

        flash(
            "Bạn chưa chọn file CSV.",
            "warning"
        )

        return redirect(
            url_for("dataset")
        )


    if not file.filename.lower().endswith(".csv"):

        flash(
            "Chỉ chấp nhận file định dạng CSV.",
            "danger"
        )

        return redirect(
            url_for("dataset")
        )


    try:

        new_df = pd.read_csv(file)


        # =====================
        # KIỂM TRA CỘT
        # =====================

        required_columns = {
            "label",
            "text"
        }

        if not required_columns.issubset(
            new_df.columns
        ):

            flash(
                "File CSV phải có hai cột: label và text.",
                "danger"
            )

            return redirect(
                url_for("dataset")
            )


        # Chỉ giữ 2 cột
        new_df = new_df[
            ["label", "text"]
        ]


        # Xóa dòng rỗng
        new_df = new_df.dropna()


        # Chuẩn hóa
        new_df["label"] = (
            new_df["label"]
            .astype(str)
            .str.lower()
            .str.strip()
        )


        new_df["text"] = (
            new_df["text"]
            .astype(str)
            .str.strip()
        )


        # Chỉ lấy spam / ham
        new_df = new_df[
            new_df["label"].isin(
                ["spam", "ham"]
            )
        ]


        # Xóa email text rỗng
        new_df = new_df[
            new_df["text"] != ""
        ]


        imported_count = len(new_df)


        if imported_count == 0:

            flash(
                "Không có dữ liệu SPAM/HAM hợp lệ trong file.",
                "warning"
            )

            return redirect(
                url_for("dataset")
            )


        path = "dataset/spam_dataset.csv"

        old_df = pd.read_csv(path)


        final_df = pd.concat(
            [
                old_df,
                new_df
            ],
            ignore_index=True
        )


        final_df.to_csv(
            path,
            index=False
        )


        flash(
            f"Import thành công {imported_count} email.",
            "success"
        )


    except Exception as e:

        print(
            "Lỗi Import CSV:",
            e
        )

        flash(
            "Không thể đọc file CSV. Vui lòng kiểm tra lại định dạng.",
            "danger"
        )


    return redirect(
        url_for("dataset")
    )

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
