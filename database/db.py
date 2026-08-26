import sqlite3
import os


DB_PATH = "database/database.db"


def init_db():
    os.makedirs("database", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            message TEXT NOT NULL,
            prediction TEXT NOT NULL,
            spam_probability REAL,
            ham_probability REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def save_prediction(
    subject,
    message,
    prediction,
    spam_probability,
    ham_probability
):
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO predictions (
            subject,
            message,
            prediction,
            spam_probability,
            ham_probability
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        subject,
        message,
        prediction,
        spam_probability,
        ham_probability
    ))

    conn.commit()
    conn.close()