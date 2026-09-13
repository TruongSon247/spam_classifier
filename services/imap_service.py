import imaplib
from email import policy
from email.parser import BytesParser

from services.encryption_service import decrypt_value
from services.message_parser import (
    decode_header_value,
    extract_email_body,
    normalize_date,
    parse_address,
)


class IMAPConnectionError(RuntimeError):
    pass


def _connect(host, port, username, password):
    try:
        client = imaplib.IMAP4_SSL(host, int(port), timeout=15)
        client.login(username, password)
        return client
    except (imaplib.IMAP4.error, OSError, ValueError) as error:
        raise IMAPConnectionError(
            "Không thể đăng nhập IMAP. Hãy kiểm tra máy chủ và App Password."
        ) from error


def test_imap_connection(host, port, username, password):
    client = _connect(host, port, username, password)
    try:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise IMAPConnectionError("Không thể mở thư mục INBOX ở chế độ chỉ đọc.")
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
    return True


def _parse_imap_message(raw_message, uid, flags=b""):
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    sender_name, sender_email = parse_address(message.get("From"))
    _, recipient_email = parse_address(message.get("To"))
    message_id = (message.get("Message-ID") or "").strip()
    return {
        "provider_message_id": message_id or f"imap-uid:{uid}",
        "thread_id": None,
        "message_id_header": message_id or None,
        "subject": decode_header_value(message.get("Subject")),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "recipient_email": recipient_email,
        "snippet": "",
        "body_text": extract_email_body(message),
        "received_at": normalize_date(message.get("Date")),
        "is_read": 1 if b"\\Seen" in flags else 0,
    }


def fetch_recent_imap_messages(account, max_results=50):
    password = decrypt_value(account["credential_encrypted"])
    client = _connect(
        account["imap_host"], account["imap_port"],
        account["imap_username"], password,
    )
    messages = []
    try:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise IMAPConnectionError("Không thể mở thư mục INBOX.")
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise IMAPConnectionError("Không thể đọc danh sách Email.")
        uids = (data[0] or b"").split()[-max_results:]
        for uid in reversed(uids):
            status, fetched = client.uid("fetch", uid, "(BODY.PEEK[] FLAGS)")
            if status != "OK" or not fetched:
                continue
            raw = next(
                (item[1] for item in fetched if isinstance(item, tuple) and item[1]),
                None,
            )
            flags = next(
                (item[0] for item in fetched if isinstance(item, tuple)), b""
            )
            if raw:
                messages.append(_parse_imap_message(raw, uid.decode(), flags))
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
    return messages
