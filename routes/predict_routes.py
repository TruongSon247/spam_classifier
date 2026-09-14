import os
import uuid

import pandas as pd
from flask import current_app, render_template, request, send_from_directory
from flask_login import current_user, login_required

from ml.predict import predict_batch_emails, predict_email
from routes import main_bp
from services.application_service import get_model_status, save_prediction


def _safe_csv_cell(value):
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@main_bp.route("/predict", methods=["GET", "POST"])
@login_required
def predict():
    result = None
    subject = ""
    message = ""
    error = None

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not message:
            error = "Vui lòng nhập nội dung email."
        else:
            result = predict_email(message)
            if result is None:
                error = (
                    "Mô hình chưa được huấn luyện. "
                    "Vui lòng vào trang Huấn luyện trước."
                )
            else:
                save_prediction(subject, message, result, int(current_user.id))

    return render_template(
        "predict.html",
        result=result,
        subject=subject,
        message=message,
        error=error,
        model_status=get_model_status(),
    )


@main_bp.route("/predict/batch", methods=["GET", "POST"])
@login_required
def batch_predict():
    results = None
    total = 0
    spam_count = 0
    ham_count = 0
    download_file = None
    error = None
    model_status = get_model_status()

    if request.method == "POST":
        if not model_status["trained"]:
            error = "Mô hình chưa được huấn luyện."
        elif "file" not in request.files:
            error = "Vui lòng chọn file CSV."
        else:
            file = request.files["file"]
            if file.filename == "":
                error = "Vui lòng chọn file CSV."
            elif not file.filename.lower().endswith(".csv"):
                error = "Chỉ chấp nhận file định dạng CSV."
            else:
                try:
                    df = pd.read_csv(file)
                    if "text" not in df.columns:
                        error = "File CSV phải có cột 'text'."
                    else:
                        if "subject" not in df.columns:
                            df["subject"] = ""
                        df = df[["subject", "text"]].copy()
                        df["subject"] = df["subject"].fillna("").astype(str).str.strip()
                        df["text"] = df["text"].fillna("").astype(str).str.strip()
                        df = df[df["text"] != ""].reset_index(drop=True)

                        max_batch_rows = 500
                        if len(df) == 0:
                            error = "File CSV không có Email hợp lệ."
                        elif len(df) > max_batch_rows:
                            error = (
                                f"Chỉ cho phép tối đa {max_batch_rows} "
                                "Email mỗi lần."
                            )
                        else:
                            predictions = predict_batch_emails(df["text"].tolist())
                            if predictions is None:
                                error = "Không thể tải mô hình dự đoán."
                            else:
                                df["prediction"] = [
                                    item["prediction"] for item in predictions
                                ]
                                df["spam_probability"] = [
                                    round(item["spam_probability"] * 100, 2)
                                    for item in predictions
                                ]
                                df["ham_probability"] = [
                                    round(item["ham_probability"] * 100, 2)
                                    for item in predictions
                                ]
                                df["confidence"] = [
                                    round(item["confidence"] * 100, 2)
                                    for item in predictions
                                ]
                                total = len(df)
                                spam_count = int(
                                    df["prediction"].str.lower().eq("spam").sum()
                                )
                                ham_count = int(
                                    df["prediction"].str.lower().eq("ham").sum()
                                )
                                os.makedirs("temp", exist_ok=True)
                                download_file = f"batch_result_{uuid.uuid4()}.csv"
                                export_df = df.copy()
                                for column in ("subject", "text"):
                                    export_df[column] = export_df[column].map(
                                        _safe_csv_cell
                                    )
                                export_df.to_csv(
                                    os.path.join("temp", download_file),
                                    index=False,
                                    encoding="utf-8-sig",
                                )
                                results = df.to_dict(orient="records")
                except (OSError, UnicodeError, pd.errors.ParserError):
                    current_app.logger.exception("Batch CSV processing failed")
                    error = (
                        "Không thể xử lý file CSV. "
                        "Hãy kiểm tra lại định dạng file."
                    )

    return render_template(
        "batch_predict.html",
        results=results,
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        download_file=download_file,
        error=error,
        model_status=model_status,
    )


@main_bp.route("/predict/batch/download/<filename>")
@login_required
def download_batch_result(filename):
    prefix = "batch_result_"
    suffix = ".csv"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        return "File không hợp lệ.", 400
    identifier = filename[len(prefix):-len(suffix)]
    try:
        if str(uuid.UUID(identifier)) != identifier.lower():
            raise ValueError
    except ValueError:
        return "File không hợp lệ.", 400
    return send_from_directory("temp", filename, as_attachment=True)
