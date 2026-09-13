import os
import unittest
from contextlib import closing
from unittest.mock import patch

import database.db as db
from app import app
from services.encryption_service import encrypt_value
from services.mail_rule_service import (
    create_validated_mail_rule,
    evaluate_sender_rules,
    re_evaluate_existing_messages,
    resolve_mail_policy,
)
from services.mail_service import sync_email_account


class MailRulesIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(os.path.dirname(__file__), "test_mail_rules.db")
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        db.init_db()
        self.admin_id = db.create_user(
            "Rule Admin", "rule-admin@example.com", "Admin123!", "admin"
        )
        self.user_id = db.create_user(
            "Rule User", "rule-user@example.com", "Password123!", "user"
        )
        self.account_id = db.create_email_account(
            self.user_id,
            "imap",
            "inbox@example.com",
            encrypt_value("app-password"),
            imap_host="imap.example.com",
            imap_port=993,
            imap_username="inbox@example.com",
        )
        app.config.update(TESTING=True, SECRET_KEY="mail-rules-test")
        self.client = app.test_client()

    def tearDown(self):
        if os.path.exists(db.DB_PATH):
            os.remove(db.DB_PATH)
        db.DB_PATH = self.original_db_path

    def login(self, email, password):
        return self.client.post(
            "/login", data={"email": email, "password": password}
        )

    @staticmethod
    def email(provider_id, sender):
        return {
            "provider_message_id": provider_id,
            "thread_id": None,
            "message_id_header": f"<{provider_id}@example.com>",
            "subject": "Policy test",
            "sender_name": "Sender",
            "sender_email": sender,
            "recipient_email": "inbox@example.com",
            "snippet": "Policy test",
            "body_text": "Neutral content for policy test",
            "received_at": "2026-09-13T12:00:00+07:00",
            "is_read": 0,
        }

    @staticmethod
    def prediction(label):
        spam_probability = 0.95 if label == "spam" else 0.05
        return {
            "prediction": label,
            "spam_probability": spam_probability,
            "ham_probability": 1 - spam_probability,
            "confidence": 0.95,
        }

    def sync_one(self, provider_id, sender, prediction):
        account = db.get_email_account(self.account_id)
        with patch(
            "services.mail_service.fetch_recent_imap_messages",
            return_value=[self.email(provider_id, sender)],
        ), patch(
            "services.mail_service.predict_batch_emails",
            return_value=[self.prediction(prediction)],
        ) as prediction_mock:
            result = sync_email_account(account)
        prediction_mock.assert_called_once()
        with closing(db.get_connection()) as conn:
            message_id = conn.execute(
                "SELECT id FROM mail_messages WHERE account_id = ? "
                "AND provider_message_id = ?",
                (self.account_id, provider_id),
            ).fetchone()["id"]
        return result, message_id

    def test_normalization_duplicate_conflict_and_validation(self):
        rule_id = create_validated_mail_rule(
            "whitelist", "email", " Trusted@Example.COM ", "Teacher", self.admin_id
        )
        rule = db.get_mail_rule(rule_id)
        self.assertEqual(rule["target_value"], "trusted@example.com")

        for rule_type in ("whitelist", "blacklist"):
            with self.subTest(rule_type=rule_type), self.assertRaisesRegex(
                ValueError, "Whitelist"
            ):
                create_validated_mail_rule(
                    rule_type, "email", "trusted@example.com", "", self.admin_id
                )

        domain_id = create_validated_mail_rule(
            "blacklist", "domain", " @Spam-Example.COM ", "Campaign", self.admin_id
        )
        self.assertEqual(db.get_mail_rule(domain_id)["target_value"], "spam-example.com")
        for invalid in ("abc", "@", "http://example.com", "https://example.com/test"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                create_validated_mail_rule(
                    "blacklist", "domain", invalid, "", self.admin_id
                )

    def test_exact_email_priority_disabled_rule_and_model_fallback(self):
        domain_id = create_validated_mail_rule(
            "blacklist", "domain", "example.com", "Blocked domain", self.admin_id
        )
        exact_id = create_validated_mail_rule(
            "whitelist", "email", "boss@example.com", "Trusted boss", self.admin_id
        )
        exact = evaluate_sender_rules("Boss@Example.com")
        self.assertEqual(exact["rule_id"], exact_id)
        self.assertEqual(exact["rule_type"], "whitelist")
        self.assertEqual(
            evaluate_sender_rules("other@example.com")["rule_id"], domain_id
        )

        db.set_mail_rule_active(exact_id, False)
        self.assertEqual(
            evaluate_sender_rules("boss@example.com")["rule_type"], "blacklist"
        )
        db.set_mail_rule_active(domain_id, False)
        self.assertEqual(evaluate_sender_rules("boss@example.com"), {"matched": False})
        fallback = resolve_mail_policy("nobody@elsewhere.com", "spam")
        self.assertEqual(fallback["policy_action"], "model")
        self.assertTrue(fallback["is_quarantined"])

    def test_sync_keeps_model_prediction_and_re_evaluate_preserves_feedback(self):
        whitelist_id = create_validated_mail_rule(
            "whitelist", "email", "trusted@example.com", "", self.admin_id
        )
        result, trusted_message_id = self.sync_one(
            "trusted-1", "trusted@example.com", "spam"
        )
        trusted = db.get_mail_message_for_user(trusted_message_id, self.user_id)
        self.assertEqual(result["new"], 1)
        self.assertEqual(trusted["prediction"], "spam")
        self.assertEqual(trusted["policy_action"], "trusted")
        self.assertEqual(trusted["matched_rule_id"], whitelist_id)
        self.assertEqual(trusted["is_quarantined"], 0)

        db.set_mail_rule_active(whitelist_id, False)
        blacklist_id = create_validated_mail_rule(
            "blacklist", "domain", "example.com", "", self.admin_id
        )
        _, blocked_message_id = self.sync_one(
            "blocked-1", "sender@example.com", "ham"
        )
        blocked = db.get_mail_message_for_user(blocked_message_id, self.user_id)
        self.assertEqual(blocked["prediction"], "ham")
        self.assertEqual(blocked["policy_action"], "blocked")
        self.assertEqual(blocked["matched_rule_id"], blacklist_id)
        self.assertEqual(blocked["is_quarantined"], 1)

        db.save_mail_feedback(self.user_id, trusted_message_id, "ham")
        evaluation = re_evaluate_existing_messages()
        reevaluated = db.get_mail_message_for_user(trusted_message_id, self.user_id)
        self.assertEqual(evaluation["feedback_preserved"], 1)
        self.assertEqual(reevaluated["prediction"], "spam")
        self.assertEqual(reevaluated["policy_action"], "blocked")
        self.assertEqual(reevaluated["user_label"], "ham")
        self.assertEqual(reevaluated["is_quarantined"], 0)

        self.assertEqual(db.delete_mail_rule(blacklist_id), "disabled")
        self.assertIsNotNone(
            db.get_mail_message_for_user(blocked_message_id, self.user_id)["prediction"]
        )

    def test_admin_routes_filters_and_safe_migration(self):
        self.login("rule-user@example.com", "Password123!")
        denied = self.client.get("/admin/mail-rules")
        self.assertEqual(denied.status_code, 302)
        self.assertTrue(denied.headers["Location"].endswith("/"))

        self.client.post("/logout")
        self.login("rule-admin@example.com", "Admin123!")
        page = self.client.get("/admin/mail-rules")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Quy tắc Email".encode(), page.data)
        added = self.client.post(
            "/admin/mail-rules/add",
            data={
                "rule_type": "whitelist",
                "target_type": "domain",
                "target_value": "@school.edu",
                "description": "Trusted school",
            },
            follow_redirects=True,
        )
        self.assertIn(b"school.edu", added.data)
        filtered = self.client.get(
            "/admin/mail-rules?search=school&rule_type=whitelist&target_type=domain&status=active"
        )
        self.assertIn(b"school.edu", filtered.data)

        with closing(db.get_connection()) as conn:
            counts_before = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("users", "email_accounts", "mail_rules")
            )
        db.init_db()
        with closing(db.get_connection()) as conn:
            counts_after = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("users", "email_accounts", "mail_rules")
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(mail_messages)")
            }
        self.assertEqual(counts_before, counts_after)
        self.assertTrue({"policy_action", "matched_rule_id"} <= columns)


if __name__ == "__main__":
    unittest.main()
