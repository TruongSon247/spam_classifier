import unittest

from app import app
from ml.predict import predict_email


class RefactorContractTest(unittest.TestCase):
    def test_public_route_contract_is_unchanged(self):
        actual = {
            (tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})), rule.rule, rule.endpoint)
            for rule in app.url_map.iter_rules()
        }
        expected = {
            (("GET",), "/", "index"),
            (("GET",), "/admin/feedback", "admin_feedback"),
            (("GET",), "/admin/api-keys", "admin_api_keys"),
            (("GET",), "/admin/audit-logs", "audit_logs"),
            (("GET",), "/admin/backups", "admin_backups"),
            (("GET",), "/admin/backups/<filename>/download", "download_backup"),
            (("GET",), "/admin/mail-rules", "admin_mail_rules"),
            (("GET",), "/algorithm", "algorithm"),
            (("GET",), "/api-docs", "api_docs"),
            (("GET",), "/api/v1/health", "api.health"),
            (("GET",), "/dataset", "dataset"),
            (("GET",), "/evaluate", "evaluate"),
            (("GET",), "/history", "history"),
            (("GET",), "/mail", "mail"),
            (("GET",), "/mail/google/callback", "google_callback"),
            (("GET",), "/mail/google/connect", "connect_google"),
            (("GET",), "/mail/message/<int:message_id>", "mail_message_detail"),
            (("GET",), "/models", "model_versions"),
            (("GET",), "/predict/batch/download/<filename>", "download_batch_result"),
            (("GET",), "/quarantine", "quarantine"),
            (("GET",), "/static/<path:filename>", "static"),
            (("GET",), "/users", "users"),
            (("GET", "POST"), "/compare", "compare"),
            (("GET", "POST"), "/login", "login"),
            (("GET", "POST"), "/mail/connect/imap", "connect_imap"),
            (("GET", "POST"), "/predict", "predict"),
            (("GET", "POST"), "/predict/batch", "batch_predict"),
            (("GET", "POST"), "/train", "train"),
            (("POST",), "/admin/feedback/<int:feedback_id>/approve", "approve_mail_feedback"),
            (("POST",), "/admin/feedback/<int:feedback_id>/reject", "reject_mail_feedback"),
            (("POST",), "/admin/api-keys/<int:api_key_id>/revoke", "revoke_api_key"),
            (("POST",), "/admin/api-keys/<int:api_key_id>/toggle", "toggle_api_key"),
            (("POST",), "/admin/api-keys/create", "create_api_key_route"),
            (("POST",), "/admin/backups/create", "create_backup_route"),
            (("POST",), "/admin/backups/<filename>/delete", "delete_backup_route"),
            (("POST",), "/admin/backups/<filename>/restore", "restore_backup_route"),
            (("POST",), "/admin/mail-rules/<int:id>/delete", "remove_mail_rule"),
            (("POST",), "/admin/mail-rules/<int:id>/toggle", "toggle_mail_rule"),
            (("POST",), "/admin/mail-rules/add", "add_mail_rule"),
            (("POST",), "/admin/mail-rules/re-evaluate", "re_evaluate_mail_rules"),
            (("POST",), "/dataset/add", "add_dataset"),
            (("POST",), "/dataset/delete/<int:index>", "delete_dataset"),
            (("POST",), "/dataset/import", "import_dataset"),
            (("POST",), "/api/v1/predict", "api.predict"),
            (("POST",), "/history/delete-all", "delete_all_history"),
            (("POST",), "/history/delete/<int:id>", "delete_history"),
            (("POST",), "/logout", "logout"),
            (("POST",), "/mail/disconnect/<int:account_id>", "disconnect_mail_account"),
            (("POST",), "/mail/message/<int:message_id>/feedback", "submit_mail_feedback"),
            (("POST",), "/mail/message/<int:message_id>/hide", "hide_mail_message"),
            (("POST",), "/mail/message/<int:message_id>/unhide", "unhide_mail_message"),
            (("POST",), "/mail/sync/<int:account_id>", "sync_mail_account"),
            (("POST",), "/models/<int:version_id>/rollback", "rollback_model_version"),
            (("POST",), "/users/<int:user_id>/role", "change_user_role"),
            (("POST",), "/users/<int:user_id>/edit", "edit_user"),
            (("POST",), "/users/<int:user_id>/reset-password", "reset_user_password_route"),
            (("POST",), "/users/<int:user_id>/toggle-active", "toggle_user_active"),
            (("POST",), "/users/create", "create_user_route"),
        }
        self.assertEqual(actual, expected)

    def test_model_predictions_keep_expected_labels_and_valid_probabilities(self):
        samples = (
            ("Congratulations! You won a free prize", "spam"),
            ("Hello, please send me the report before tomorrow.", "ham"),
            ("CHÚC MỪNG! Bạn đã trúng thưởng tiền mặt", "spam"),
            ("Chào bạn, vui lòng gửi báo cáo trước ngày mai", "ham"),
        )
        for text, expected_label in samples:
            with self.subTest(text=text):
                result = predict_email(text)
                self.assertEqual(result["prediction"], expected_label)
                self.assertGreaterEqual(result["spam_probability"], 0.0)
                self.assertLessEqual(result["spam_probability"], 1.0)
                self.assertGreaterEqual(result["ham_probability"], 0.0)
                self.assertLessEqual(result["ham_probability"], 1.0)
                self.assertAlmostEqual(
                    result["spam_probability"] + result["ham_probability"],
                    1.0,
                    places=12,
                )


if __name__ == "__main__":
    unittest.main()
