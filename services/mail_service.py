from database.db import save_mail_message, update_email_account_sync_time
from ml.predict import predict_batch_emails
from services.gmail_service import fetch_recent_messages
from services.imap_service import fetch_recent_imap_messages


LOW_CONFIDENCE_THRESHOLD = 0.65


class ModelUnavailableError(RuntimeError):
    pass


def sync_email_account(account):
    if account["provider"] == "gmail":
        emails = fetch_recent_messages(account, max_results=50)
    elif account["provider"] == "imap":
        emails = fetch_recent_imap_messages(account, max_results=50)
    else:
        raise ValueError("Nhà cung cấp Email không hợp lệ.")

    classification_texts = [
        (
            email_message.get("body_text")
            or " ".join(filter(None, [email_message.get("subject"), email_message.get("snippet")]))
        ).strip()
        for email_message in emails
    ]
    results = predict_batch_emails(classification_texts) if emails else []
    if results is None:
        raise ModelUnavailableError(
            "Mô hình chưa được huấn luyện. Không thể phân loại Email."
        )

    new_count = 0
    existing_count = 0
    for email_message, result in zip(emails, results):
        record = {
            **email_message,
            "user_id": account["user_id"],
            "account_id": account["id"],
            "prediction": result["prediction"],
            "spam_probability": result["spam_probability"],
            "ham_probability": result["ham_probability"],
            "confidence": result["confidence"],
            "is_quarantined": 1 if result["prediction"] == "spam" else 0,
        }
        if save_mail_message(record):
            new_count += 1
        else:
            existing_count += 1
    update_email_account_sync_time(account["id"])
    return {"new": new_count, "existing": existing_count, "total": len(emails)}
