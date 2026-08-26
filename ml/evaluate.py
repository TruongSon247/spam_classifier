import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)

from ml.preprocessing import clean_text


DATASET_PATH = "dataset/spam_dataset.csv"
MODEL_PATH = "model/model.pkl"
VECTORIZER_PATH = "model/vectorizer.pkl"


def evaluate_model():

    # Đọc dataset
    df = pd.read_csv(DATASET_PATH)

    # Loại dữ liệu rỗng
    df = df.dropna(subset=["label", "text"])

    # Chuẩn hóa label
    df["label"] = df["label"].str.lower().str.strip()

    # Tiền xử lý
    df["clean_text"] = df["text"].apply(clean_text)

    X = df["clean_text"]
    y = df["label"]

    # Chia lại đúng như lúc train
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y
    )

    # Load model đã huấn luyện
    model = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTORIZER_PATH)

    # Vector hóa tập test
    X_test_vector = vectorizer.transform(X_test)

    # Dự đoán
    predictions = model.predict(X_test_vector)

    # Các chỉ số
    accuracy = accuracy_score(y_test, predictions)

    precision = precision_score(
        y_test,
        predictions,
        pos_label="spam"
    )

    recall = recall_score(
        y_test,
        predictions,
        pos_label="spam"
    )

    f1 = f1_score(
        y_test,
        predictions,
        pos_label="spam"
    )

    # Confusion Matrix
    cm = confusion_matrix(
        y_test,
        predictions,
        labels=["ham", "spam"]
    )

    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,

        "tn": int(cm[0][0]),
        "fp": int(cm[0][1]),
        "fn": int(cm[1][0]),
        "tp": int(cm[1][1]),

        "test_size": len(y_test)
    }