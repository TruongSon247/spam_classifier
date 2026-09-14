import pandas as pd
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from auth import admin_required
from routes import main_bp
from services.audit_service import log_audit


DATASET_PATH = "dataset/spam_dataset.csv"


@main_bp.route("/dataset")
@admin_required
def dataset():
    df = pd.read_csv(DATASET_PATH).reset_index()
    search = request.args.get("search", "").strip()
    label = request.args.get("label", "all")
    page = request.args.get("page", 1, type=int)
    per_page = 20

    if search:
        df = df[df["text"].str.contains(search, case=False, na=False)]
    if label in ["spam", "ham"]:
        df = df[df["label"] == label]

    total = len(df)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    emails = df.iloc[start:start + per_page].to_dict(orient="records")

    return render_template(
        "dataset.html",
        emails=emails,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        label=label,
        start_index=start,
    )


@main_bp.route("/dataset/add", methods=["POST"])
@admin_required
def add_dataset():
    label = request.form.get("label", "").strip().lower()
    text = request.form.get("text", "").strip()
    if label not in ["spam", "ham"]:
        flash("Nhãn email không hợp lệ.", "danger")
        return redirect(url_for("dataset"))
    if not text:
        flash("Nội dung email không được để trống.", "warning")
        return redirect(url_for("dataset"))

    df = pd.read_csv(DATASET_PATH)
    new_row = pd.DataFrame([{"label": label, "text": text}])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(DATASET_PATH, index=False)
    log_audit("DATASET_ADD", "dataset", user_id=int(current_user.id), target_type="dataset", description=f"Added one {label.upper()} sample.")
    flash("Thêm email vào Dataset thành công.", "success")
    return redirect(url_for("dataset"))


@main_bp.route("/dataset/delete/<int:index>", methods=["POST"])
@admin_required
def delete_dataset(index):
    df = pd.read_csv(DATASET_PATH)
    if 0 <= index < len(df):
        df = df.drop(df.index[index]).reset_index(drop=True)
        df.to_csv(DATASET_PATH, index=False)
        log_audit("DATASET_DELETE", "dataset", user_id=int(current_user.id), target_type="dataset_row", target_id=index, description="Deleted one Dataset sample.")
        flash("Xóa email khỏi Dataset thành công.", "success")
    else:
        flash("Không tìm thấy email cần xóa.", "danger")
    return redirect(url_for("dataset"))


@main_bp.route("/dataset/import", methods=["POST"])
@admin_required
def import_dataset():
    if "file" not in request.files:
        flash("Không tìm thấy file upload.", "danger")
        return redirect(url_for("dataset"))

    file = request.files["file"]
    if file.filename == "":
        flash("Bạn chưa chọn file CSV.", "warning")
        return redirect(url_for("dataset"))
    if not file.filename.lower().endswith(".csv"):
        flash("Chỉ chấp nhận file định dạng CSV.", "danger")
        return redirect(url_for("dataset"))

    try:
        new_df = pd.read_csv(file)
        required_columns = {"label", "text"}
        if not required_columns.issubset(new_df.columns):
            flash("File CSV phải có hai cột: label và text.", "danger")
            return redirect(url_for("dataset"))
        new_df = new_df[["label", "text"]].dropna()
        new_df["label"] = (
            new_df["label"].astype(str).str.lower().str.strip()
        )
        new_df["text"] = new_df["text"].astype(str).str.strip()
        new_df = new_df[new_df["label"].isin(["spam", "ham"])]
        new_df = new_df[new_df["text"] != ""]
        imported_count = len(new_df)
        if imported_count == 0:
            flash("Không có dữ liệu SPAM/HAM hợp lệ trong file.", "warning")
            return redirect(url_for("dataset"))

        old_df = pd.read_csv(DATASET_PATH)
        final_df = pd.concat([old_df, new_df], ignore_index=True)
        final_df.to_csv(DATASET_PATH, index=False)
        log_audit("DATASET_IMPORT", "dataset", user_id=int(current_user.id), target_type="dataset", description=f"Imported {imported_count} valid samples.")
        flash(f"Import thành công {imported_count} email.", "success")
    except Exception:
        current_app.logger.exception("Dataset import failed")
        log_audit("DATASET_IMPORT_FAILED", "dataset", user_id=int(current_user.id), target_type="dataset", description="Unable to read or import the CSV file.", status="failed")
        flash("Không thể đọc file CSV. Vui lòng kiểm tra lại định dạng.", "danger")
    return redirect(url_for("dataset"))
