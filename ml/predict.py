import os
import joblib

from ml.preprocessing import clean_text


MODEL_PATH = "model/model.pkl"
VECTORIZER_PATH = "model/vectorizer.pkl"


def predict_email(text):

    if (
        not os.path.exists(MODEL_PATH)
        or not os.path.exists(VECTORIZER_PATH)
    ):
        return None

    model = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTORIZER_PATH)

    clean = clean_text(text)

    vector = vectorizer.transform([clean])

    prediction = model.predict(vector)[0]

    probabilities = model.predict_proba(vector)[0]

    classes = model.classes_

    probability_result = {}

    for label, probability in zip(classes, probabilities):
        probability_result[label] = float(probability)

    spam_probability = probability_result.get("spam", 0)
    ham_probability = probability_result.get("ham", 0)

    important_words = []
    feature_names = vectorizer.get_feature_names_out()
    indices = vector.nonzero()[1]

    if len(indices) > 0:
        class_names = list(model.classes_)
        spam_index = class_names.index("spam")
        ham_index = class_names.index("ham")
        word_scores = []

        for index in indices:
            tfidf_value = vector[0, index]
            log_probability_difference = (
                model.feature_log_prob_[spam_index, index]
                - model.feature_log_prob_[ham_index, index]
            )
            score = float(tfidf_value * log_probability_difference)

            word_scores.append({
                "word": feature_names[index],
                "score": score
            })

        word_scores.sort(
            key=lambda item: item["score"],
            reverse=prediction == "spam"
        )
        important_words = word_scores[:5]

    return {
        "prediction": prediction,
        "spam_probability": spam_probability,
        "ham_probability": ham_probability,
        "confidence": max(spam_probability, ham_probability),
        "important_words": important_words
    }


def predict_batch_emails(texts):
    if (
        not os.path.exists(MODEL_PATH)
        or not os.path.exists(VECTORIZER_PATH)
    ):
        return None

    model = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTORIZER_PATH)
    cleaned_texts = [clean_text(text) for text in texts]
    vectors = vectorizer.transform(cleaned_texts)
    predictions = model.predict(vectors)
    probabilities = model.predict_proba(vectors)

    classes = list(model.classes_)
    spam_index = classes.index("spam")
    ham_index = classes.index("ham")
    results = []

    for index, prediction in enumerate(predictions):
        spam_probability = float(probabilities[index][spam_index])
        ham_probability = float(probabilities[index][ham_index])
        results.append({
            "prediction": str(prediction),
            "spam_probability": spam_probability,
            "ham_probability": ham_probability,
            "confidence": max(spam_probability, ham_probability)
        })

    return results
