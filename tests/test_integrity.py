import sqlite3
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


def test_order_api_rejects_services_not_offered_by_the_app():
    class Request:
        async def json(self):
            return {
                "initData": make_init_data(int(time.time())),
                "service": "Fake service",
                "details": "test"
            }

    import asyncio
    response = asyncio.run(main.api_create_order(Request()))
    assert response.status == 400


def test_order_api_limits_bursts_per_user(tmp_path):
    main.DB_NAME = str(tmp_path / "orders.sqlite3")
    main.init_db()
    init_data = make_init_data(int(time.time()))

    class Request:
        def __init__(self, payload):
            self.payload = payload

        async def json(self):
            return self.payload

    import asyncio
    results = []
    for i in range(6):
        request = Request({
            "initData": init_data,
            "service": "PUBG UC",
            "details": f"test order {i}"
        })
        results.append(asyncio.run(main.api_create_order(request)).status)

    assert results == [200, 200, 200, 200, 200, 429]

def test_balance_credit_is_audited_and_duplicate_reference_rolls_back(tmp_path):
    main.DB_NAME = str(tmp_path / "ledger.sqlite3")
    main.init_db()
    con = sqlite3.connect(main.DB_NAME)
    con.execute("INSERT INTO users (user_id, username) VALUES (2001, 'ledger-user')")
    con.commit()

    con.execute("BEGIN IMMEDIATE")
    assert main.credit_balance(con.cursor(), 2001, 250, "test_credit", "order-1") == 250
    con.commit()

    con.execute("BEGIN IMMEDIATE")
    try:
        main.credit_balance(con.cursor(), 2001, 250, "test_credit", "order-1")
    except sqlite3.IntegrityError:
        con.rollback()
    else:
        raise AssertionError("Duplicate ledger reference should be rejected")

    balance = con.execute("SELECT balance FROM users WHERE user_id=2001").fetchone()[0]
    ledger = con.execute(
        "SELECT amount, balance_after FROM balance_ledger WHERE user_id=2001"
    ).fetchall()
    con.close()
    assert balance == 250
    assert ledger == [(250, 250)]


def test_navigation_stops_background_game_loops():
    html = (Path(__file__).resolve().parents[1] / "webapp" / "index.html").read_text(encoding="utf-8")
    start = html.index("function openPage(id)")
    end = html.index("\nlet presenceTimer", start)
    navigation = html[start:end]
    for cleanup in ("stopXOPoll()", "stopCKPoll()", "stopRPSPoll()", "stopChessPoll()", "stopAgar()"):
        assert cleanup in navigation
