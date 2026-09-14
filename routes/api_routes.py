from flask import Blueprint, current_app, g, jsonify, request

from database.db import save_api_prediction_log
from extensions import limiter
from ml.predict import predict_email
from services.api_key_service import api_error, api_key_required
from services.application_service import get_model_status
from services.model_registry_service import get_active_model_version


api_bp = Blueprint("api", __name__, url_prefix="/api/v1")
MAX_API_TEXT_LENGTH = 50000
MAX_API_SUBJECT_LENGTH = 1000


@api_bp.get("/health")
def health():
    model_status = get_model_status()
    active_model = get_active_model_version()
    return jsonify({
        "success": True,
        "status": "ok",
        "service": "Naive Bayes Spam Classifier",
        "model_ready": bool(model_status.get("trained")),
        "model_outdated": bool(model_status.get("outdated")),
        "active_model": active_model["version"] if active_model else None,
    })


@api_bp.post("/predict")
@limiter.limit(
    "60 per minute",
    exempt_when=lambda: current_app.testing
    and not current_app.config.get("RATELIMIT_TEST_ENABLED", False),
)
@api_key_required
def predict():
    if not request.is_json:
        return api_error("Content-Type must be application/json.", 415)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("Invalid JSON payload.", 400)

    text = payload.get("text")
    subject = payload.get("subject", "")
    if not isinstance(text, str):
        if text is None:
            return api_error("Email text is required.", 400)
        return api_error("Email text must be a string.", 400)
    if not isinstance(subject, str):
        return api_error("Email subject must be a string.", 400)
    text = text.strip()
    if not text:
        return api_error("Email text is required.", 400)
    if len(text) > MAX_API_TEXT_LENGTH:
        return api_error(
            f"Email text must not exceed {MAX_API_TEXT_LENGTH} characters.",
            413,
        )
    if len(subject) > MAX_API_SUBJECT_LENGTH:
        return api_error(
            f"Email subject must not exceed {MAX_API_SUBJECT_LENGTH} characters.",
            413,
        )

    try:
        model_status = get_model_status()
        if not model_status.get("trained"):
            return api_error("Model is not available.", 503)
        result = predict_email(text)
        if result is None:
            return api_error("Model is not available.", 503)
        save_api_prediction_log(
            g.api_key_id,
            result["prediction"],
            result["spam_probability"],
            result["ham_probability"],
            result["confidence"],
        )
        active_model = get_active_model_version()
        return jsonify({
            "success": True,
            "prediction": result["prediction"],
            "spam_probability": result["spam_probability"],
            "ham_probability": result["ham_probability"],
            "confidence": result["confidence"],
            "model_version": (
                active_model["version"] if active_model else None
            ),
            "model_outdated": bool(model_status.get("outdated")),
        })
    except Exception:
        current_app.logger.exception(
            "API prediction failed for key prefix %s", g.api_key_prefix
        )
        return api_error("Unable to complete prediction.", 500)
