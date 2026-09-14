import os
import sqlite3
from contextlib import closing
from datetime import datetime

from werkzeug.security import generate_password_hash


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get(
    "SPAM_CLASSIFIER_DB_PATH",
    os.path.join(BASE_DIR, "database", "database.db"),
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with closing(get_connection()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user'
                    CHECK (role IN ('admin', 'user')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                message TEXT NOT NULL,
                prediction TEXT NOT NULL,
                spam_probability REAL,
                ham_probability REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id)
            )
        """)

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(predictions)").fetchall()
        }
        if "user_id" not in columns:
            conn.execute(
                "ALTER TABLE predictions ADD COLUMN user_id INTEGER REFERENCES users(id)"
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_predictions_user_id "
            "ON predictions(user_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                provider TEXT NOT NULL CHECK (provider IN ('gmail', 'imap')),
                email_address TEXT NOT NULL,
                display_name TEXT,
                credential_encrypted TEXT,
                imap_host TEXT,
                imap_port INTEGER,
                imap_username TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_sync_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, provider, email_address)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mail_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_type TEXT NOT NULL
                    CHECK (rule_type IN ('whitelist', 'blacklist')),
                target_type TEXT NOT NULL
                    CHECK (target_type IN ('email', 'domain')),
                target_value TEXT NOT NULL,
                description TEXT,
                created_by INTEGER NOT NULL REFERENCES users(id),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(rule_type, target_type, target_value)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mail_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                account_id INTEGER NOT NULL REFERENCES email_accounts(id),
                provider_message_id TEXT NOT NULL,
                thread_id TEXT,
                message_id_header TEXT,
                subject TEXT,
                sender_name TEXT,
                sender_email TEXT,
                recipient_email TEXT,
                snippet TEXT,
                body_text TEXT,
                received_at TIMESTAMP,
                prediction TEXT,
                spam_probability REAL,
                ham_probability REAL,
                confidence REAL,
                is_read INTEGER NOT NULL DEFAULT 0,
                synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, provider_message_id)
            )
        """)
        mail_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(mail_messages)").fetchall()
        }
        mail_migrations = {
            "is_quarantined": "INTEGER NOT NULL DEFAULT 0",
            "user_label": "TEXT CHECK (user_label IN ('spam', 'ham') OR user_label IS NULL)",
            "feedback_at": "TIMESTAMP",
            "policy_action": "TEXT DEFAULT 'model' CHECK (policy_action IN ('trusted', 'blocked', 'model') OR policy_action IS NULL)",
            "matched_rule_id": "INTEGER REFERENCES mail_rules(id) ON DELETE SET NULL",
            "is_hidden": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in mail_migrations.items():
            if column not in mail_columns:
                conn.execute(
                    f"ALTER TABLE mail_messages ADD COLUMN {column} {definition}"
                )
        conn.execute("""
            UPDATE mail_messages
            SET is_quarantined = CASE WHEN prediction = 'spam' THEN 1 ELSE 0 END
            WHERE user_label IS NULL AND feedback_at IS NULL
              AND COALESCE(policy_action, 'model') = 'model'
        """)
        conn.execute("""
            UPDATE mail_messages SET policy_action = 'model'
            WHERE policy_action IS NULL
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mail_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                message_id INTEGER NOT NULL REFERENCES mail_messages(id),
                original_prediction TEXT NOT NULL
                    CHECK (original_prediction IN ('spam', 'ham')),
                corrected_label TEXT NOT NULL
                    CHECK (corrected_label IN ('spam', 'ham')),
                allow_training INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                reviewed_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                text_hash TEXT,
                UNIQUE(user_id, message_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_accounts_user "
            "ON email_accounts(user_id, is_active)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mail_messages_user "
            "ON mail_messages(user_id, received_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mail_messages_visibility "
            "ON mail_messages(user_id, is_hidden, received_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mail_quarantine_user "
            "ON mail_messages(user_id, is_quarantined)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mail_feedback_review "
            "ON mail_feedback(status, allow_training)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mail_rules_match "
            "ON mail_rules(is_active, target_type, target_value)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT UNIQUE NOT NULL,
                model_name TEXT NOT NULL,
                vectorizer TEXT NOT NULL,
                accuracy REAL,
                precision REAL,
                recall REAL,
                f1 REAL,
                tn INTEGER,
                fp INTEGER,
                fn INTEGER,
                tp INTEGER,
                train_size INTEGER,
                test_size INTEGER,
                dataset_size INTEGER,
                vocabulary_size INTEGER,
                training_time REAL,
                alpha REAL,
                ngram_min INTEGER,
                ngram_max INTEGER,
                dataset_hash TEXT,
                model_path TEXT NOT NULL,
                vectorizer_path TEXT NOT NULL,
                info_path TEXT NOT NULL,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_model_versions_one_active
            ON model_versions(is_active) WHERE is_active = 1
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL
                    CHECK (event_type IN ('train', 'activate', 'rollback')),
                from_version TEXT,
                to_version TEXT,
                user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_events_created "
            "ON model_events(created_at DESC)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                last_used_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_prediction_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id INTEGER NOT NULL REFERENCES api_keys(id),
                prediction TEXT NOT NULL CHECK (prediction IN ('spam', 'ham')),
                spam_probability REAL NOT NULL,
                ham_probability REAL NOT NULL,
                confidence REAL NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_logs_key_created "
            "ON api_prediction_logs(api_key_id, created_at DESC)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                action TEXT NOT NULL,
                category TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'success'
                    CHECK (status IN ('success', 'failed')),
                ip_address TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_created "
            "ON audit_logs(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_filters "
            "ON audit_logs(category, status, user_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL,
                file_size INTEGER,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'ready'
                    CHECK (status IN ('ready', 'failed', 'restored')),
                notes TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_backups_created "
            "ON backups(created_at DESC)"
        )


def get_user_by_id(user_id):
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def get_user_by_email(email):
    normalized_email = (email or "").strip().lower()
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (normalized_email,)
        ).fetchone()


def create_user(name, email, password, role="user"):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    role = (role or "").strip().lower()

    if not name or not email:
        raise ValueError("Tên và email không được để trống.")
    if len(password or "") < 8:
        raise ValueError("Mật khẩu phải có ít nhất 8 ký tự.")
    if role not in {"admin", "user"}:
        raise ValueError("Vai trò không hợp lệ.")

    try:
        with closing(get_connection()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, generate_password_hash(password), role),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Email đã tồn tại trong hệ thống.") from error


def get_all_users():
    with closing(get_connection()) as conn:
        return conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()


def set_user_active(user_id, is_active):
    with closing(get_connection()) as conn, conn:
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )


def update_user_role(user_id, role):
    if role not in {"admin", "user"}:
        raise ValueError("Vai trò không hợp lệ.")
    with closing(get_connection()) as conn, conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))


def update_user(user_id, name, email, role):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    role = (role or "").strip().lower()
    if not name or not email:
        raise ValueError("Tên và Email không được để trống.")
    if role not in {"admin", "user"}:
        raise ValueError("Vai trò không hợp lệ.")
    try:
        with closing(get_connection()) as conn, conn:
            cursor = conn.execute("""
                UPDATE users SET name = ?, email = ?, role = ? WHERE id = ?
            """, (name, email, role, user_id))
            return cursor.rowcount > 0
    except sqlite3.IntegrityError as error:
        raise ValueError("Email đã tồn tại trong hệ thống.") from error


def reset_user_password(user_id, password_hash):
    if not password_hash:
        raise ValueError("Password hash không hợp lệ.")
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        return cursor.rowcount > 0


def update_last_login(user_id):
    with closing(get_connection()) as conn, conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )


def count_active_admins(exclude_user_id=None):
    query = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    params = ()
    if exclude_user_id is not None:
        query += " AND id != ?"
        params = (exclude_user_id,)
    with closing(get_connection()) as conn:
        return conn.execute(query, params).fetchone()[0]


def save_prediction(
    subject,
    message,
    prediction,
    spam_probability,
    ham_probability,
    user_id=None,
):
    with closing(get_connection()) as conn, conn:
        conn.execute("""
            INSERT INTO predictions (
                subject,
                message,
                prediction,
                spam_probability,
                ham_probability,
                user_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            subject,
            message,
            prediction,
            spam_probability,
            ham_probability,
            user_id,
        ))


def create_email_account(
    user_id,
    provider,
    email_address,
    credential_encrypted,
    display_name=None,
    imap_host=None,
    imap_port=None,
    imap_username=None,
):
    provider = (provider or "").strip().lower()
    email_address = (email_address or "").strip().lower()
    if provider not in {"gmail", "imap"}:
        raise ValueError("Nhà cung cấp Email không hợp lệ.")
    if not email_address or not credential_encrypted:
        raise ValueError("Email và credential không được để trống.")
    if imap_port is not None and not 1 <= int(imap_port) <= 65535:
        raise ValueError("Cổng IMAP phải nằm trong khoảng 1-65535.")

    with closing(get_connection()) as conn, conn:
        conn.execute("""
            INSERT INTO email_accounts (
                user_id, provider, email_address, display_name,
                credential_encrypted, imap_host, imap_port,
                imap_username, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id, provider, email_address) DO UPDATE SET
                display_name = excluded.display_name,
                credential_encrypted = excluded.credential_encrypted,
                imap_host = excluded.imap_host,
                imap_port = excluded.imap_port,
                imap_username = excluded.imap_username,
                is_active = 1
        """, (
            user_id, provider, email_address, display_name,
            credential_encrypted, imap_host, imap_port, imap_username,
        ))
        return conn.execute("""
            SELECT id FROM email_accounts
            WHERE user_id = ? AND provider = ? AND email_address = ?
        """, (user_id, provider, email_address)).fetchone()["id"]


def get_email_accounts_by_user(user_id, active_only=True):
    query = "SELECT * FROM email_accounts WHERE user_id = ?"
    params = [user_id]
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY id DESC"
    with closing(get_connection()) as conn:
        return conn.execute(query, params).fetchall()


def get_email_account(account_id):
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM email_accounts WHERE id = ?", (account_id,)
        ).fetchone()


def get_email_account_for_user(account_id, user_id, active_only=True):
    query = "SELECT * FROM email_accounts WHERE id = ? AND user_id = ?"
    params = [account_id, user_id]
    if active_only:
        query += " AND is_active = 1"
    with closing(get_connection()) as conn:
        return conn.execute(query, params).fetchone()


def disconnect_email_account(account_id, user_id):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            UPDATE email_accounts
            SET is_active = 0, credential_encrypted = NULL
            WHERE id = ? AND user_id = ?
        """, (account_id, user_id))
        return cursor.rowcount > 0


def update_email_account_sync_time(account_id):
    with closing(get_connection()) as conn, conn:
        conn.execute(
            "UPDATE email_accounts SET last_sync_at = CURRENT_TIMESTAMP WHERE id = ?",
            (account_id,),
        )


def update_email_account_credential(account_id, credential_encrypted):
    with closing(get_connection()) as conn, conn:
        conn.execute("""
            UPDATE email_accounts SET credential_encrypted = ? WHERE id = ?
        """, (credential_encrypted, account_id))


def get_mail_provider_message_ids(account_id):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT provider_message_id FROM mail_messages WHERE account_id = ?",
            (account_id,),
        ).fetchall()
    return {row["provider_message_id"] for row in rows}


def create_mail_rule(rule_type, target_type, target_value, description, created_by):
    try:
        with closing(get_connection()) as conn, conn:
            cursor = conn.execute("""
                INSERT INTO mail_rules (
                    rule_type, target_type, target_value, description, created_by
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                rule_type, target_type, target_value, description or None, created_by,
            ))
            return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Quy tắc này đã tồn tại.") from error


def find_rule_conflict(target_type, target_value):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT * FROM mail_rules
            WHERE target_type = ? AND target_value = ?
            ORDER BY id LIMIT 1
        """, (target_type, target_value)).fetchone()


def get_mail_rule(rule_id):
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM mail_rules WHERE id = ?", (rule_id,)
        ).fetchone()


def get_mail_rules(search="", rule_type="all", target_type="all", status="all"):
    conditions = ["1 = 1"]
    params = []
    if search:
        conditions.append("mail_rules.target_value LIKE ?")
        params.append(f"%{search}%")
    if rule_type in {"whitelist", "blacklist"}:
        conditions.append("mail_rules.rule_type = ?")
        params.append(rule_type)
    if target_type in {"email", "domain"}:
        conditions.append("mail_rules.target_type = ?")
        params.append(target_type)
    if status in {"active", "disabled"}:
        conditions.append("mail_rules.is_active = ?")
        params.append(1 if status == "active" else 0)
    with closing(get_connection()) as conn:
        return conn.execute(f"""
            SELECT mail_rules.*, users.name AS created_by_name,
                   users.email AS created_by_email
            FROM mail_rules
            JOIN users ON users.id = mail_rules.created_by
            WHERE {' AND '.join(conditions)}
            ORDER BY mail_rules.is_active DESC, mail_rules.id DESC
        """, params).fetchall()


def get_active_mail_rules():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT * FROM mail_rules WHERE is_active = 1
            ORDER BY CASE target_type WHEN 'email' THEN 0 ELSE 1 END, id
        """).fetchall()


def get_matching_mail_rule(sender_email):
    sender_email = (sender_email or "").strip().lower()
    domain = sender_email.rsplit("@", 1)[1] if "@" in sender_email else ""
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT * FROM mail_rules
            WHERE is_active = 1 AND (
                (target_type = 'email' AND target_value = ?)
                OR (target_type = 'domain' AND target_value = ?)
            )
            ORDER BY CASE target_type WHEN 'email' THEN 0 ELSE 1 END, id
            LIMIT 1
        """, (sender_email, domain)).fetchone()


def set_mail_rule_active(rule_id, active):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            UPDATE mail_rules
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (1 if active else 0, rule_id))
        return cursor.rowcount > 0


def delete_mail_rule(rule_id):
    with closing(get_connection()) as conn, conn:
        linked = conn.execute(
            "SELECT 1 FROM mail_messages WHERE matched_rule_id = ? LIMIT 1",
            (rule_id,),
        ).fetchone()
        if linked:
            cursor = conn.execute("""
                UPDATE mail_rules
                SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rule_id,))
            return "disabled" if cursor.rowcount else None
        cursor = conn.execute("DELETE FROM mail_rules WHERE id = ?", (rule_id,))
        return "deleted" if cursor.rowcount else None


def get_mail_rule_statistics():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT
                COALESCE(SUM(rule_type = 'whitelist' AND target_type = 'email'), 0)
                    AS whitelist_email,
                COALESCE(SUM(rule_type = 'whitelist' AND target_type = 'domain'), 0)
                    AS whitelist_domain,
                COALESCE(SUM(rule_type = 'blacklist' AND target_type = 'email'), 0)
                    AS blacklist_email,
                COALESCE(SUM(rule_type = 'blacklist' AND target_type = 'domain'), 0)
                    AS blacklist_domain
            FROM mail_rules
        """).fetchone()


def get_mail_messages_for_rule_evaluation():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT id, sender_email, prediction, user_label, feedback_at
            FROM mail_messages ORDER BY id
        """).fetchall()


def update_mail_message_policy(
    message_id, policy_action, matched_rule_id, is_quarantined=None
):
    with closing(get_connection()) as conn, conn:
        if is_quarantined is None:
            conn.execute("""
                UPDATE mail_messages
                SET policy_action = ?, matched_rule_id = ?
                WHERE id = ?
            """, (policy_action, matched_rule_id, message_id))
        else:
            conn.execute("""
                UPDATE mail_messages
                SET policy_action = ?, matched_rule_id = ?, is_quarantined = ?
                WHERE id = ?
            """, (
                policy_action, matched_rule_id, 1 if is_quarantined else 0,
                message_id,
            ))


def save_mail_message(message):
    fields = (
        "user_id", "account_id", "provider_message_id", "thread_id",
        "message_id_header", "subject", "sender_name", "sender_email",
        "recipient_email", "snippet", "body_text", "received_at",
        "prediction", "spam_probability", "ham_probability", "confidence",
        "is_read", "is_quarantined", "policy_action", "matched_rule_id",
    )
    values = tuple(
        (
            message.get(
                "is_quarantined",
                1 if message.get("prediction") == "spam" else 0,
            )
            if field == "is_quarantined"
            else "model" if field == "policy_action" and message.get(field) is None
            else message.get(field)
        )
        for field in fields
    )
    placeholders = ", ".join("?" for _ in fields)
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO mail_messages ({', '.join(fields)}) "
            f"VALUES ({placeholders})",
            values,
        )
        return cursor.rowcount > 0


def get_mail_messages_by_user(user_id, filter_name="all", search="", page=1, per_page=20):
    conditions = ["mail_messages.user_id = ?"]
    params = [user_id]
    if filter_name == "hidden":
        conditions.append("mail_messages.is_hidden = 1")
    else:
        conditions.append("mail_messages.is_hidden = 0")
    if filter_name in {"spam", "ham"}:
        conditions.append("mail_messages.prediction = ?")
        params.append(filter_name)
    elif filter_name == "low":
        conditions.append("mail_messages.confidence < ?")
        params.append(0.65)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append("(mail_messages.subject LIKE ? OR mail_messages.sender_email LIKE ? OR mail_messages.sender_name LIKE ?)")
        params.extend([pattern, pattern, pattern])

    offset = (max(1, page) - 1) * per_page
    params.extend([per_page, offset])
    with closing(get_connection()) as conn:
        return conn.execute(f"""
            SELECT mail_messages.*, email_accounts.email_address AS account_email,
                   email_accounts.provider AS account_provider
            FROM mail_messages
            JOIN email_accounts ON email_accounts.id = mail_messages.account_id
            WHERE {' AND '.join(conditions)}
            ORDER BY COALESCE(received_at, synced_at) DESC, mail_messages.id DESC
            LIMIT ? OFFSET ?
        """, params).fetchall()


def get_mail_message_for_user(message_id, user_id):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT mail_messages.*, email_accounts.email_address AS account_email,
                   email_accounts.provider AS account_provider,
                   mail_rules.rule_type AS matched_rule_type,
                   mail_rules.target_type AS matched_target_type,
                   mail_rules.target_value AS matched_target_value
            FROM mail_messages
            JOIN email_accounts ON email_accounts.id = mail_messages.account_id
            LEFT JOIN mail_rules ON mail_rules.id = mail_messages.matched_rule_id
            WHERE mail_messages.id = ? AND mail_messages.user_id = ?
        """, (message_id, user_id)).fetchone()


def set_mail_message_hidden(message_id, user_id, is_hidden):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            UPDATE mail_messages SET is_hidden = ?
            WHERE id = ? AND user_id = ?
        """, (1 if is_hidden else 0, message_id, user_id))
        return cursor.rowcount > 0


def count_mail_messages_by_user(user_id, filter_name="all", search=""):
    conditions = ["user_id = ?"]
    params = [user_id]
    if filter_name == "hidden":
        conditions.append("is_hidden = 1")
    else:
        conditions.append("is_hidden = 0")
    if filter_name in {"spam", "ham"}:
        conditions.append("prediction = ?")
        params.append(filter_name)
    elif filter_name == "low":
        conditions.append("confidence < ?")
        params.append(0.65)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append("(subject LIKE ? OR sender_email LIKE ? OR sender_name LIKE ?)")
        params.extend([pattern, pattern, pattern])
    with closing(get_connection()) as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM mail_messages WHERE {' AND '.join(conditions)}",
            params,
        ).fetchone()[0]


def get_mail_statistics(user_id):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT COUNT(*) AS total,
                COALESCE(SUM(prediction = 'spam'), 0) AS spam,
                COALESCE(SUM(prediction = 'ham'), 0) AS ham,
                COALESCE(SUM(confidence < 0.65), 0) AS low_confidence
            FROM mail_messages WHERE user_id = ? AND is_hidden = 0
        """, (user_id,)).fetchone()


def save_mail_feedback(user_id, message_id, corrected_label, allow_training=False):
    corrected_label = (corrected_label or "").strip().lower()
    if corrected_label not in {"spam", "ham"}:
        raise ValueError("Nhãn phản hồi không hợp lệ.")

    with closing(get_connection()) as conn, conn:
        message = conn.execute("""
            SELECT id, prediction FROM mail_messages
            WHERE id = ? AND user_id = ?
        """, (message_id, user_id)).fetchone()
        if not message:
            raise PermissionError("Không tìm thấy Email hoặc bạn không có quyền.")

        existing = conn.execute("""
            SELECT status FROM mail_feedback
            WHERE user_id = ? AND message_id = ?
        """, (user_id, message_id)).fetchone()
        if existing and existing["status"] != "pending":
            raise ValueError("Phản hồi này đã được Admin xử lý và được giữ để audit.")

        conn.execute("""
            INSERT INTO mail_feedback (
                user_id, message_id, original_prediction,
                corrected_label, allow_training
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, message_id) DO UPDATE SET
                corrected_label = excluded.corrected_label,
                allow_training = excluded.allow_training,
                created_at = CURRENT_TIMESTAMP
        """, (
            user_id, message_id, message["prediction"], corrected_label,
            1 if allow_training else 0,
        ))
        conn.execute("""
            UPDATE mail_messages
            SET user_label = ?, is_quarantined = ?, feedback_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """, (
            corrected_label, 1 if corrected_label == "spam" else 0,
            message_id, user_id,
        ))
        return conn.execute("""
            SELECT * FROM mail_feedback WHERE user_id = ? AND message_id = ?
        """, (user_id, message_id)).fetchone()


def get_feedback_by_message(user_id, message_id):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT * FROM mail_feedback WHERE user_id = ? AND message_id = ?
        """, (user_id, message_id)).fetchone()


def get_quarantined_messages_by_user(
    user_id, filter_name="all", search="", page=1, per_page=20
):
    conditions = ["mail_messages.user_id = ?", "mail_messages.is_quarantined = 1"]
    params = [user_id]
    if filter_name == "unchecked":
        conditions.append("mail_messages.user_label IS NULL")
    elif filter_name == "confirmed_spam":
        conditions.append("mail_messages.user_label = 'spam'")
    elif filter_name == "false_positive":
        conditions.append(
            "mail_messages.prediction = 'spam' AND mail_messages.user_label = 'ham'"
        )
    elif filter_name == "low":
        conditions.append("mail_messages.confidence < ?")
        params.append(0.65)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append("""
            (mail_messages.subject LIKE ? OR mail_messages.sender_email LIKE ?
             OR mail_messages.sender_name LIKE ?)
        """)
        params.extend([pattern, pattern, pattern])
    params.extend([per_page, (max(1, page) - 1) * per_page])
    with closing(get_connection()) as conn:
        return conn.execute(f"""
            SELECT mail_messages.*, email_accounts.email_address AS account_email,
                   email_accounts.provider AS account_provider
            FROM mail_messages
            JOIN email_accounts ON email_accounts.id = mail_messages.account_id
            WHERE {' AND '.join(conditions)}
            ORDER BY COALESCE(received_at, synced_at) DESC, mail_messages.id DESC
            LIMIT ? OFFSET ?
        """, params).fetchall()


def count_quarantined_messages_by_user(user_id, filter_name="all", search=""):
    conditions = ["user_id = ?", "is_quarantined = 1"]
    params = [user_id]
    if filter_name == "unchecked":
        conditions.append("user_label IS NULL")
    elif filter_name == "confirmed_spam":
        conditions.append("user_label = 'spam'")
    elif filter_name == "false_positive":
        conditions.append("prediction = 'spam' AND user_label = 'ham'")
    elif filter_name == "low":
        conditions.append("confidence < ?")
        params.append(0.65)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append("(subject LIKE ? OR sender_email LIKE ? OR sender_name LIKE ?)")
        params.extend([pattern, pattern, pattern])
    with closing(get_connection()) as conn:
        return conn.execute(
            f"SELECT COUNT(1) FROM mail_messages WHERE {' AND '.join(conditions)}",
            params,
        ).fetchone()[0]


def get_quarantine_statistics(user_id):
    with closing(get_connection()) as conn:
        current = conn.execute("""
            SELECT COUNT(1) AS total,
                COALESCE(SUM(user_label IS NULL), 0) AS unchecked,
                COALESCE(SUM(user_label = 'spam'), 0) AS confirmed_spam
            FROM mail_messages
            WHERE user_id = ? AND is_quarantined = 1
        """, (user_id,)).fetchone()
        false_positive = conn.execute("""
            SELECT COUNT(1) FROM mail_feedback
            WHERE user_id = ? AND original_prediction = 'spam'
              AND corrected_label = 'ham'
        """, (user_id,)).fetchone()[0]
        return {
            "total": current["total"],
            "unchecked": current["unchecked"],
            "confirmed_spam": current["confirmed_spam"],
            "false_positive": false_positive,
        }


def get_pending_training_feedback():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT mail_feedback.*, users.name AS user_name,
                   users.email AS user_email, mail_messages.subject,
                   mail_messages.body_text, mail_messages.snippet
            FROM mail_feedback
            JOIN users ON users.id = mail_feedback.user_id
            JOIN mail_messages ON mail_messages.id = mail_feedback.message_id
            WHERE mail_feedback.status = 'pending'
              AND mail_feedback.allow_training = 1
            ORDER BY mail_feedback.id ASC
        """).fetchall()


def get_training_feedback_for_review(feedback_id):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT mail_feedback.*, mail_messages.subject,
                   mail_messages.body_text, mail_messages.snippet
            FROM mail_feedback
            JOIN mail_messages ON mail_messages.id = mail_feedback.message_id
            WHERE mail_feedback.id = ? AND mail_feedback.status = 'pending'
              AND mail_feedback.allow_training = 1
        """, (feedback_id,)).fetchone()


def approve_feedback(feedback_id, admin_id, text_hash):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            UPDATE mail_feedback
            SET status = 'approved', reviewed_by = ?,
                reviewed_at = CURRENT_TIMESTAMP, text_hash = ?
            WHERE id = ? AND status = 'pending' AND allow_training = 1
        """, (admin_id, text_hash, feedback_id))
        return cursor.rowcount > 0


def reject_feedback(feedback_id, admin_id):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            UPDATE mail_feedback
            SET status = 'rejected', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending' AND allow_training = 1
        """, (admin_id, feedback_id))
        return cursor.rowcount > 0


def is_training_text_hash_approved(text_hash):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT 1 FROM mail_feedback
            WHERE text_hash = ? AND status = 'approved' LIMIT 1
        """, (text_hash,)).fetchone() is not None


def get_feedback_statistics():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT COUNT(1) AS total,
                COALESCE(SUM(status = 'pending'), 0) AS pending,
                COALESCE(SUM(status = 'approved'), 0) AS approved,
                COALESCE(SUM(status = 'rejected'), 0) AS rejected,
                COALESCE(SUM(original_prediction = corrected_label), 0) AS correct,
                COALESCE(SUM(original_prediction = 'spam' AND corrected_label = 'ham'), 0) AS false_positive,
                COALESCE(SUM(original_prediction = 'ham' AND corrected_label = 'spam'), 0) AS false_negative,
                COALESCE(SUM(allow_training = 1), 0) AS training_opt_in
            FROM mail_feedback
        """).fetchone()


def get_model_versions():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT model_versions.*, users.name AS creator_name,
                   users.email AS creator_email
            FROM model_versions
            LEFT JOIN users ON users.id = model_versions.created_by
            ORDER BY CAST(SUBSTR(version, 2) AS INTEGER) DESC, model_versions.id DESC
        """).fetchall()


def get_model_version(version_id):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT model_versions.*, users.name AS creator_name,
                   users.email AS creator_email
            FROM model_versions
            LEFT JOIN users ON users.id = model_versions.created_by
            WHERE model_versions.id = ?
        """, (version_id,)).fetchone()


def get_active_model_version():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT model_versions.*, users.name AS creator_name,
                   users.email AS creator_email
            FROM model_versions
            LEFT JOIN users ON users.id = model_versions.created_by
            WHERE model_versions.is_active = 1
            LIMIT 1
        """).fetchone()


def get_max_model_version_number():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT version FROM model_versions").fetchall()
    numbers = []
    for row in rows:
        version = row["version"]
        if version.startswith("v") and version[1:].isdigit():
            numbers.append(int(version[1:]))
    return max(numbers, default=0)


def create_model_version(values, is_active=False):
    fields = (
        "version", "model_name", "vectorizer", "accuracy", "precision",
        "recall", "f1", "tn", "fp", "fn", "tp", "train_size",
        "test_size", "dataset_size", "vocabulary_size", "training_time",
        "alpha", "ngram_min", "ngram_max", "dataset_hash", "model_path",
        "vectorizer_path", "info_path", "created_by", "notes",
    )
    params = [values.get(field) for field in fields]
    params.append(1 if is_active else 0)
    placeholders = ", ".join("?" for _ in params)
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute(
            f"INSERT INTO model_versions ({', '.join(fields)}, is_active) "
            f"VALUES ({placeholders})",
            params,
        )
        return cursor.lastrowid


def set_active_model_version(version_id, user_id, event_type="activate"):
    if event_type not in {"train", "activate", "rollback"}:
        raise ValueError("Loại sự kiện model không hợp lệ.")
    with closing(get_connection()) as conn, conn:
        target = conn.execute(
            "SELECT id, version FROM model_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        if not target:
            raise ValueError("Phiên bản mô hình không tồn tại.")
        current = conn.execute(
            "SELECT id, version FROM model_versions WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE model_versions SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "UPDATE model_versions SET is_active = 1 WHERE id = ?",
            (version_id,),
        )
        conn.execute("""
            INSERT INTO model_events (
                event_type, from_version, to_version, user_id
            ) VALUES (?, ?, ?, ?)
        """, (
            event_type,
            current["version"] if current else None,
            target["version"],
            user_id,
        ))


def get_model_events(limit=20):
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT model_events.*, users.name AS user_name,
                   users.email AS user_email
            FROM model_events
            LEFT JOIN users ON users.id = model_events.user_id
            ORDER BY model_events.id DESC
            LIMIT ?
        """, (max(1, int(limit)),)).fetchall()


def create_api_key(name, key_prefix, key_hash, created_by):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            INSERT INTO api_keys (name, key_prefix, key_hash, created_by)
            VALUES (?, ?, ?, ?)
        """, (name, key_prefix, key_hash, created_by))
        return cursor.lastrowid


def get_api_key_by_hash(key_hash):
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? LIMIT 1",
            (key_hash,),
        ).fetchone()


def get_api_key(api_key_id):
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM api_keys WHERE id = ?",
            (api_key_id,),
        ).fetchone()


def get_api_keys():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT api_keys.id, api_keys.name, api_keys.key_prefix,
                   api_keys.created_by, api_keys.is_active,
                   api_keys.last_used_at, api_keys.created_at,
                   users.name AS creator_name, users.email AS creator_email,
                   COUNT(api_prediction_logs.id) AS total_requests,
                   COALESCE(SUM(api_prediction_logs.prediction = 'spam'), 0)
                       AS spam_predictions,
                   COALESCE(SUM(api_prediction_logs.prediction = 'ham'), 0)
                       AS ham_predictions
            FROM api_keys
            JOIN users ON users.id = api_keys.created_by
            LEFT JOIN api_prediction_logs
                ON api_prediction_logs.api_key_id = api_keys.id
            GROUP BY api_keys.id
            ORDER BY api_keys.id DESC
        """).fetchall()


def set_api_key_active(api_key_id, is_active):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute(
            "UPDATE api_keys SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, api_key_id),
        )
        return cursor.rowcount > 0


def update_api_key_last_used(api_key_id):
    with closing(get_connection()) as conn, conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
            (api_key_id,),
        )


def save_api_prediction_log(
    api_key_id,
    prediction,
    spam_probability,
    ham_probability,
    confidence,
):
    with closing(get_connection()) as conn, conn:
        conn.execute("""
            INSERT INTO api_prediction_logs (
                api_key_id, prediction, spam_probability,
                ham_probability, confidence
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            api_key_id,
            prediction,
            spam_probability,
            ham_probability,
            confidence,
        ))


def get_api_key_statistics():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT COUNT(DISTINCT api_keys.id) AS total_keys,
                   COUNT(DISTINCT CASE WHEN api_keys.is_active = 1
                       THEN api_keys.id END) AS active_keys,
                   COUNT(api_prediction_logs.id) AS total_requests,
                   COALESCE(SUM(api_prediction_logs.prediction = 'spam'), 0)
                       AS spam_predictions,
                   COALESCE(SUM(api_prediction_logs.prediction = 'ham'), 0)
                       AS ham_predictions
            FROM api_keys
            LEFT JOIN api_prediction_logs
                ON api_prediction_logs.api_key_id = api_keys.id
        """).fetchone()


def create_audit_log(
    user_id,
    action,
    category,
    target_type=None,
    target_id=None,
    description=None,
    status="success",
    ip_address=None,
):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute("""
            INSERT INTO audit_logs (
                user_id, action, category, target_type, target_id,
                description, status, ip_address
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, action, category, target_type, target_id,
            description, status, ip_address,
        ))
        return cursor.lastrowid


def _audit_filter_clause(category="all", status="all", user_id=None, search=""):
    conditions = []
    params = []
    if category != "all":
        conditions.append("audit_logs.category = ?")
        params.append(category)
    if status != "all":
        conditions.append("audit_logs.status = ?")
        params.append(status)
    if user_id is not None:
        conditions.append("audit_logs.user_id = ?")
        params.append(user_id)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            "(audit_logs.action LIKE ? OR audit_logs.description LIKE ?)"
        )
        params.extend((pattern, pattern))
    return (" WHERE " + " AND ".join(conditions)) if conditions else "", params


def get_audit_logs(
    category="all", status="all", user_id=None, search="", page=1, per_page=20
):
    where_clause, params = _audit_filter_clause(
        category, status, user_id, search
    )
    page = max(1, int(page))
    per_page = max(1, min(int(per_page), 100))
    with closing(get_connection()) as conn:
        total = conn.execute(
            f"SELECT COUNT(1) FROM audit_logs{where_clause}", params
        ).fetchone()[0]
        rows = conn.execute(f"""
            SELECT audit_logs.*, users.name AS user_name,
                   users.email AS user_email
            FROM audit_logs
            LEFT JOIN users ON users.id = audit_logs.user_id
            {where_clause}
            ORDER BY audit_logs.created_at DESC, audit_logs.id DESC
            LIMIT ? OFFSET ?
        """, (*params, per_page, (page - 1) * per_page)).fetchall()
        return rows, total


def get_audit_statistics():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT COUNT(1) AS total,
                   COALESCE(SUM(status = 'success'), 0) AS success,
                   COALESCE(SUM(status = 'failed'), 0) AS failed,
                   COALESCE(SUM(DATE(created_at) = DATE('now')), 0) AS today
            FROM audit_logs
        """).fetchone()


def save_backup_record(
    filename, file_size, created_by=None, status="ready", notes=None
):
    if status not in {"ready", "failed", "restored"}:
        raise ValueError("Trạng thái backup không hợp lệ.")
    notes = (notes or "").strip() or None
    with closing(get_connection()) as conn, conn:
        if created_by is not None:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE id = ?", (created_by,)
            ).fetchone()
            if not exists:
                created_by = None
        conn.execute("""
            INSERT INTO backups (
                filename, file_size, created_by, status, notes
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                file_size = excluded.file_size,
                status = excluded.status,
                notes = COALESCE(excluded.notes, backups.notes)
        """, (filename, file_size, created_by, status, notes))
        return conn.execute(
            "SELECT id FROM backups WHERE filename = ?", (filename,)
        ).fetchone()["id"]


def get_backup_records():
    with closing(get_connection()) as conn:
        return conn.execute("""
            SELECT backups.*, users.name AS creator_name,
                   users.email AS creator_email
            FROM backups
            LEFT JOIN users ON users.id = backups.created_by
            ORDER BY backups.created_at DESC, backups.id DESC
        """).fetchall()


def delete_backup_record(filename):
    with closing(get_connection()) as conn, conn:
        cursor = conn.execute(
            "DELETE FROM backups WHERE filename = ?", (filename,)
        )
        return cursor.rowcount > 0
