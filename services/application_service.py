import json
import os

from database.db import get_connection, save_prediction as save_prediction_to_db


def get_model_status(dataset_path="dataset/spam_dataset.csv"):
    source_paths = (dataset_path, "ml/preprocessing.py", "ml/train.py")
    model_path = "model/model.pkl"
    vectorizer_path = "model/vectorizer.pkl"

    if not os.path.exists(model_path) or not os.path.exists(vectorizer_path):
        return {
            "trained": False,
            "outdated": True,
            "message": "Mô hình chưa được huấn luyện.",
        }

    try:
        model_time = min(
            os.path.getmtime(model_path),
            os.path.getmtime(vectorizer_path),
        )
        source_times = [
            os.path.getmtime(path)
            for path in source_paths
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
    except (OSError, ValueError) as error:
        print("Model status error:", error)
        return {
            "trained": False,
            "outdated": True,
            "message": "Không thể kiểm tra trạng thái mô hình.",
        }

    return {"trained": True, "outdated": outdated, "message": message}


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
        "recent_predictions": recent_predictions,
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
