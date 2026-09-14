from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from requests.exceptions import RequestException

from database.db import (
    count_mail_messages_by_user,
    create_email_account,
    disconnect_email_account,
    get_email_account_for_user,
    get_email_accounts_by_user,
    get_feedback_by_message,
    get_mail_message_for_user,
    get_mail_messages_by_user,
    get_mail_statistics,
    set_mail_message_hidden,
)
from routes import main_bp
from services.application_service import get_model_status
from services.audit_service import log_audit
from services.encryption_service import CredentialConfigurationError, encrypt_value
from services.gmail_service import (
    GmailConfigurationError,
    credentials_to_json,
    exchange_callback_code,
    get_authorization_url,
    get_profile_from_credentials,
    revoke_gmail_credentials,
)
from services.imap_service import IMAPConnectionError, test_imap_connection
from services.mail_service import (
    DEFAULT_MAIL_SYNC_LIMIT,
    MAIL_SYNC_LIMITS,
    ModelUnavailableError,
    sync_email_account,
)


@main_bp.route("/mail")
@login_required
def mail():
    user_id = int(current_user.id)
    search = request.args.get("search", "").strip()
    selected_filter = request.args.get("filter", "all").strip().lower()
    if selected_filter not in {"all", "spam", "ham", "low", "hidden"}:
        selected_filter = "all"
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    total_messages = count_mail_messages_by_user(user_id, selected_filter, search)
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
        sync_limit_options=MAIL_SYNC_LIMITS,
    )


@main_bp.route("/mail/message/<int:message_id>")
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


@main_bp.post("/mail/message/<int:message_id>/hide")
@login_required
def hide_mail_message(message_id):
    user_id = int(current_user.id)
    if not set_mail_message_hidden(message_id, user_id, True):
        flash("Không tìm thấy Email hoặc bạn không có quyền.", "danger")
        return redirect(url_for("mail"))
    log_audit("MAIL_HIDE", "mail", user_id=user_id, target_type="mail_message", target_id=message_id, description=f"Hidden local mail message #{message_id}.")
    flash("Đã ẩn Email khỏi hộp thư trong hệ thống.", "success")
    return redirect(url_for("mail"))


@main_bp.post("/mail/message/<int:message_id>/unhide")
@login_required
def unhide_mail_message(message_id):
    user_id = int(current_user.id)
    if not set_mail_message_hidden(message_id, user_id, False):
        flash("Không tìm thấy Email hoặc bạn không có quyền.", "danger")
        return redirect(url_for("mail", filter="hidden"))
    log_audit("MAIL_UNHIDE", "mail", user_id=user_id, target_type="mail_message", target_id=message_id, description=f"Restored local mail message #{message_id}.")
    flash("Đã hiện lại Email trong hộp thư.", "success")
    return redirect(url_for("mail"))


@main_bp.route("/mail/sync/<int:account_id>", methods=["POST"])
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
        max_results = int(
            request.form.get("max_results", DEFAULT_MAIL_SYNC_LIMIT)
        )
    except (TypeError, ValueError):
        max_results = 0
    if max_results not in MAIL_SYNC_LIMITS:
        flash("Số lượng Email đồng bộ không hợp lệ.", "danger")
        return redirect(url_for("mail"))

    try:
        result = sync_email_account(account, max_results=max_results)
        log_audit("MAIL_SYNC", "mail", user_id=int(current_user.id), target_type="email_account", target_id=account_id, description=f"Synced {result['new']} new messages from {account['provider'].upper()}.")
        if result.get("rate_limited"):
            flash(
                f"Đã đồng bộ {result['new']} Email mới. Gmail đang tạm giới hạn "
                "số request; hãy chờ khoảng 1 phút rồi Đồng bộ tiếp.",
                "warning",
            )
        elif result["new"] == 0:
            flash("Không có Email mới.", "info")
        else:
            flash(
                f"Đồng bộ thành công: {result['new']} Email mới, "
                f"{result['existing']} Email đã tồn tại.",
                "success",
            )
    except (
        CredentialConfigurationError,
        GmailConfigurationError,
        IMAPConnectionError,
        ModelUnavailableError,
        ValueError,
    ) as error:
        current_app.logger.warning("Mail sync rejected for account_id=%s: %s", account_id, type(error).__name__)
        log_audit("MAIL_SYNC_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", target_id=account_id, description="Mailbox sync could not be completed.", status="failed")
        flash(str(error), "danger")
    except Exception:
        current_app.logger.exception("Mail sync failed for account_id=%s", account_id)
        log_audit("MAIL_SYNC_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", target_id=account_id, description="Mailbox sync could not be completed.", status="failed")
        flash("Không thể đồng bộ hộp thư. Vui lòng thử lại sau.", "danger")
    return redirect(url_for("mail"))


@main_bp.route("/mail/disconnect/<int:account_id>", methods=["POST"])
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
    log_audit("MAIL_DISCONNECT", "mail", user_id=user_id, target_type="email_account", target_id=account_id, description=f"Disconnected {account['provider'].upper()} mailbox.")
    flash("Đã ngắt kết nối. Email đã đồng bộ vẫn được giữ lại.", "success")
    return redirect(url_for("mail"))


@main_bp.route("/mail/connect/imap", methods=["GET", "POST"])
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
        values = {key: request.form.get(key, "").strip() for key in values}
        password = request.form.get("app_password", "")
        try:
            try:
                port = int(values["imap_port"])
            except (TypeError, ValueError) as error:
                raise ValueError("Cổng IMAP phải là một số từ 1-65535.") from error
            if not 1 <= port <= 65535:
                raise ValueError("Cổng IMAP phải nằm trong khoảng 1-65535.")
            if not all((
                values["email_address"],
                values["imap_host"],
                values["imap_username"],
                password,
            )):
                raise ValueError("Vui lòng nhập đầy đủ thông tin kết nối IMAP.")
            test_imap_connection(
                values["imap_host"], port, values["imap_username"], password
            )
            credential = encrypt_value(password)
            account_id = create_email_account(
                int(current_user.id),
                "imap",
                values["email_address"],
                credential,
                values["display_name"],
                values["imap_host"],
                port,
                values["imap_username"],
            )
            log_audit("MAIL_CONNECT", "mail", user_id=int(current_user.id), target_type="email_account", target_id=account_id, description="Connected IMAP mailbox.")
            flash("Kết nối tài khoản IMAP thành công.", "success")
            return redirect(url_for("mail"))
        except (
            ValueError,
            IMAPConnectionError,
            CredentialConfigurationError,
        ) as error:
            log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description="IMAP connection could not be completed.", status="failed")
            flash(str(error), "danger")
    return render_template("connect_imap.html", values=values)


@main_bp.route("/mail/google/connect")
@login_required
def connect_google():
    try:
        authorization_url, state, code_verifier = get_authorization_url()
        session["google_oauth_state"] = state
        session["google_oauth_user_id"] = int(current_user.id)
        session["google_oauth_code_verifier"] = code_verifier
        return redirect(authorization_url)
    except (GmailConfigurationError, CredentialConfigurationError) as error:
        log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description="Gmail authorization could not be started.", status="failed")
        flash(str(error), "danger")
        return redirect(url_for("mail"))


@main_bp.route("/mail/google/callback")
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
        log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description="Invalid or expired Google authorization session.", status="failed")
        flash("Phiên kết nối Google không hợp lệ hoặc đã hết hạn.", "danger")
        return redirect(url_for("mail"))
    if request.args.get("error"):
        log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description="Google authorization was cancelled.", status="failed")
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
        account_id = create_email_account(
            int(current_user.id),
            "gmail",
            email_address,
            credential,
            display_name=email_address,
        )
        log_audit("MAIL_CONNECT", "mail", user_id=int(current_user.id), target_type="email_account", target_id=account_id, description="Connected Gmail mailbox.")
        flash("Kết nối Gmail thành công.", "success")
    except (
        GmailConfigurationError,
        CredentialConfigurationError,
        ValueError,
    ) as error:
        log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description=f"Gmail connection failed during {stage}.", status="failed")
        flash(str(error), "danger")
    except RequestException as error:
        current_app.logger.error(
            "Google OAuth network failure at %s: %s",
            stage,
            type(error).__name__,
        )
        log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description=f"Gmail network failure during {stage}.", status="failed")
        flash(
            "Không thể kết nối tới máy chủ Google. "
            "Hãy kiểm tra kết nối mạng hoặc cấu hình proxy rồi thử lại.",
            "danger",
        )
    except Exception as error:
        response = getattr(error, "response", None)
        api_response = getattr(error, "resp", None)
        status = (
            getattr(response, "status_code", None)
            or getattr(api_response, "status", None)
        )
        current_app.logger.error(
            "Google OAuth failed at %s: %s (HTTP %s)",
            stage,
            type(error).__name__,
            status or "unknown",
        )
        log_audit("MAIL_CONNECT_FAILED", "mail", user_id=int(current_user.id), target_type="email_account", description=f"Gmail connection failed during {stage}.", status="failed")
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
