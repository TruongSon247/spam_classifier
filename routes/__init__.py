from flask import Blueprint


main_bp = Blueprint("main", __name__)


from routes import (  # noqa: E402, F401
    admin_routes,
    algorithm_routes,
    api_key_routes,
    audit_routes,
    backup_routes,
    auth_routes,
    dashboard_routes,
    dataset_routes,
    feedback_routes,
    history_routes,
    mail_routes,
    mail_rule_routes,
    model_routes,
    model_version_routes,
    predict_routes,
)
