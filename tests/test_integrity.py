import hashlib
import hmac
import json
import os
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("ADMIN_ID", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        element_id = attrs.get("id")
        if element_id:
            self.ids.append(element_id)
            self.elements[element_id] = (tag, attrs)


def make_init_data(auth_date):
    fields = {
        "auth_date": str(auth_date),
        "user": json.dumps({"id": 123456, "first_name": "Test"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", main.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_mini_app_has_unique_ids_and_balance_page_is_reachable():
    html = (Path(__file__).resolve().parents[1] / "webapp" / "index.html").read_text(encoding="utf-8")
    parser = IdCollector()
    parser.feed(html)

    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    assert duplicates == []
    assert parser.elements["balance"][0] == "section"
    assert "page" in parser.elements["balance"][1].get("class", "").split()
    assert parser.elements["balanceAmount"][0] == "div"
    assert "getElementById('balanceAmount')" in html


def test_webapp_init_data_accepts_fresh_signed_data():
    assert main.validate_webapp_init_data(make_init_data(int(time.time())))["id"] == 123456


def test_webapp_init_data_rejects_future_and_expired_data():
    now = int(time.time())
    assert main.validate_webapp_init_data(make_init_data(now + 120)) is None
    assert main.validate_webapp_init_data(make_init_data(now - 86401)) is None


def test_api_middleware_rejects_non_object_json():
    class Request:
        path = "/api/me"

        async def json(self):
            return ["not", "an", "object"]

    async def handler(request):
        raise AssertionError("Handler must not run for invalid JSON shape")

    import asyncio
    response = asyncio.run(main.require_channel_subscription(Request(), handler))
    assert response.status == 400
