
import os
import sqlite3
import asyncio
import hmac
import hashlib
import json
import time
from urllib.parse import parse_qsl
from pathlib import Path
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
DB_NAME = "idonat_robot.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi!")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

promo_waiting = set()


def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            inviter INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            amount INTEGER,
            limit_count INTEGER,
            used_count INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_redemptions (
            user_id INTEGER,
            code TEXT,
            UNIQUE(user_id, code)
        )
    """)

    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT balance, referrals, points FROM users WHERE user_id=?",
        (user_id,)
    )
    result = cur.fetchone()
    con.close()
    return result


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            *([[KeyboardButton(text="🚀 Mini ilovani ochish", web_app=WebAppInfo(url=WEBAPP_URL))]] if WEBAPP_URL.startswith("https://") else []),
            [KeyboardButton(text="🛍 Xizmatlar")],
            [KeyboardButton(text="🎮 PUBG UC"),
             KeyboardButton(text="📞 Virtual raqamlar")],
            [KeyboardButton(text="💳 Balans"),
             KeyboardButton(text="📦 Buyurtmalarim")],
            [KeyboardButton(text="👨‍💻 Yordam")]
        ],
        resize_keyboard=True
    )


def balance_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Mening balansim")],
            [KeyboardButton(text="🤝 Referal"),
             KeyboardButton(text="🎟 Promokod")],
            [KeyboardButton(text="🏆 TOP 10")],
            [KeyboardButton(text="⬅️ Orqaga")]
        ],
        resize_keyboard=True
    )


@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    parts = message.text.split()
    inviter = 0

    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            inviter = int(parts[1][4:])
        except ValueError:
            inviter = 0

    con = db()
    cur = con.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cur.fetchone()

    if not exists:
        if inviter == user_id:
            inviter = 0

        cur.execute(
            """INSERT INTO users
            (user_id, username, balance, referrals, points, inviter)
            VALUES (?, ?, 0, 0, 0, ?)""",
            (user_id, username, inviter)
        )

        if inviter:
            cur.execute(
                "UPDATE users SET balance=balance+100, referrals=referrals+1 WHERE user_id=?",
                (inviter,)
            )

    con.commit()
    con.close()

    await message.answer(
        "🤖 <b>iDonat Robotga xush kelibsiz!</b>\n\n"
        "Kerakli bo‘limni tanlang.",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == "💳 Balans")
async def balance_menu(message: Message):
    await message.answer(
        "💳 <b>Balans bo‘limi</b>\n\nKerakli bo‘limni tanlang:",
        reply_markup=balance_keyboard()
    )


@dp.message(F.text == "💰 Mening balansim")
async def my_balance(message: Message):
    user = get_user(message.from_user.id)

    if user:
        await message.answer(
            f"💰 Balansingiz: <b>{user[0]:,} so‘m</b>\n"
            f"🤝 Taklif qilganlaringiz: <b>{user[1]}</b>\n"
            f"⭐ O‘yin ochkolari: <b>{user[2]}</b>"
        )


@dp.message(F.text == "🤝 Referal")
async def referral(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user_id}"

    await message.answer(
        "🤝 <b>Referal tizimi</b>\n\n"
        "Do‘stlaringizni taklif qiling!\n"
        "Har bir yangi foydalanuvchi uchun 100 so‘m "
        "virtual balans beriladi.\n\n"
        f"👥 Taklif qilganlaringiz: <b>{user[1]}</b>\n"
        f"💰 Referal havolangiz:\n<code>{link}</code>"
    )


@dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message):
    promo_waiting.add(message.from_user.id)
    await message.answer(
        "🎟 Promokodingizni yuboring.\n"
        "Bekor qilish uchun /cancel yozing."
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    promo_waiting.discard(message.from_user.id)
    await message.answer("Bekor qilindi.", reply_markup=balance_keyboard())


async def redeem_promo(message: Message):
    user_id = message.from_user.id
    code = message.text.strip().upper()

    con = db()
    cur = con.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")

        cur.execute(
            "SELECT amount, limit_count, used_count FROM promo_codes WHERE code=?",
            (code,)
        )
        promo = cur.fetchone()

        if not promo:
            con.rollback()
            await message.answer("❌ Bunday promokod topilmadi.")
            return

        amount, limit_count, used_count = promo

        if used_count >= limit_count:
            con.rollback()
            await message.answer("❌ Bu promokodning limiti tugagan.")
            return

        cur.execute(
            "SELECT 1 FROM promo_redemptions WHERE user_id=? AND code=?",
            (user_id, code)
        )

        if cur.fetchone():
            con.rollback()
            await message.answer("❌ Siz bu promokoddan foydalangansiz.")
            return

        cur.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (amount, user_id)
        )

        cur.execute(
            "UPDATE promo_codes SET used_count=used_count+1 WHERE code=?",
            (code,)
        )

        cur.execute(
            "INSERT INTO promo_redemptions (user_id, code) VALUES (?, ?)",
            (user_id, code)
        )

        con.commit()
        await message.answer(
            f"✅ Promokod qabul qilindi!\n"
            f"💰 Balansingizga {amount:,} so‘m qo‘shildi."
        )

    except sqlite3.Error:
        con.rollback()
        await message.answer("❌ Xatolik yuz berdi. Keyinroq urinib ko‘ring.")

    finally:
        con.close()


@dp.message(Command("addpromo"))
async def add_promo(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return

    parts = message.text.split()

    if len(parts) != 4:
        await message.answer(
            "Format:\n/addpromo KOD MIQDOR LIMIT\n"
            "Masalan: /addpromo TEST100 1000 50"
        )
        return

    try:
        code = parts[1].upper()
        amount = int(parts[2])
        limit_count = int(parts[3])

        if amount <= 0 or limit_count <= 0:
            raise ValueError

        con = db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO promo_codes (code, amount, limit_count) VALUES (?, ?, ?)",
            (code, amount, limit_count)
        )
        con.commit()
        con.close()

        await message.answer("✅ Promokod yaratildi!")

    except ValueError:
        await message.answer("❌ Miqdor va limit musbat son bo‘lishi kerak.")
    except sqlite3.IntegrityError:
        await message.answer("❌ Bu promokod avval yaratilgan.")


@dp.message(F.text == "🏆 TOP 10")
async def top10(message: Message):
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT username, referrals
        FROM users
        ORDER BY referrals DESC, user_id ASC
        LIMIT 10
    """)
    rows = cur.fetchall()
    con.close()

    text = "🏆 <b>REFERAL TOP 10</b>\n\n"

    if not rows:
        text += "Hozircha natijalar yo‘q."
    else:
        for i, row in enumerate(rows, 1):
            name = ("@" + row[0]) if row[0] else "Foydalanuvchi"
            text += f"{i}. {name} — {row[1]} ta\n"

    text += "\n⭐ O‘yin TOP 10 alohida tizimda yuritiladi."
    await message.answer(text)


@dp.message(F.text == "🛍 Xizmatlar")
async def services(message: Message):
    await message.answer(
        "🛍 <b>Xizmatlar</b>\n\n"
        "Bu bo‘lim provayder ulangandan keyin faollashadi."
    )


@dp.message(F.text == "🎮 PUBG UC")
async def pubg(message: Message):
    await message.answer(
        "🎮 <b>PUBG UC</b>\n\n"
        "UC buyurtmalari rasmiy provayder ulangandan keyin faollashadi."
    )


@dp.message(F.text == "📞 Virtual raqamlar")
async def numbers(message: Message):
    await message.answer(
        "📞 <b>Virtual raqamlar</b>\n\n"
        "Bu xizmat provayder ulangandan keyin faollashadi."
    )


@dp.message(F.text == "📦 Buyurtmalarim")
async def orders(message: Message):
    await message.answer("📦 Hozircha buyurtmalaringiz yo‘q.")


@dp.message(F.text == "👨‍💻 Yordam")
async def help_user(message: Message):
    await message.answer(
        "👨‍💻 <b>Yordam</b>\n\n"
        "Savollaringiz bo‘lsa, administratorga murojaat qiling."
    )


@dp.message(F.text == "⬅️ Orqaga")
async def back(message: Message):
    await message.answer(
        "Asosiy menyu:",
        reply_markup=main_keyboard()
    )


@dp.message(F.text)
async def other_messages(message: Message):
    user_id = message.from_user.id

    if user_id in promo_waiting:
        promo_waiting.discard(user_id)
        await redeem_promo(message)
        return

    await message.answer(
        "Kerakli bo‘limni menyudan tanlang.",
        reply_markup=main_keyboard()
    )



def validate_webapp_init_data(init_data):
    if not init_data or not BOT_TOKEN:
        return None

    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = fields.pop("hash", "")
        if not received_hash:
            return None

        check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(fields.items())
        )
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(fields.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400:
            return None

        user = json.loads(fields.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


async def api_me(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)

    telegram_user = validate_webapp_init_data(payload.get("initData", ""))
    if not telegram_user:
        return web.json_response(
            {"error": "Telegram orqali qayta oching"}, status=401
        )

    user_id = int(telegram_user["id"])
    username = telegram_user.get("username", "") or ""
    con = db()
    cur = con.cursor()
    cur.execute(
        """INSERT OR IGNORE INTO users
        (user_id, username, balance, referrals, points, inviter)
        VALUES (?, ?, 0, 0, 0, 0)""",
        (user_id, username)
    )
    cur.execute(
        "UPDATE users SET username=? WHERE user_id=?",
        (username, user_id)
    )
    cur.execute(
        "SELECT balance, referrals, points FROM users WHERE user_id=?",
        (user_id,)
    )
    account = cur.fetchone()

    cur.execute("""
        SELECT username, referrals
        FROM users
        ORDER BY referrals DESC, user_id ASC
        LIMIT 10
    """)
    leaders = [
        {"username": row[0] or "", "referrals": row[1]}
        for row in cur.fetchall()
    ]
    con.commit()
    con.close()

    me = await bot.get_me()
    referral_link = f"https://t.me/{me.username}?start=ref_{user_id}"

    return web.json_response({
        "user_id": user_id,
        "username": username,
        "first_name": telegram_user.get("first_name", ""),
        "last_name": telegram_user.get("last_name", ""),
        "balance": account[0] if account else 0,
        "referrals": account[1] if account else 0,
        "points": account[2] if account else 0,
        "referral_link": referral_link,
        "top10": leaders,
        "orders": []
    })


async def mini_app_home(request):
    page = Path(__file__).parent / "webapp" / "index.html"
    if not page.exists():
        return web.Response(text="Mini App fayli topilmadi", status=404)
    return web.FileResponse(page)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", mini_app_home)
    app.router.add_post("/api/me", api_me)
    app.router.add_get("/health", lambda request: web.json_response({"ok": True, "app": "iDonat Robot"}))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Mini App web server {port}-portda ishga tushdi")
    return runner


async def main():
    init_db()
    print("iDonat Robot ishga tushdi!")
    runner = await start_web_server()
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
