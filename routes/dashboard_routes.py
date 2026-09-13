import pandas as pd
from flask import render_template
from flask_login import current_user, login_required

from ml.evaluate import evaluate_model
from routes import main_bp
from services.application_service import get_model_status, get_prediction_statistics


@main_bp.route("/")
@login_required
def index():
    df = pd.read_csv("dataset/spam_dataset.csv")
    df["label"] = df["label"].str.lower().str.strip()
    total = len(df)
    spam_count = len(df[df["label"] == "spam"])
    ham_count = len(df[df["label"] == "ham"])
    accuracy = precision = recall = f1 = 0
    tn = fp = fn = tp = 0

    try:
        evaluation = evaluate_model()
        accuracy = round(evaluation["accuracy"] * 100, 2)
        precision = round(evaluation["precision"] * 100, 2)
        recall = round(evaluation["recall"] * 100, 2)
        f1 = round(evaluation["f1"] * 100, 2)
        tn = evaluation["tn"]
        fp = evaluation["fp"]
        fn = evaluation["fn"]
        tp = evaluation["tp"]
    except Exception:
        pass

    model_status = get_model_status()
    statistics_user_id = None
    if current_user.role != "admin":
        statistics_user_id = int(current_user.id)
    prediction_stats = get_prediction_statistics(statistics_user_id)
    return render_template(
        "index.html",
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1=f1,
        tn=tn,
        fp=fp,
        fn=fn,
        tp=tp,
        model_status=model_status,
        total_predictions=prediction_stats["total_predictions"],
        spam_predictions=prediction_stats["spam_predictions"],
        ham_predictions=prediction_stats["ham_predictions"],
        recent_predictions=prediction_stats["recent_predictions"],
    )
