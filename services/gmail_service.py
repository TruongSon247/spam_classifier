import base64
import json
import os
import urllib.parse
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from database.db import update_email_account_credential
from services.encryption_service import decrypt_value, encrypt_value
from services.message_parser import html_to_text, normalize_date, parse_address


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = [GMAIL_READONLY_SCOPE]


class GmailConfigurationError(RuntimeError):
    pass


def _client_config():
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise GmailConfigurationError(
            "Thiếu GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET hoặc GOOGLE_REDIRECT_URI."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }, redirect_uri


def create_oauth_flow(state=None, code_verifier=None):
    config, redirect_uri = _client_config()
    flow = Flow.from_client_config(
        config,
        scopes=SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    flow.redirect_uri = redirect_uri
    return flow


def get_authorization_url():
    flow = create_oauth_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url, state, flow.code_verifier


def credentials_to_json(credentials):
    payload = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or SCOPES),
    }
    if credentials.expiry:
        payload["expiry"] = credentials.expiry.isoformat()
    return json.dumps(payload)


def exchange_callback_code(authorization_code, state, code_verifier):
    if not authorization_code:
        raise ValueError("Google không trả về authorization code.")
    if not code_verifier:
        raise ValueError("Phiên PKCE của Google không hợp lệ hoặc đã hết hạn.")
    flow = create_oauth_flow(state=state, code_verifier=code_verifier)
    # State is verified by the Flask callback. Sending only the code avoids
    # treating the local HTTP callback URL as the OAuth token transport.
    flow.fetch_token(code=authorization_code)
    return flow.credentials


def build_gmail_service(account):
    credential_info = json.loads(decrypt_value(account["credential_encrypted"]))
    credentials = Credentials.from_authorized_user_info(credential_info, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        update_email_account_credential(
            account["id"], encrypt_value(credentials_to_json(credentials))
        )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def get_gmail_profile(account=None, service=None):
    service = service or build_gmail_service(account)
    return service.users().getProfile(userId="me").execute()


def get_profile_from_credentials(credentials):
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    return service.users().getProfile(userId="me").execute()


def _decode_body(data):
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
            "utf-8", errors="replace"
        )
    except (ValueError, UnicodeError):
        return ""


def _walk_payload(part, plain_parts, html_parts):
    filename = part.get("filename") or ""
    if filename:
        return
    mime_type = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if mime_type == "text/plain" and data:
        plain_parts.append(_decode_body(data))
    elif mime_type == "text/html" and data:
        html_parts.append(_decode_body(data))
    for child in part.get("parts") or []:
        _walk_payload(child, plain_parts, html_parts)


def parse_gmail_message(message):
    payload = message.get("payload") or {}
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in payload.get("headers") or []
    }
    plain_parts = []
    html_parts = []
    _walk_payload(payload, plain_parts, html_parts)
    body_text = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if not body_text:
        body_text = html_to_text("\n".join(html_parts))
    sender_name, sender_email = parse_address(headers.get("from"))
    _, recipient_email = parse_address(headers.get("to"))
    return {
        "provider_message_id": message["id"],
        "thread_id": message.get("threadId"),
        "message_id_header": headers.get("message-id"),
        "subject": headers.get("subject", ""),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "recipient_email": recipient_email,
        "snippet": message.get("snippet", ""),
        "body_text": body_text,
        "received_at": normalize_date(headers.get("date")),
        "is_read": 0 if "UNREAD" in (message.get("labelIds") or []) else 1,
    }


def fetch_message_detail(account, gmail_message_id, service=None):
    service = service or build_gmail_service(account)
    raw = service.users().messages().get(
        userId="me", id=gmail_message_id, format="full"
    ).execute()
    return parse_gmail_message(raw)


def fetch_recent_messages(account, max_results=50):
    service = build_gmail_service(account)
    response = service.users().messages().list(
        userId="me", q="in:inbox", maxResults=min(max_results, 50)
    ).execute()
    return [
        fetch_message_detail(account, item["id"], service=service)
        for item in response.get("messages", [])
    ]


def revoke_gmail_credentials(account):
    try:
        data = json.loads(decrypt_value(account["credential_encrypted"]))
        token = data.get("refresh_token") or data.get("token")
        if not token:
            return False
        request = urllib.request.Request(
            "https://oauth2.googleapis.com/revoke",
            data=urllib.parse.urlencode({"token": token}).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=5):
            return True
    except Exception:
        return False
