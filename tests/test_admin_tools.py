import os
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("ADMIN_ID", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_order_status_can_only_transition_once(tmp_path):
    main.DB_NAME = str(tmp_path / "admin.sqlite3")
    main.init_db()
    con = sqlite3.connect(main.DB_NAME)
    con.execute("INSERT INTO users (user_id, username) VALUES (1001, 'customer')")
    con.execute(
        "INSERT INTO orders (user_id, service, details, status, created_at) "
        "VALUES (1001, 'PUBG UC', 'test order', 'pending', '2026-11-19T10:00:00+05:00')"
    )
    con.commit()
    con.close()

    assert main.transition_order_status(1, "approved") == (1001, "updated")
    assert main.transition_order_status(1, "rejected") == (1001, "already_processed")

    con = sqlite3.connect(main.DB_NAME)
    status = con.execute("SELECT status FROM orders WHERE id=1").fetchone()[0]
    con.close()
    assert status == "approved"


def test_order_status_reports_missing_order(tmp_path):
    main.DB_NAME = str(tmp_path / "empty.sqlite3")
    main.init_db()
    assert main.transition_order_status(999, "approved") == (None, "not_found")
