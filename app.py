from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for
)
import json
import pandas as pd
import sqlite3
import os
import uuid

from ml.predict import predict_batch_emails, predict_email
from ml.compare_models import compare_models
from ml.train import train_model
from ml.evaluate import evaluate_model


def init_db():

    os.makedirs("database", exist_ok=True)

    conn = sqlite3.connect("database/database.db")

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


def get_model_status():

    dataset_path = "dataset/spam_dataset.csv"
    preprocessing_path = "ml/preprocessing.py"
    train_path = "ml/train.py"
    model_path = "model/model.pkl"
    vectorizer_path = "model/vectorizer.pkl"

    if (
        not os.path.exists(model_path)
        or not os.path.exists(vectorizer_path)
    ):
        return {
            "trained": False,
            "outdated": True,
            "message": "Mô hình chưa được huấn luyện."
        }

    try:
        model_time = min(
            os.path.getmtime(model_path),
            os.path.getmtime(vectorizer_path)
        )
        source_times = [
            os.path.getmtime(path)
            for path in (dataset_path, preprocessing_path, train_path)
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

        return {
            "trained": True,
            "outdated": outdated,
            "message": message
        }
    except (OSError, ValueError) as error:
        print("Model status error:", error)
        return {
            "trained": False,
            "outdated": True,
            "message": "Không thể kiểm tra trạng thái mô hình."
        }


def get_model_info():

    path = "model/model_info.json"

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as metadata_file:
            return json.load(metadata_file)
    except (OSError, json.JSONDecodeError):
        return None


def get_prediction_statistics():

    conn = sqlite3.connect("database/database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) AS total_predictions,
            COALESCE(SUM(CASE WHEN prediction = 'spam' THEN 1 ELSE 0 END), 0)
                AS spam_predictions,
            COALESCE(SUM(CASE WHEN prediction = 'ham' THEN 1 ELSE 0 END), 0)
                AS ham_predictions
        FROM predictions
    """)
    counts = cursor.fetchone()

    cursor.execute("""
        SELECT *
        FROM predictions
        ORDER BY id DESC
        LIMIT 5
    """)
    recent_predictions = cursor.fetchall()

    conn.close()

    return {
        "total_predictions": counts["total_predictions"],
        "spam_predictions": counts["spam_predictions"],
        "ham_predictions": counts["ham_predictions"],
        "recent_predictions": recent_predictions
    }

def save_prediction(subject, message, result):

    conn = sqlite3.connect("database/database.db")

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
        result["prediction"],
        result["spam_probability"],
        result["ham_probability"]
    ))

    conn.commit()
    conn.close()


app = Flask(__name__)
app.secret_key = "spam-classifier-secret-key"

init_db()


@app.context_processor
def inject_global_data():

    return {
        "global_model_status": get_model_status()
    }


@app.route("/")
def index():

    df = pd.read_csv("dataset/spam_dataset.csv")

    # Chuẩn hóa label
    df["label"] = df["label"].str.lower().str.strip()

    total = len(df)

    spam_count = len(
        df[df["label"] == "spam"]
    )

    ham_count = len(
        df[df["label"] == "ham"]
    )

    # Giá trị mặc định
    accuracy = 0
    precision = 0
    recall = 0
    f1 = 0

    tn = 0
    fp = 0
    fn = 0
    tp = 0

    try:

        evaluation = evaluate_model()

        accuracy = round(
            evaluation["accuracy"] * 100,
            2
        )

        precision = round(
            evaluation["precision"] * 100,
            2
        )

        recall = round(
            evaluation["recall"] * 100,
            2
        )

        f1 = round(
            evaluation["f1"] * 100,
            2
        )

        tn = evaluation["tn"]
        fp = evaluation["fp"]
        fn = evaluation["fn"]
        tp = evaluation["tp"]

    except Exception:
        pass

    model_status = get_model_status()
    prediction_stats = get_prediction_statistics()

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
        recent_predictions=prediction_stats["recent_predictions"]
    )

@app.route("/predict", methods=["GET", "POST"])
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

                save_prediction(
                    subject,
                    message,
                    result
                )

    model_status = get_model_status()

    return render_template(
        "predict.html",
        result=result,
        subject=subject,
        message=message,
        error=error,
        model_status=model_status
    )


@app.route("/predict/batch", methods=["GET", "POST"])
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
                        df["subject"] = (
                            df["subject"].fillna("").astype(str).str.strip()
                        )
                        df["text"] = (
                            df["text"].fillna("").astype(str).str.strip()
                        )
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
                            predictions = predict_batch_emails(
                                df["text"].tolist()
                            )

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
                                download_file = (
                                    f"batch_result_{uuid.uuid4()}.csv"
                                )
                                df.to_csv(
                                    os.path.join("temp", download_file),
                                    index=False,
                                    encoding="utf-8-sig"
                                )
                                results = df.to_dict(orient="records")
                except (OSError, UnicodeError, pd.errors.ParserError) as error_detail:
                    print("Batch prediction error:", error_detail)
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
        model_status=model_status
    )


@app.route("/predict/batch/download/<filename>")
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

@app.route("/dataset")
def dataset():

    df = pd.read_csv("dataset/spam_dataset.csv")

    # Giữ lại vị trí dòng gốc để thao tác xóa đúng sau khi lọc.
    df = df.reset_index()

    # Nhận từ khóa tìm kiếm
    search = request.args.get("search", "").strip()

    # Nhận bộ lọc label
    label = request.args.get("label", "all")

    # Nhận số trang
    page = request.args.get("page", 1, type=int)

    # Số email mỗi trang
    per_page = 20

    # =========================
    # TÌM KIẾM
    # =========================
    if search:
        df = df[
            df["text"].str.contains(
                search,
                case=False,
                na=False
            )
        ]

    # =========================
    # LỌC SPAM / HAM
    # =========================
    if label in ["spam", "ham"]:
        df = df[df["label"] == label]

    # Tổng số email sau khi lọc
    total = len(df)

    # =========================
    # PHÂN TRANG
    # =========================
    total_pages = max(
        1,
        (total + per_page - 1) // per_page
    )

    # Không cho page vượt quá giới hạn
    if page < 1:
        page = 1

    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page

    df_page = df.iloc[start:end]

    emails = df_page.to_dict(orient="records")

    return render_template(
        "dataset.html",
        emails=emails,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        label=label,
        start_index=start
    )
@app.route(
    "/train",
    methods=["GET", "POST"]
)
def train():

    result = None

    df = pd.read_csv(
        "dataset/spam_dataset.csv"
    )

    total = len(df)

    spam_count = len(
        df[
            df["label"].str.lower()
            == "spam"
        ]
    )

    ham_count = len(
        df[
            df["label"].str.lower()
            == "ham"
        ]
    )


    if request.method == "POST":

        try:

            result = train_model()

            flash(
                "Huấn luyện mô hình Naïve Bayes thành công.",
                "success"
            )

        except Exception as e:

            print(
                "Training Error:",
                e
            )

            flash(
                "Có lỗi xảy ra trong quá trình huấn luyện.",
                "danger"
            )


    model_status = get_model_status()
    model_info = get_model_info()

    return render_template(
        "train.html",
        result=result,
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        model_status=model_status,
        model_info=model_info
    )

@app.route("/evaluate")
def evaluate():

    result = evaluate_model()

    return render_template(
        "evaluate.html",
        result=result
    )


@app.route("/compare", methods=["GET", "POST"])
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
                chart_f1 = [
                    round(item["f1"] * 100, 2) for item in results
                ]
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
        chart_f1=chart_f1
    )

@app.route("/history")
def history():

    conn = sqlite3.connect(
        "database/database.db"
    )

    conn.row_factory = sqlite3.Row

    predictions = conn.execute(
        """
        SELECT *
        FROM predictions
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    total_predictions = len(predictions)

    spam_predictions = sum(
        1
        for item in predictions
        if item["prediction"].lower() == "spam"
    )

    ham_predictions = sum(
        1
        for item in predictions
        if item["prediction"].lower() == "ham"
    )

    return render_template(
        "history.html",
        predictions=predictions,
        total_predictions=total_predictions,
        spam_predictions=spam_predictions,
        ham_predictions=ham_predictions
    )

@app.route(
    "/history/delete/<int:id>",
    methods=["POST"]
)
def delete_history(id):

    conn = sqlite3.connect(
        "database/database.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM predictions WHERE id = ?",
        (id,)
    )

    conn.commit()
    conn.close()

    flash(
        "Đã xóa lịch sử dự đoán.",
        "success"
    )

    return redirect(
        url_for("history")
    )

@app.route(
    "/history/delete-all",
    methods=["POST"]
)
def delete_all_history():

    conn = sqlite3.connect(
        "database/database.db"
    )

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM predictions"
    )

    conn.commit()
    conn.close()

    flash(
        "Đã xóa toàn bộ lịch sử dự đoán.",
        "success"
    )

    return redirect(
        url_for("history")
    )

@app.route("/algorithm")
def algorithm():

    total = 0
    spam_count = 0
    ham_count = 0

    try:

        df = pd.read_csv(
            "dataset/spam_dataset.csv"
        )

        df = df.dropna(
            subset=["label", "text"]
        )

        df["label"] = (
            df["label"]
            .astype(str)
            .str.lower()
            .str.strip()
        )

        total = len(df)
        spam_count = len(
            df[df["label"] == "spam"]
        )
        ham_count = len(
            df[df["label"] == "ham"]
        )

    except (OSError, KeyError, ValueError) as error:

        print(
            "Algorithm dataset error:",
            error
        )

    return render_template(
        "algorithm.html",
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        model_info=get_model_info()
    )

@app.route("/dataset/add", methods=["POST"])
def add_dataset():

    label = request.form.get(
        "label",
        ""
    ).strip().lower()

    text = request.form.get(
        "text",
        ""
    ).strip()

    # Kiểm tra label
    if label not in ["spam", "ham"]:

        flash(
            "Nhãn email không hợp lệ.",
            "danger"
        )

        return redirect(
            url_for("dataset")
        )

    # Kiểm tra nội dung
    if not text:

        flash(
            "Nội dung email không được để trống.",
            "warning"
        )

        return redirect(
            url_for("dataset")
        )

    path = "dataset/spam_dataset.csv"

    df = pd.read_csv(path)

    new_row = pd.DataFrame([
        {
            "label": label,
            "text": text
        }
    ])

    df = pd.concat(
        [df, new_row],
        ignore_index=True
    )

    df.to_csv(
        path,
        index=False
    )

    flash(
        "Thêm email vào Dataset thành công.",
        "success"
    )

    return redirect(
        url_for("dataset")
    )

@app.route(
    "/dataset/delete/<int:index>",
    methods=["POST"]
)
def delete_dataset(index):

    path = "dataset/spam_dataset.csv"

    df = pd.read_csv(path)

    if 0 <= index < len(df):

        df = df.drop(
            df.index[index]
        )

        df = df.reset_index(
            drop=True
        )

        df.to_csv(
            path,
            index=False
        )

        flash(
            "Xóa email khỏi Dataset thành công.",
            "success"
        )

    else:

        flash(
            "Không tìm thấy email cần xóa.",
            "danger"
        )

    return redirect(
        url_for("dataset")
    )

@app.route(
    "/dataset/import",
    methods=["POST"]
)
def import_dataset():

    if "file" not in request.files:

        flash(
            "Không tìm thấy file upload.",
            "danger"
        )

        return redirect(
            url_for("dataset")
        )


    file = request.files["file"]


    if file.filename == "":

        flash(
            "Bạn chưa chọn file CSV.",
            "warning"
        )

        return redirect(
            url_for("dataset")
        )


    if not file.filename.lower().endswith(".csv"):

        flash(
            "Chỉ chấp nhận file định dạng CSV.",
            "danger"
        )

        return redirect(
            url_for("dataset")
        )


    try:

        new_df = pd.read_csv(file)


        # =====================
        # KIỂM TRA CỘT
        # =====================

        required_columns = {
            "label",
            "text"
        }

        if not required_columns.issubset(
            new_df.columns
        ):

            flash(
                "File CSV phải có hai cột: label và text.",
                "danger"
            )

            return redirect(
                url_for("dataset")
            )


        # Chỉ giữ 2 cột
        new_df = new_df[
            ["label", "text"]
        ]


        # Xóa dòng rỗng
        new_df = new_df.dropna()


        # Chuẩn hóa
        new_df["label"] = (
            new_df["label"]
            .astype(str)
            .str.lower()
            .str.strip()
        )


        new_df["text"] = (
            new_df["text"]
            .astype(str)
            .str.strip()
        )


        # Chỉ lấy spam / ham
        new_df = new_df[
            new_df["label"].isin(
                ["spam", "ham"]
            )
        ]


        # Xóa email text rỗng
        new_df = new_df[
            new_df["text"] != ""
        ]


        imported_count = len(new_df)


        if imported_count == 0:

            flash(
                "Không có dữ liệu SPAM/HAM hợp lệ trong file.",
                "warning"
            )

            return redirect(
                url_for("dataset")
            )


        path = "dataset/spam_dataset.csv"

        old_df = pd.read_csv(path)


        final_df = pd.concat(
            [
                old_df,
                new_df
            ],
            ignore_index=True
        )


        final_df.to_csv(
            path,
            index=False
        )


        flash(
            f"Import thành công {imported_count} email.",
            "success"
        )


    except Exception as e:

        print(
            "Lỗi Import CSV:",
            e
        )

        flash(
            "Không thể đọc file CSV. Vui lòng kiểm tra lại định dạng.",
            "danger"
        )


    return redirect(
        url_for("dataset")
    )

if __name__ == "__main__":
    app.run(debug=True)
