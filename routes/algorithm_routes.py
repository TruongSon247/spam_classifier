import pandas as pd
from flask import render_template
from flask_login import login_required

from routes import main_bp
from services.application_service import get_model_info
from services.model_registry_service import get_active_model_version


@main_bp.route("/algorithm")
@login_required
def algorithm():
    total = 0
    spam_count = 0
    ham_count = 0
    try:
        df = pd.read_csv("dataset/spam_dataset.csv")
        df = df.dropna(subset=["label", "text"])
        df["label"] = df["label"].astype(str).str.lower().str.strip()
        total = len(df)
        spam_count = len(df[df["label"] == "spam"])
        ham_count = len(df[df["label"] == "ham"])
    except (OSError, KeyError, ValueError) as error:
        print("Algorithm dataset error:", error)

    return render_template(
        "algorithm.html",
        total=total,
        spam_count=spam_count,
        ham_count=ham_count,
        model_info=get_model_info(),
        active_version=get_active_model_version(),
    )
