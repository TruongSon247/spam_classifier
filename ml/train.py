import os
import json
import joblib
import pandas as pd
import time
from datetime import datetime

from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from ml.preprocessing import clean_text


DATASET_PATH = "dataset/spam_dataset.csv"
MODEL_PATH = "model/model.pkl"
VECTORIZER_PATH = "model/vectorizer.pkl"
METADATA_PATH = "model/model_info.json"


def train_model(output_dir="model", metadata_updates=None):

    start_time = time.time()

    df = pd.read_csv(DATASET_PATH)

    # Loại bỏ dòng bị thiếu dữ liệu
    df = df.dropna()

    # Tiền xử lý
    df["clean_text"] = df["text"].apply(clean_text)

    X = df["clean_text"]
    y = df["label"]

    # Chia dữ liệu train/test
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y
    )

    # Vector hóa văn bản
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True
    )

    X_train_vector = vectorizer.fit_transform(X_train)
    X_test_vector = vectorizer.transform(X_test)

    # Tạo mô hình Naive Bayes
    model = MultinomialNB(alpha=1.0)

    # Huấn luyện
    model.fit(X_train_vector, y_train)

    # Dự đoán tập test
    predictions = model.predict(X_test_vector)

    # Tính các chỉ số đánh giá trên cùng tập test cố định.
    accuracy = accuracy_score(y_test, predictions)
    precision = precision_score(y_test, predictions, pos_label="spam")
    recall = recall_score(y_test, predictions, pos_label="spam")
    f1 = f1_score(y_test, predictions, pos_label="spam")
    cm = confusion_matrix(y_test, predictions, labels=["ham", "spam"])

    # output_dir cho phép registry huấn luyện vào staging trước khi activate.
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "model.pkl")
    vectorizer_path = os.path.join(output_dir, "vectorizer.pkl")
    metadata_path = os.path.join(output_dir, "model_info.json")

    # Lưu model
    joblib.dump(model, model_path)
    joblib.dump(vectorizer, vectorizer_path)

    training_time = time.time() - start_time

    model_info = {
        "model_name": "Multinomial Naive Bayes",
        "vectorizer": "TF-IDF",
        "ngram_range": [1, 2],
        "unicode_support": True,
        "alpha": 1.0,
        "total": len(df),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "vocabulary_size": len(vectorizer.vocabulary_),
        "accuracy": float(accuracy),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "tn": int(cm[0][0]),
        "fp": int(cm[0][1]),
        "fn": int(cm[1][0]),
        "tp": int(cm[1][1]),
        "training_time": float(training_time),
        "trained_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }
    if metadata_updates:
        model_info.update(metadata_updates)

    with open(metadata_path, "w", encoding="utf-8") as metadata_file:
        json.dump(
            model_info,
            metadata_file,
            ensure_ascii=False,
            indent=4
        )

    return {
        "total": len(df),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tn": int(cm[0][0]),
        "fp": int(cm[0][1]),
        "fn": int(cm[1][0]),
        "tp": int(cm[1][1]),
        "training_time": training_time,
        "vocabulary_size": len(vectorizer.vocabulary_),
        "trained_at": model_info["trained_at"],
        "model_path": model_path,
        "vectorizer_path": vectorizer_path,
        "info_path": metadata_path,
        **(metadata_updates or {}),
    }


if __name__ == "__main__":
    result = train_model()

    print("Training completed")
    print("Accuracy:", result["accuracy"])
    print("Train:", result["train_size"])
    print("Test:", result["test_size"])
