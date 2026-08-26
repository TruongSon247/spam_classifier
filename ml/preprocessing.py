import re


def clean_text(text):
    if not isinstance(text, str):
        return ""

    # Chuyển về chữ thường
    text = text.lower()

    # Xóa URL
    text = re.sub(r"http\S+|www\S+", "", text)

    # Xóa email address
    text = re.sub(r"\S+@\S+", "", text)

    # Chỉ giữ chữ cái và khoảng trắng
    text = re.sub(r"[^a-zA-Z\s]", " ", text)

    # Xóa khoảng trắng dư
    text = re.sub(r"\s+", " ", text).strip()

    return text