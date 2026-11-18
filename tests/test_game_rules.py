import asyncio
import os
import sqlite3

# aiogram only validates the token format during Bot construction; no API calls are made.
os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("ADMIN_ID", "0")

import main


def initial_checkers_board():
    board = [""] * 64
    for row in range(3):
        for col in range(8):
            if (row + col) % 2:
                board[row * 8 + col] = "b"
    for row in range(5, 8):
        for col in range(8):
            if (row + col) % 2:
                board[row * 8 + col] = "w"
    return board


def test_xo_winner_and_draw():
    assert main.xo_winner(["X", "X", "X", "", "O", "", "", "", "O"]) == "X"
    assert main.xo_winner(["X", "O", "X", "X", "O", "O", "O", "X", "X"]) == "draw"
    assert main.xo_winner([""] * 9) == ""


def test_checkers_initial_position_has_seven_white_moves():
    moves = main.checkers_legal_boards(initial_checkers_board(), "w")
    assert len(moves) == 7
    assert all(len(board) == 64 for board in moves)


def test_referral_reward_is_only_paid_once(tmp_path):
    main.DB_NAME = str(tmp_path / "test.sqlite3")
    main.init_db()
    con = sqlite3.connect(main.DB_NAME)
    con.execute(
        "INSERT INTO users (user_id, username, inviter, referral_rewarded) VALUES (1, 'inviter', 0, 1)"
    )
    con.execute(
        "INSERT INTO users (user_id, username, inviter, referral_rewarded) VALUES (2, 'new_user', 1, 0)"
    )
    con.commit()
    con.close()

    asyncio.run(main.finish_referral(2))
    asyncio.run(main.finish_referral(2))

    con = sqlite3.connect(main.DB_NAME)
    balance, referrals = con.execute(
        "SELECT balance, referrals FROM users WHERE user_id=1"
    ).fetchone()
    con.close()
    assert (balance, referrals) == (100, 1)
