import time

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC

from ml.preprocessing import clean_text


DATASET_PATH = "dataset/spam_dataset.csv"


def compare_models():
    df = pd.read_csv(DATASET_PATH)
    df = df.dropna(subset=["label", "text"])
    df["label"] = df["label"].astype(str).str.lower().str.strip()
    df = df[df["label"].isin(["spam", "ham"])].copy()
    df["clean_text"] = df["text"].astype(str).apply(clean_text)
    df = df[df["clean_text"] != ""].reset_index(drop=True)

    if len(df) == 0:
        raise ValueError("Dataset không có dữ liệu hợp lệ.")
    if df["label"].nunique() < 2:
        raise ValueError("Dataset phải có cả SPAM và HAM.")

    X_train, X_test, y_train, y_test = train_test_split(
        df["clean_text"],
        df["label"],
        test_size=0.2,
        random_state=42,
        stratify=df["label"]
    )

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True
    )
    X_train_vector = vectorizer.fit_transform(X_train)
    X_test_vector = vectorizer.transform(X_test)

    models = [
        {
            "name": "Multinomial Naive Bayes",
            "short_name": "Naive Bayes",
            "key": "nb",
            "model": MultinomialNB(alpha=1.0)
        },
        {
            "name": "Logistic Regression",
            "short_name": "Logistic",
            "key": "lr",
            "model": LogisticRegression(max_iter=1000, random_state=42)
        },
        {
            "name": "Linear SVM",
            "short_name": "Linear SVM",
            "key": "svm",
            "model": LinearSVC(random_state=42, max_iter=5000)
        }
    ]
    results = []

    for item in models:
        model = item["model"]
        start_time = time.perf_counter()
        model.fit(X_train_vector, y_train)
        training_time = time.perf_counter() - start_time
        predictions = model.predict(X_test_vector)

        results.append({
            "name": item["name"],
            "short_name": item["short_name"],
            "key": item["key"],
            "accuracy": float(accuracy_score(y_test, predictions)),
            "precision": float(precision_score(
                y_test,
                predictions,
                pos_label="spam",
                zero_division=0
            )),
            "recall": float(recall_score(
                y_test,
                predictions,
                pos_label="spam",
                zero_division=0
            )),
            "f1": float(f1_score(
                y_test,
                predictions,
                pos_label="spam",
                zero_division=0
            )),
            "training_time": float(training_time)
        })

    results.sort(key=lambda item: item["f1"], reverse=True)

    return {
        "results": results,
        "total": len(df),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "vocabulary_size": len(vectorizer.vocabulary_)
    }
