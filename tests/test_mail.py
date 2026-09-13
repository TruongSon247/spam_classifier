import base64
import os
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from googleapiclient.errors import HttpError
from requests.exceptions import ProxyError

import database.db as db
from app import app
from services.encryption_service import decrypt_value, encrypt_value
from services.gmail_service import (
    exchange_callback_code,
    fetch_recent_messages,
    parse_gmail_message,
)
from services.imap_service import IMAPConnectionError
from services.mail_service import sync_email_account


class MailboxIntegrationTest(unittest.TestCase):
    def setUp(self):
        db.DB_PATH = os.path.join(os.path.dirname(__file__), "test_mail.db")
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        os.environ["CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        db.init_db()
        self.user_a = db.create_user(
            "User A", "mail-a@example.com", "Password123!", "user"
        )
        self.user_b = db.create_user(
            "User B", "mail-b@example.com", "Password123!", "user"
        )
        self.account_a = db.create_email_account(
            self.user_a, "imap", "a@example.com", encrypt_value("app-password"),
            "Inbox A", "imap.example.com", 993, "a@example.com",
        )
        self.account_b = db.create_email_account(
            self.user_b, "imap", "b@example.com", encrypt_value("app-password"),
            "Inbox B", "imap.example.com", 993, "b@example.com",
        )
        self.message_a = self._save_message(
            self.user_a, self.account_a, "a-1", "Khuyến mãi đặc biệt", "spam", 0.9
        )
        self.message_b = self._save_message(
            self.user_b, self.account_b, "b-1", "Nội bộ công ty", "ham", 0.91
        )
        app.config.update(TESTING=True, SECRET_KEY="mail-test-secret")
        self.client = app.test_client()

    def tearDown(self):
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)

    def _save_message(self, user_id, account_id, provider_id, subject, prediction, confidence):
        db.save_mail_message({
            "user_id": user_id,
            "account_id": account_id,
            "provider_message_id": provider_id,
            "subject": subject,
            "sender_name": "Người gửi",
            "sender_email": f"sender-{user_id}@example.com",
            "recipient_email": f"user-{user_id}@example.com",
            "snippet": "Nội dung xem trước",
            "body_text": "Email Unicode tiếng Việt <script>alert(1)</script>",
            "received_at": "2026-09-13T08:00:00+07:00",
            "prediction": prediction,
            "spam_probability": 0.9 if prediction == "spam" else 0.09,
            "ham_probability": 0.1 if prediction == "spam" else 0.91,
            "confidence": confidence,
            "is_read": 0,
        })
        with closing(db.get_connection()) as conn:
            return conn.execute(
                "SELECT id FROM mail_messages WHERE account_id = ? AND provider_message_id = ?",
                (account_id, provider_id),
            ).fetchone()["id"]

    def login_a(self):
        return self.client.post(
            "/login",
            data={"email": "mail-a@example.com", "password": "Password123!"},
            follow_redirects=True,
        )

    def test_routes_filters_privacy_and_disconnect(self):
        self.assertIn("/login", self.client.get("/mail").headers["Location"])
        self.assertEqual(self.login_a().status_code, 200)

        mailbox = self.client.get("/mail")
        self.assertIn("Khuyến mãi đặc biệt".encode(), mailbox.data)
        self.assertNotIn("Nội bộ công ty".encode(), mailbox.data)
        self.assertIn("Hộp thư".encode(), mailbox.data)

        self.assertIn(
            "Khuyến mãi đặc biệt".encode(),
            self.client.get("/mail?filter=spam").data,
        )
        self.assertNotIn(
            "Khuyến mãi đặc biệt".encode(),
            self.client.get("/mail?filter=ham").data,
        )
        self.assertIn(
            "Khuyến mãi đặc biệt".encode(),
            self.client.get("/mail?search=khuyến").data,
        )
        self.assertNotIn(
            "Khuyến mãi đặc biệt".encode(),
            self.client.get("/mail?search=không-tồn-tại").data,
        )

        own_detail = self.client.get(f"/mail/message/{self.message_a}")
        self.assertEqual(own_detail.status_code, 200)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", own_detail.data)
        foreign_detail = self.client.get(
            f"/mail/message/{self.message_b}", follow_redirects=True
        )
        self.assertNotIn("Nội bộ công ty".encode(), foreign_detail.data)

        with patch("routes.mail_routes.sync_email_account") as sync_mock:
            self.client.post(f"/mail/sync/{self.account_b}")
            sync_mock.assert_not_called()
        self.client.post(f"/mail/disconnect/{self.account_b}")
        self.assertIsNotNone(db.get_email_account_for_user(self.account_b, self.user_b))

        self.client.post(f"/mail/disconnect/{self.account_a}")
        disconnected = db.get_email_account_for_user(
            self.account_a, self.user_a, active_only=False
        )
        self.assertEqual(disconnected["is_active"], 0)
        self.assertIsNone(disconnected["credential_encrypted"])
        self.assertIsNotNone(db.get_mail_message_for_user(self.message_a, self.user_a))

    def test_imap_connect_validation_and_encryption(self):
        self.login_a()
        form = {
            "email_address": "new@example.com",
            "display_name": "New Mail",
            "imap_host": "imap.example.com",
            "imap_port": "993",
            "imap_username": "new@example.com",
            "app_password": "secret-app-password",
        }
        with patch(
            "routes.mail_routes.test_imap_connection",
            side_effect=IMAPConnectionError("Sai App Password."),
        ):
            response = self.client.post(
                "/mail/connect/imap", data=form, follow_redirects=True
            )
        self.assertIn("Sai App Password".encode(), response.data)
        self.assertEqual(len(db.get_email_accounts_by_user(self.user_a)), 1)

        with patch("routes.mail_routes.test_imap_connection", return_value=True):
            response = self.client.post(
                "/mail/connect/imap", data=form, follow_redirects=True
            )
        self.assertEqual(response.status_code, 200)
        account = next(
            item for item in db.get_email_accounts_by_user(self.user_a)
            if item["email_address"] == "new@example.com"
        )
        self.assertNotEqual(account["credential_encrypted"], form["app_password"])
        self.assertEqual(decrypt_value(account["credential_encrypted"]), form["app_password"])

    def test_sync_does_not_duplicate(self):
        account = db.get_email_account_for_user(self.account_a, self.user_a)
        email_data = [{
            "provider_message_id": "stable-id",
            "thread_id": None,
            "message_id_header": "<stable@example.com>",
            "subject": "Meeting tomorrow",
            "sender_name": "An",
            "sender_email": "an@example.com",
            "recipient_email": "a@example.com",
            "snippet": "Meeting",
            "body_text": "Please send the report tomorrow",
            "received_at": "2026-09-13T09:00:00+07:00",
            "is_read": 0,
        }]
        prediction = [{
            "prediction": "ham",
            "spam_probability": 0.1,
            "ham_probability": 0.9,
            "confidence": 0.9,
        }]
        with patch(
            "services.mail_service.fetch_recent_imap_messages",
            return_value=email_data,
        ) as fetch_mock, patch(
            "services.mail_service.predict_batch_emails", return_value=prediction
        ):
            first = sync_email_account(account, max_results=200)
            second = sync_email_account(account)
        self.assertEqual(
            first,
            {"new": 1, "existing": 0, "total": 1, "rate_limited": False},
        )
        self.assertEqual(
            second,
            {"new": 0, "existing": 1, "total": 1, "rate_limited": False},
        )
        self.assertEqual(fetch_mock.call_args_list[0].kwargs["max_results"], 200)
        self.assertEqual(fetch_mock.call_args_list[1].kwargs["max_results"], 50)

    def test_gmail_skips_existing_messages_and_handles_rate_limit(self):
        service = Mock()
        service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "known"}, {"id": "new"}, {"id": "limited"}]
        }
        response = Mock(status=403, reason="Forbidden")
        quota_error = HttpError(
            response,
            b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}',
        )
        with patch(
            "services.gmail_service.build_gmail_service", return_value=service
        ), patch(
            "services.gmail_service.fetch_message_detail",
            side_effect=[{"provider_message_id": "new"}, quota_error],
        ) as detail_mock:
            result = fetch_recent_messages(
                {"id": self.account_a},
                max_results=300,
                excluded_ids={"known"},
            )
        self.assertEqual([item["provider_message_id"] for item in result], ["new"])
        self.assertEqual(result.skipped_existing, 1)
        self.assertTrue(result.rate_limited)
        self.assertEqual(detail_mock.call_count, 2)
        list_call = service.users.return_value.messages.return_value.list.call_args
        self.assertEqual(list_call.kwargs["maxResults"], 300)

    def test_sync_limit_is_selected_and_validated(self):
        self.login_a()
        mailbox = self.client.get("/mail")
        for limit in (50, 100, 200, 300, 500):
            self.assertIn(f'value="{limit}"'.encode(), mailbox.data)

        ready_model = {"trained": True, "outdated": False, "message": "ready"}
        with patch(
            "routes.mail_routes.get_model_status", return_value=ready_model
        ), patch(
            "routes.mail_routes.sync_email_account",
            return_value={"new": 0, "existing": 0, "total": 0},
        ) as sync_mock:
            response = self.client.post(
                f"/mail/sync/{self.account_a}",
                data={"max_results": "300"},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        sync_mock.assert_called_once()
        self.assertEqual(sync_mock.call_args.kwargs["max_results"], 300)

        with patch(
            "routes.mail_routes.get_model_status", return_value=ready_model
        ), patch("routes.mail_routes.sync_email_account") as sync_mock:
            invalid = self.client.post(
                f"/mail/sync/{self.account_a}",
                data={"max_results": "999"},
                follow_redirects=True,
            )
        sync_mock.assert_not_called()
        self.assertIn("không hợp lệ".encode(), invalid.data)

    def test_gmail_html_fallback_is_plain_text(self):
        html_body = base64.urlsafe_b64encode(
            b"<p>Xin chao <b>ban</b></p><script>alert('x')</script>"
        ).decode()
        parsed = parse_gmail_message({
            "id": "gmail-1",
            "threadId": "thread-1",
            "snippet": "Xin chao",
            "payload": {
                "mimeType": "text/html",
                "headers": [
                    {"name": "Subject", "value": "Unicode Gmail"},
                    {"name": "From", "value": "Sender <sender@example.com>"},
                ],
                "body": {"data": html_body},
            },
        })
        self.assertIn("Xin chao ban", parsed["body_text"])
        self.assertNotIn("script", parsed["body_text"])
        self.assertNotIn("alert", parsed["body_text"])

    def test_google_oauth_state_and_encrypted_storage(self):
        self.login_a()
        with patch(
            "routes.mail_routes.get_authorization_url",
            return_value=(
                "https://accounts.google.test/auth",
                "secure-state",
                "pkce-verifier",
            ),
        ):
            response = self.client.get("/mail/google/connect")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://accounts.google.test/auth")

        invalid = self.client.get(
            "/mail/google/callback?state=wrong-state", follow_redirects=True
        )
        self.assertIn("không hợp lệ".encode(), invalid.data)
        self.assertFalse(any(
            account["provider"] == "gmail"
            for account in db.get_email_accounts_by_user(self.user_a)
        ))

        with self.client.session_transaction() as flask_session:
            flask_session["google_oauth_state"] = "secure-state"
            flask_session["google_oauth_user_id"] = self.user_a
            flask_session["google_oauth_code_verifier"] = "pkce-verifier"
        with patch("routes.mail_routes.exchange_callback_code", return_value=Mock()), patch(
            "routes.mail_routes.get_profile_from_credentials",
            return_value={"emailAddress": "oauth@gmail.com"},
        ), patch("routes.mail_routes.credentials_to_json", return_value="serialized-token"):
            valid = self.client.get(
                "/mail/google/callback?state=secure-state&code=test",
                follow_redirects=True,
            )
        self.assertIn("Kết nối Gmail thành công".encode(), valid.data)
        gmail = next(
            account for account in db.get_email_accounts_by_user(self.user_a)
            if account["provider"] == "gmail"
        )
        self.assertNotEqual(gmail["credential_encrypted"], "serialized-token")
        self.assertEqual(decrypt_value(gmail["credential_encrypted"]), "serialized-token")

    def test_google_token_exchange_does_not_parse_local_http_url(self):
        flow = Mock()
        flow.credentials = Mock()
        with patch(
            "services.gmail_service.create_oauth_flow", return_value=flow
        ) as flow_factory:
            credentials = exchange_callback_code(
                "authorization-code", "secure-state", "pkce-verifier"
            )
        flow_factory.assert_called_once_with(
            state="secure-state", code_verifier="pkce-verifier"
        )
        flow.fetch_token.assert_called_once_with(code="authorization-code")
        self.assertIs(credentials, flow.credentials)

    def test_google_callback_reports_network_error_accurately(self):
        self.login_a()
        with self.client.session_transaction() as flask_session:
            flask_session["google_oauth_state"] = "network-state"
            flask_session["google_oauth_user_id"] = self.user_a
            flask_session["google_oauth_code_verifier"] = "pkce-verifier"
        with patch(
            "routes.mail_routes.exchange_callback_code",
            side_effect=ProxyError("blocked proxy"),
        ):
            response = self.client.get(
                "/mail/google/callback?state=network-state&code=test",
                follow_redirects=True,
            )
        self.assertIn("kết nối tới máy chủ Google".encode(), response.data)
        self.assertNotIn("Client Secret".encode(), response.data)

    def test_model_status_controls_sync_and_low_confidence_filter(self):
        low_id = self._save_message(
            self.user_a, self.account_a, "a-low", "Cần kiểm tra", "ham", 0.55
        )
        self.assertGreater(low_id, 0)
        self.login_a()
        low_page = self.client.get("/mail?filter=low")
        self.assertIn("Cần kiểm tra".encode(), low_page.data)
        self.assertNotIn("Khuyến mãi đặc biệt".encode(), low_page.data)

        with patch(
            "routes.mail_routes.get_model_status",
            return_value={"trained": False, "outdated": True, "message": "missing"},
        ), patch("routes.mail_routes.sync_email_account") as sync_mock:
            missing = self.client.post(
                f"/mail/sync/{self.account_a}", follow_redirects=True
            )
        sync_mock.assert_not_called()
        self.assertIn("chưa được huấn luyện".encode(), missing.data)

        with patch(
            "routes.mail_routes.get_model_status",
            return_value={"trained": True, "outdated": True, "message": "old"},
        ), patch(
            "routes.mail_routes.sync_email_account",
            return_value={"new": 0, "existing": 1, "total": 1},
        ) as sync_mock:
            outdated = self.client.post(
                f"/mail/sync/{self.account_a}", follow_redirects=True
            )
        sync_mock.assert_called_once()
        self.assertIn("cần được huấn luyện lại".encode(), outdated.data)


if __name__ == "__main__":
    unittest.main()
