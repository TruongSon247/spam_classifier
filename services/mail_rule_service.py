import re

from database.db import (
    create_mail_rule,
    find_rule_conflict,
    get_mail_messages_for_rule_evaluation,
    get_matching_mail_rule,
    update_mail_message_policy,
)


RULE_TYPES = {"whitelist", "blacklist"}
TARGET_TYPES = {"email", "domain"}
DOMAIN_PATTERN = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
EMAIL_PATTERN = re.compile(
    r"^[^@\s]+@(?P<domain>(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})$"
)


def normalize_rule_target(target_type, target_value):
    target_type = (target_type or "").strip().lower()
    value = (target_value or "").strip().lower()
    if target_type not in TARGET_TYPES:
        raise ValueError("Loại đối tượng không hợp lệ.")
    if target_type == "domain":
        value = value.lstrip("@").strip()
        if not DOMAIN_PATTERN.fullmatch(value):
            raise ValueError("Domain không hợp lệ. Ví dụ đúng: example.com.")
    elif not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Địa chỉ Email không hợp lệ.")
    return value


def create_validated_mail_rule(
    rule_type, target_type, target_value, description, created_by
):
    rule_type = (rule_type or "").strip().lower()
    target_type = (target_type or "").strip().lower()
    if rule_type not in RULE_TYPES:
        raise ValueError("Loại quy tắc không hợp lệ.")
    target_value = normalize_rule_target(target_type, target_value)
    existing = find_rule_conflict(target_type, target_value)
    if existing:
        target_label = "Email" if target_type == "email" else "Domain"
        list_label = (
            "Whitelist" if existing["rule_type"] == "whitelist" else "Blacklist"
        )
        raise ValueError(f"{target_label} này đã tồn tại trong {list_label}.")
    description = (description or "").strip()
    if len(description) > 500:
        raise ValueError("Mô tả không được vượt quá 500 ký tự.")
    return create_mail_rule(
        rule_type, target_type, target_value, description, created_by
    )


def evaluate_sender_rules(sender_email):
    sender_email = (sender_email or "").strip().lower()
    if not EMAIL_PATTERN.fullmatch(sender_email):
        return {"matched": False}
    rule = get_matching_mail_rule(sender_email)
    if not rule:
        return {"matched": False}
    return {
        "matched": True,
        "rule_type": rule["rule_type"],
        "target_type": rule["target_type"],
        "target_value": rule["target_value"],
        "rule_id": rule["id"],
    }


def resolve_mail_policy(sender_email, model_prediction):
    match = evaluate_sender_rules(sender_email)
    if not match["matched"]:
        return {
            **match,
            "policy_action": "model",
            "is_quarantined": model_prediction == "spam",
        }
    if match["rule_type"] == "whitelist":
        return {**match, "policy_action": "trusted", "is_quarantined": False}
    return {**match, "policy_action": "blocked", "is_quarantined": True}


def re_evaluate_existing_messages():
    updated = 0
    feedback_preserved = 0
    for message in get_mail_messages_for_rule_evaluation():
        policy = resolve_mail_policy(message["sender_email"], message["prediction"])
        has_feedback = bool(message["user_label"] or message["feedback_at"])
        update_mail_message_policy(
            message["id"],
            policy["policy_action"],
            policy.get("rule_id"),
            None if has_feedback else policy["is_quarantined"],
        )
        updated += 1
        feedback_preserved += int(has_feedback)
    return {"updated": updated, "feedback_preserved": feedback_preserved}
