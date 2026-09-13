import pandas as pd
from flask import flash, render_template, request

from auth import admin_required
from ml.compare_models import compare_models
from ml.evaluate import evaluate_model
from ml.train import train_model
from routes import main_bp
from services.application_service import get_model_info, get_model_status


@main_bp.route("/train", methods=["GET", "POST"])
@admin_required
def train():
    result = None
    df = pd.read_csv("dataset/spam_dataset.csv")
    total = len(df)
    spam_count = len(df[df["label"].str.lower() == "spam"])
    ham_count = len(df[df["label"].str.lower() == "ham"])

    if request.method == "POST":
        try:
            result = train_model()
            flash("Huấn luyện mô hình Naïve Bayes thành công.", "success")
        except Exception as error:
            print("Training Error:", error)
            flash("Có lỗi xảy ra trong quá trình huấn luyện.", "danger")

    return render_template(
        "train.html",
        result=result,
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        model_status=get_model_status(),
        model_info=get_model_info(),
    )


@main_bp.route("/evaluate")
@admin_required
def evaluate():
    return render_template("evaluate.html", result=evaluate_model())


@main_bp.route("/compare", methods=["GET", "POST"])
@admin_required
def compare():
    comparison = None
    best_model = None
    error = None
    chart_labels = []
    chart_accuracy = []
    chart_precision = []
    chart_recall = []
    chart_f1 = []

    if request.method == "POST":
        try:
            comparison = compare_models()
            results = comparison["results"]
            if results:
                best_model = results[0]
                chart_labels = [item["short_name"] for item in results]
                chart_accuracy = [
                    round(item["accuracy"] * 100, 2) for item in results
                ]
                chart_precision = [
                    round(item["precision"] * 100, 2) for item in results
                ]
                chart_recall = [
                    round(item["recall"] * 100, 2) for item in results
                ]
                chart_f1 = [round(item["f1"] * 100, 2) for item in results]
        except Exception as error_detail:
            print("Compare models error:", error_detail)
            error = "Không thể thực hiện so sánh thuật toán."

    return render_template(
        "compare.html",
        comparison=comparison,
        best_model=best_model,
        error=error,
        chart_labels=chart_labels,
        chart_accuracy=chart_accuracy,
        chart_precision=chart_precision,
        chart_recall=chart_recall,
        chart_f1=chart_f1,
    )
