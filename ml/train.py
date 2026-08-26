import os
import json
import joblib
import pandas as pd
import time
from datetime import datetime

from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import accuracy_score

from ml.preprocessing import clean_text


DATASET_PATH = "dataset/spam_dataset.csv"
MODEL_PATH = "model/model.pkl"
VECTORIZER_PATH = "model/vectorizer.pkl"
METADATA_PATH = "model/model_info.json"


def train_model():

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
    vectorizer = TfidfVectorizer()

    X_train_vector = vectorizer.fit_transform(X_train)
    X_test_vector = vectorizer.transform(X_test)

    # Tạo mô hình Naive Bayes
    model = MultinomialNB(alpha=1.0)

    # Huấn luyện
    model.fit(X_train_vector, y_train)

    # Dự đoán tập test
    predictions = model.predict(X_test_vector)

    # Tính accuracy
    accuracy = accuracy_score(y_test, predictions)

    # Tạo folder model nếu chưa có
    os.makedirs("model", exist_ok=True)

    # Lưu model
    joblib.dump(model, MODEL_PATH)
    joblib.dump(vectorizer, VECTORIZER_PATH)

    training_time = time.time() - start_time

    model_info = {
        "model_name": "Multinomial Naive Bayes",
        "vectorizer": "TF-IDF",
        "alpha": 1.0,
        "total": len(df),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "vocabulary_size": len(vectorizer.vocabulary_),
        "accuracy": float(accuracy),
        "training_time": float(training_time),
        "trained_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as metadata_file:
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
        "training_time": training_time,
        "vocabulary_size": len(vectorizer.vocabulary_),
        "trained_at": model_info["trained_at"]
    }


if __name__ == "__main__":
    result = train_model()

    print("Training completed")
    print("Accuracy:", result["accuracy"])
    print("Train:", result["train_size"])
    print("Test:", result["test_size"])
