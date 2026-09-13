import html
import re
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def html_to_text(value):
    parser = _HTMLTextExtractor()
    parser.feed(value or "")
    text = html.unescape("".join(parser.parts))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def decode_header_value(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return str(value)


def parse_address(value):
    addresses = getaddresses([decode_header_value(value)])
    if not addresses:
        return "", ""
    name, address = addresses[0]
    return name.strip(), address.strip().lower()


def normalize_date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.isoformat() if parsed else None
    except (TypeError, ValueError, OverflowError):
        return None


def extract_email_body(message):
    plain_parts = []
    html_parts = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(str(content).strip())
        else:
            html_parts.append(str(content))
    plain_text = "\n\n".join(part for part in plain_parts if part)
    return plain_text or html_to_text("\n".join(html_parts))
