
import chess
import os
import sqlite3
import asyncio
import hmac
import html
import hashlib
import json
import re
import time
import tempfile
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import parse_qsl
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, web

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
REQUIRED_CHANNEL = "@Cr7_Siu_Pubg"
DB_PATH_CONFIGURED = bool(os.getenv("DB_PATH", "").strip())
DB_NAME = os.getenv("DB_PATH", "idonat_robot.db").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi!")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

promo_waiting = set()


def language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O‘zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")]
    ])


def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url="https://t.me/Cr7_Siu_Pubg")],
        [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_subscription")]
    ])


async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as exc:
        print(f"Obuna tekshirish xatosi: {exc}")
        return None


async def send_language_prompt(target):
    await target.answer("🌐 <b>Tilni tanlang / Выберите язык / Choose your language</b>", reply_markup=language_keyboard())


async def send_subscription_prompt(target, user_id=None):
    uid = user_id or target.from_user.id
    t = BOT_TEXT[user_language(uid)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["join"], url="https://t.me/Cr7_Siu_Pubg")],
        [InlineKeyboardButton(text=t["check"], callback_data="check_subscription")]
    ])
    await target.answer(t["subscribe"], reply_markup=keyboard)


async def finish_referral(user_id):
    # Claim the reward atomically so duplicate updates cannot pay twice.
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT inviter, referral_rewarded FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row and not row[1]:
            cur.execute(
                "UPDATE users SET referral_rewarded=1 WHERE user_id=? AND referral_rewarded=0",
                (user_id,)
            )
            if cur.rowcount == 1:
                inviter = row[0]
                if inviter and inviter != user_id:
                    cur.execute("UPDATE users SET referrals=referrals+1 WHERE user_id=?", (inviter,))
                    credit_balance(cur, inviter, 100, "referral", str(user_id))
        con.commit()
    except sqlite3.Error:
        con.rollback()
        raise
    finally:
        con.close()


class AccessGate(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)
        if event.text and event.text.split()[0].startswith("/start"):
            return await handler(event, data)
        con = db()
        cur = con.cursor()
        cur.execute("SELECT language FROM users WHERE user_id=?", (event.from_user.id,))
        row = cur.fetchone()
        con.close()
        if not row or not row[0]:
            await send_language_prompt(event)
            return
        subscribed = await is_subscribed(event.from_user.id)
        if subscribed is not True:
            if subscribed is None:
                await event.answer(tr(event.from_user.id, "sub_admin"))
            else:
                await send_subscription_prompt(event, event.from_user.id)
            return
        return await handler(event, data)


dp.message.middleware(AccessGate())


def db():
    # Use durable commits and wait briefly for concurrent Telegram/API requests.
    con = sqlite3.connect(DB_NAME, timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA synchronous=FULL")
    return con


def credit_balance(cur, user_id, amount, reason, reference):
    """Credit a user's virtual balance and append an immutable audit row.
    Caller must wrap this operation in the same SQLite transaction.
    """
    amount = int(amount)
    if amount <= 0 or not reason or not reference:
        raise ValueError("Balans qo‘shish ma’lumotlari noto‘g‘ri")
    cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    if cur.rowcount != 1:
        raise ValueError("Foydalanuvchi hisobi topilmadi")
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    balance_after = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO balance_ledger (user_id, amount, balance_after, reason, reference, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, amount, balance_after, reason, reference,
         datetime.now(ZoneInfo("Asia/Tashkent")).isoformat(timespec="seconds"))
    )
    return balance_after


def init_db():
    if (os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID")) and not DB_PATH_CONFIGURED:
        print("OGOHLANTIRISH: Railway uchun DB_PATH sozlanmagan. Balanslar yo‘qolmasligi uchun Persistent Volume ulang va DB_PATH=/data/idonat_robot.db qiling.")
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)
    con = db()
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=FULL")
    cur.execute("PRAGMA busy_timeout=20000")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            inviter INTEGER DEFAULT 0,
            language TEXT DEFAULT '',
            referral_rewarded INTEGER DEFAULT 1,
            welcome_sent INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS balance_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL CHECK(amount > 0),
            balance_after INTEGER NOT NULL,
            reason TEXT NOT NULL,
            reference TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(reason, reference)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_balance_ledger_user ON balance_ledger(user_id, id DESC)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_presence (
            user_id INTEGER PRIMARY KEY,
            last_seen REAL NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_app_presence_last_seen ON app_presence(last_seen)")
    cur.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cur.fetchall()}
    if "language" not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT ''")
    if "referral_rewarded" not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN referral_rewarded INTEGER DEFAULT 1")
    if "welcome_sent" not in columns:
        # Existing accounts have already passed onboarding; greet only newly registered users.
        cur.execute("ALTER TABLE users ADD COLUMN welcome_sent INTEGER DEFAULT 1")

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_bonus_claims (
            user_id INTEGER,
            claim_date TEXT,
            UNIQUE(user_id, claim_date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS xo_rooms (
            room_id TEXT PRIMARY KEY,
            player_x INTEGER NOT NULL,
            player_o INTEGER,
            board TEXT NOT NULL DEFAULT '["","","","","","","","",""]',
            turn TEXT NOT NULL DEFAULT 'X',
            status TEXT NOT NULL DEFAULT 'waiting',
            winner TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rps_rooms (
            room_id TEXT PRIMARY KEY,
            player_a INTEGER NOT NULL,
            player_b INTEGER,
            choice_a TEXT NOT NULL DEFAULT '',
            choice_b TEXT NOT NULL DEFAULT '',
            round_no INTEGER NOT NULL DEFAULT 1,
            score_a INTEGER NOT NULL DEFAULT 0,
            score_b INTEGER NOT NULL DEFAULT 0,
            resolved INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'waiting',
            updated_at REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chess_rooms (
            room_id TEXT PRIMARY KEY,
            player_white INTEGER NOT NULL,
            player_black INTEGER,
            fen TEXT NOT NULL,
            moves TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'waiting',
            winner TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chess_rooms_queue ON chess_rooms(status, updated_at)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS checkers_rooms (
            room_id TEXT PRIMARY KEY,
            player_x INTEGER NOT NULL,
            player_o INTEGER,
            board TEXT NOT NULL,
            turn TEXT NOT NULL DEFAULT 'X',
            status TEXT NOT NULL DEFAULT 'waiting',
            winner TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service TEXT NOT NULL,
            details TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    # Keep common ranking, order-history and matchmaking lookups fast.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_referrals ON users(referrals DESC, user_id ASC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id, id DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_xo_rooms_queue ON xo_rooms(status, updated_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_checkers_rooms_queue ON checkers_rooms(status, updated_at)")

    con.commit()
    con.close()


def get_user(user_id, username=""):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username or "")
    )
    cur.execute(
        "SELECT balance, referrals, points FROM users WHERE user_id=?",
        (user_id,)
    )
    result = cur.fetchone()
    con.commit()
    con.close()
    return result



BOT_TEXT = {
 "uz":{"services":"🛍 Xizmatlar","pubg":"🎮 PUBG UC","numbers":"📞 Virtual raqamlar","balance":"💳 Balans","orders":"📦 Buyurtmalarim","help":"👨‍💻 Yordam","app":"🚀 Mini ilovani ochish","my_balance":"💰 Mening balansim","referral":"🤝 Referal","promo":"🎟 Promokod","top":"🏆 TOP 10","back":"⬅️ Orqaga","home":"🤖 <b>iDonat Robotga xush kelibsiz!</b>\n\nKerakli bo‘limni tanlang.","balance_title":"💳 <b>Balans bo‘limi</b>\n\nKerakli bo‘limni tanlang:","balance_info":"💰 Balansingiz: <b>{balance:,} so‘m</b>\n🤝 Taklif qilganlaringiz: <b>{referrals}</b>\n⭐ O‘yin ochkolari: <b>{points}</b>","ref_info":"🤝 <b>Referal tizimi</b>\n\nDo‘stlaringizni taklif qiling! Har bir yangi foydalanuvchi uchun 100 so‘m virtual balans beriladi.\n\n👥 Taklif qilganlaringiz: <b>{count}</b>\n💰 Havolangiz:\n<code>{link}</code>","promo_prompt":"🎟 Promokodingizni yuboring. Bekor qilish uchun /cancel yozing.","cancel":"Bekor qilindi.","top_title":"🏆 <b>REFERAL TOP 10</b>\n\n","no_results":"Hozircha natijalar yo‘q.","user":"Foydalanuvchi","top_note":"\n⭐ O‘yin TOP 10 alohida tizimda yuritiladi.","services_info":"🛍 <b>Xizmatlar</b>\n\nBuyurtmalarni Mini App orqali yuboring. Provayder ulanmagan xizmatlar avtomatik bajarilmaydi.","pubg_info":"🎮 <b>PUBG UC</b>\n\nUC buyurtmasini Mini App orqali yuborishingiz mumkin. Rasmiy provayder ulanmaguncha avtomatik yetkazib berish mavjud emas.","numbers_info":"📞 <b>Virtual raqamlar</b>\n\nBu xizmat provayder ulangandan keyin faollashadi.","orders_info":"📦 Buyurtmalaringizni ko‘rish uchun Mini App ichidagi «Buyurtmalar» bo‘limini oching.","help_info":"👨‍💻 <b>Yordam</b>\n\n/start — bosh menyu\n/app — Mini App\n/balance — balans\n/referral — referal havolasi\n/top — TOP 10\n/orders — buyurtmalarim\n/language — tilni almashtirish\n/cancel — amalni bekor qilish\n\nSavollar bo‘lsa, administratorga murojaat qiling.","back_info":"Asosiy menyu:","choose":"Kerakli bo‘limni menyudan tanlang.","mini":"🚀 <b>Mini ilovani ochish:</b>","app_missing":"Mini App manzili sozlanmagan. Administratorga murojaat qiling.","language_saved":"Til saqlandi!","subscribe":"🔒 <b>Botdan foydalanish uchun kanalimizga obuna bo‘ling.</b>\n\n📢 @Cr7_Siu_Pubg kanaliga qo‘shiling, so‘ng «Obunani tekshirish» tugmasini bosing.","join":"📢 Kanalga obuna bo‘lish","check":"✅ Obunani tekshirish","sub_admin":"⚠️ Botni @Cr7_Siu_Pubg kanaliga administrator qilib qo‘shing.","sub_ok":"✅ Obuna tasdiqlandi!","sub_no":"❌ Hali kanalga obuna bo‘lmagansiz.","lang_prompt":"Tilni tanlang:"},
 "ru":{"services":"🛍 Услуги","pubg":"🎮 PUBG UC","numbers":"📞 Виртуальные номера","balance":"💳 Баланс","orders":"📦 Мои заказы","help":"👨‍💻 Помощь","app":"🚀 Открыть Mini App","my_balance":"💰 Мой баланс","referral":"🤝 Рефералы","promo":"🎟 Промокод","top":"🏆 ТОП 10","back":"⬅️ Назад","home":"🤖 <b>Добро пожаловать в iDonat Robot!</b>\n\nВыберите нужный раздел.","balance_title":"💳 <b>Баланс</b>\n\nВыберите нужный пункт:","balance_info":"💰 Баланс: <b>{balance:,} сум</b>\n🤝 Приглашено вами: <b>{referrals}</b>\n⭐ Игровые очки: <b>{points}</b>","ref_info":"🤝 <b>Реферальная система</b>\n\nПриглашайте друзей! За каждого нового пользователя начисляется 100 сум виртуального баланса.\n\n👥 Приглашено: <b>{count}</b>\n💰 Ваша ссылка:\n<code>{link}</code>","promo_prompt":"🎟 Отправьте промокод. Для отмены используйте /cancel.","cancel":"Отменено.","top_title":"🏆 <b>РЕФЕРАЛЬНЫЙ ТОП 10</b>\n\n","no_results":"Пока результатов нет.","user":"Пользователь","top_note":"\n⭐ Игровой ТОП 10 ведётся отдельно.","services_info":"🛍 <b>Услуги</b>\n\nЗаявки отправляются через Mini App. Автоматическое выполнение пока недоступно без провайдера.","pubg_info":"🎮 <b>PUBG UC</b>\n\nОтправьте заявку через Mini App. Автоматическая доставка требует официального провайдера.","numbers_info":"📞 <b>Виртуальные номера</b>\n\nУслуга станет доступна после подключения провайдера.","orders_info":"📦 Откройте раздел «Заказы» внутри Mini App, чтобы посмотреть заявки.","help_info":"👨‍💻 <b>Помощь</b>\n\n/start — главное меню\n/app — Mini App\n/balance — баланс\n/referral — реферальная ссылка\n/top — ТОП 10\n/orders — мои заказы\n/language — сменить язык\n/cancel — отменить действие\n\nОбратитесь к администратору, если нужна помощь.","back_info":"Главное меню:","choose":"Выберите раздел в меню.","mini":"🚀 <b>Открыть Mini App:</b>","app_missing":"Адрес Mini App не настроен. Обратитесь к администратору.","language_saved":"Язык сохранён!","subscribe":"🔒 <b>Подпишитесь на канал, чтобы пользоваться ботом.</b>\n\n📢 Вступите в @Cr7_Siu_Pubg, затем нажмите «Проверить подписку».","join":"📢 Подписаться на канал","check":"✅ Проверить подписку","sub_admin":"⚠️ Добавьте бота администратором канала @Cr7_Siu_Pubg.","sub_ok":"✅ Подписка подтверждена!","sub_no":"❌ Вы ещё не подписались на канал.","lang_prompt":"Выберите язык:"},
 "en":{"services":"🛍 Services","pubg":"🎮 PUBG UC","numbers":"📞 Virtual numbers","balance":"💳 Balance","orders":"📦 My orders","help":"👨‍💻 Help","app":"🚀 Open Mini App","my_balance":"💰 My balance","referral":"🤝 Referrals","promo":"🎟 Promo code","top":"🏆 TOP 10","back":"⬅️ Back","home":"🤖 <b>Welcome to iDonat Robot!</b>\n\nChoose a section.","balance_title":"💳 <b>Balance</b>\n\nChoose an option:","balance_info":"💰 Balance: <b>{balance:,} UZS</b>\n🤝 Invited users: <b>{referrals}</b>\n⭐ Game points: <b>{points}</b>","ref_info":"🤝 <b>Referral system</b>\n\nInvite friends! You receive 100 UZS in virtual balance for each new user.\n\n👥 Invited: <b>{count}</b>\n💰 Your referral link:\n<code>{link}</code>","promo_prompt":"🎟 Send your promo code. Use /cancel to cancel.","cancel":"Cancelled.","top_title":"🏆 <b>REFERRAL TOP 10</b>\n\n","no_results":"No results yet.","user":"User","top_note":"\n⭐ Game TOP 10 is tracked separately.","services_info":"🛍 <b>Services</b>\n\nSubmit requests through the Mini App. Automatic fulfillment is unavailable until a provider is connected.","pubg_info":"🎮 <b>PUBG UC</b>\n\nSubmit a UC request through the Mini App. Automatic delivery requires an official provider.","numbers_info":"📞 <b>Virtual numbers</b>\n\nThis service will be available after a provider is connected.","orders_info":"📦 Open the Orders section in the Mini App to view your requests.","help_info":"👨‍💻 <b>Help</b>\n\n/start — main menu\n/app — Mini App\n/balance — balance\n/referral — referral link\n/top — TOP 10\n/orders — my orders\n/language — change language\n/cancel — cancel action\n\nContact the administrator if you need help.","back_info":"Main menu:","choose":"Please choose a section from the menu.","mini":"🚀 <b>Open the Mini App:</b>","app_missing":"The Mini App URL is not configured. Contact the administrator.","language_saved":"Language saved!","subscribe":"🔒 <b>Subscribe to our channel to use the bot.</b>\n\n📢 Join @Cr7_Siu_Pubg, then tap “Check subscription”.","join":"📢 Subscribe to channel","check":"✅ Check subscription","sub_admin":"⚠️ Add the bot as an administrator of @Cr7_Siu_Pubg.","sub_ok":"✅ Subscription confirmed!","sub_no":"❌ You have not subscribed to the channel yet.","lang_prompt":"Choose your language:"}
}

def user_language(user_id):
    con=db(); cur=con.cursor()
    cur.execute("SELECT language FROM users WHERE user_id=?",(user_id,))
    row=cur.fetchone(); con.close()
    return row[0] if row and row[0] in BOT_TEXT else "uz"

def tr(user_id,key):
    return BOT_TEXT[user_language(user_id)].get(key,BOT_TEXT["uz"].get(key,key))

async def set_chat_commands(chat_id, language):
    from aiogram.types import BotCommand, BotCommandScopeChat
    commands={
      "uz":[("start","Botni ishga tushirish"),("app","Mini ilovani ochish"),("balance","Balansni ko‘rish"),("orders","Buyurtmalarim"),("referral","Referal havolasi"),("top","TOP 10"),("language","Tilni almashtirish"),("cancel","Amalni bekor qilish"),("help","Yordam")],
      "ru":[("start","Запустить бота"),("app","Открыть Mini App"),("balance","Мой баланс"),("orders","Мои заказы"),("referral","Реферальная ссылка"),("top","ТОП 10"),("language","Сменить язык"),("cancel","Отменить действие"),("help","Помощь")],
      "en":[("start","Start the bot"),("app","Open Mini App"),("balance","View balance"),("orders","My orders"),("referral","Referral link"),("top","TOP 10"),("language","Change language"),("cancel","Cancel current action"),("help","Help")]
    }
    try:
        await bot.set_my_commands(
            [BotCommand(command=c, description=d) for c, d in commands[language]],
            scope=BotCommandScopeChat(chat_id=chat_id)
        )
    except Exception as exc:
        print(f"Buyruqlar menyusini sozlash xatosi: {exc}")

def main_keyboard(user_id=None):
    t=BOT_TEXT[user_language(user_id) if user_id else "uz"]
    return ReplyKeyboardMarkup(keyboard=[
      *([[KeyboardButton(text=t["app"],web_app=WebAppInfo(url=WEBAPP_URL))]] if WEBAPP_URL.startswith("https://") else []),
      [KeyboardButton(text=t["services"])],[KeyboardButton(text=t["pubg"]),KeyboardButton(text=t["numbers"])],
      [KeyboardButton(text=t["balance"]),KeyboardButton(text=t["orders"])],[KeyboardButton(text=t["help"])]
    ],resize_keyboard=True)

async def send_home_screen(target, user_id):
    """Show the welcome message once, then keep the home menu available on every visit."""
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COALESCE(welcome_sent, 1) FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    should_welcome = bool(row and row[0] == 0)
    if should_welcome:
        await target.answer(tr(user_id, "home"), reply_markup=main_keyboard(user_id))
        cur.execute("UPDATE users SET welcome_sent=1 WHERE user_id=? AND welcome_sent=0", (user_id,))
        con.commit()
    else:
        await target.answer(tr(user_id, "choose"), reply_markup=main_keyboard(user_id))
    con.close()
    if WEBAPP_URL.startswith("https://"):
        await target.answer(
            tr(user_id, "mini"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=tr(user_id, "app"),
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]])
        )


def balance_keyboard(user_id=None):
    t=BOT_TEXT[user_language(user_id) if user_id else "uz"]
    return ReplyKeyboardMarkup(keyboard=[
      [KeyboardButton(text=t["my_balance"])],[KeyboardButton(text=t["referral"]),KeyboardButton(text=t["promo"])],
      [KeyboardButton(text=t["top"])],[KeyboardButton(text=t["back"])]
    ],resize_keyboard=True)


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
    cur.execute("SELECT user_id, language FROM users WHERE user_id=?", (user_id,))
    existing = cur.fetchone()
    if not existing:
        if inviter == user_id:
            inviter = 0
        cur.execute("SELECT 1 FROM users WHERE user_id=?", (inviter,))
        if not cur.fetchone():
            inviter = 0
        cur.execute(
            """INSERT INTO users
            (user_id, username, balance, referrals, points, inviter, language, referral_rewarded, welcome_sent)
            VALUES (?, ?, 0, 0, 0, ?, '', 0, 0)""",
            (user_id, username, inviter)
        )
        language = ""
    else:
        language = existing[1] or ""
        # Existing users should never be asked to choose a language again.
        # Older accounts with an empty language are safely assigned Uzbek.
        if not language:
            language = "uz"
            cur.execute("UPDATE users SET language=? WHERE user_id=?", (language, user_id))
        cur.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    con.commit()
    con.close()
    if not language:
        await send_language_prompt(message)
        return
    subscribed = await is_subscribed(user_id)
    if subscribed is not True:
        if subscribed is None:
            await message.answer(tr(user_id, "sub_admin"))
        else:
            await send_subscription_prompt(message, user_id)
        return
    await finish_referral(user_id)
    await set_chat_commands(message.chat.id, language)
    await send_home_screen(message, user_id)


@dp.callback_query(F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery):
    language = callback.data.split(":", 1)[1]
    if language not in ("uz", "ru", "en"):
        await callback.answer("Noto‘g‘ri til.", show_alert=True)
        return
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                (callback.from_user.id, callback.from_user.username or ""))
    cur.execute("UPDATE users SET language=? WHERE user_id=?", (language, callback.from_user.id))
    con.commit()
    con.close()
    await set_chat_commands(callback.message.chat.id, language)
    await callback.answer(tr(callback.from_user.id, "language_saved"))
    subscribed = await is_subscribed(callback.from_user.id)
    if subscribed is True:
        await finish_referral(callback.from_user.id)
        await send_home_screen(callback.message, callback.from_user.id)
    elif subscribed is False:
        await send_subscription_prompt(callback.message, callback.from_user.id)
    else:
        await callback.message.answer(tr(callback.from_user.id, "sub_admin"))


@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    subscribed = await is_subscribed(callback.from_user.id)
    if subscribed is True:
        await finish_referral(callback.from_user.id)
        await callback.answer(tr(callback.from_user.id, "sub_ok"))
        await send_home_screen(callback.message, callback.from_user.id)
    elif subscribed is False:
        await callback.answer(tr(callback.from_user.id, "sub_no"), show_alert=True)
    else:
        await callback.answer(tr(callback.from_user.id, "sub_admin"), show_alert=True)


@dp.message(Command("app"))
async def open_mini_app(message: Message):
    if not WEBAPP_URL.startswith("https://"):
        await message.answer(tr(message.from_user.id, "app_missing"))
        return
    await message.answer(
        "🚀 <b>Mini ilovani ochish:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=tr(message.from_user.id, "app"),
                web_app=WebAppInfo(url=WEBAPP_URL)
            )]
        ])
    )



@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(tr(message.from_user.id, "help_info"), reply_markup=main_keyboard(message.from_user.id))


@dp.message(Command("language"))
async def change_language_command(message: Message):
    await message.answer(tr(message.from_user.id, "lang_prompt"), reply_markup=language_keyboard())


@dp.message(Command("balance"))
async def balance_command(message: Message):
    user = get_user(message.from_user.id, message.from_user.username or "")
    if user:
        await message.answer(
            tr(message.from_user.id, "balance_info").format(balance=user[0], referrals=user[1], points=user[2]),
            reply_markup=balance_keyboard(message.from_user.id)
        )


@dp.message(Command("referral"))
async def referral_command(message: Message):
    await referral(message)


@dp.message(Command("top"))
async def top_command(message: Message):
    await top10(message)


@dp.message(F.text.in_([BOT_TEXT[l]["balance"] for l in BOT_TEXT]))
async def balance_menu(message: Message):
    await message.answer(
        tr(message.from_user.id, "balance_title"),
        reply_markup=balance_keyboard(message.from_user.id)
    )


@dp.message(F.text.in_([BOT_TEXT[l]["my_balance"] for l in BOT_TEXT]))
async def my_balance(message: Message):
    user = get_user(message.from_user.id, message.from_user.username or '')

    if user:
        await message.answer(
            tr(message.from_user.id, "balance_info").format(balance=user[0], referrals=user[1], points=user[2])
        )


@dp.message(F.text.in_([BOT_TEXT[l]["referral"] for l in BOT_TEXT]))
async def referral(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username or '')

    if not user:
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user_id}"

    await message.answer(
        tr(user_id, "ref_info").format(count=user[1], link=link)
    )


@dp.message(F.text.in_([BOT_TEXT[l]["promo"] for l in BOT_TEXT]))
async def promo_start(message: Message):
    promo_waiting.add(message.from_user.id)
    await message.answer(
        tr(message.from_user.id, "promo_prompt")
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    promo_waiting.discard(message.from_user.id)
    await message.answer(tr(message.from_user.id, "cancel"), reply_markup=balance_keyboard(message.from_user.id))


async def redeem_promo(message: Message):
    user_id = message.from_user.id
    code = message.text.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,40}", code):
        await message.answer("❌ Promokod 3–40 belgidan iborat bo‘lishi va faqat lotin harflari, raqam, _ yoki - ishlatishi kerak.")
        return

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

        credit_balance(cur, user_id, amount, "promo", f"{user_id}:{code}")

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

        if not re.fullmatch(r"[A-Z0-9_-]{3,40}", code):
            await message.answer("❌ Kod 3–40 belgidan iborat bo‘lsin: A–Z, 0–9, _ yoki -.")
            return
        if not (1 <= amount <= 100_000_000) or not (1 <= limit_count <= 1_000_000):
            await message.answer("❌ Miqdor 1–100 000 000 so‘m, limit esa 1–1 000 000 oralig‘ida bo‘lishi kerak.")
            return

        con = db()
        try:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO promo_codes (code, amount, limit_count) VALUES (?, ?, ?)",
                (code, amount, limit_count)
            )
            con.commit()
        finally:
            con.close()

        await message.answer("✅ Promokod yaratildi!")

    except ValueError:
        await message.answer("❌ Miqdor va limit butun son bo‘lishi kerak.")
    except sqlite3.IntegrityError:
        await message.answer("❌ Bu promokod avval yaratilgan.")


@dp.message(F.text.in_([BOT_TEXT[l]["top"] for l in BOT_TEXT]))
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

    text = tr(message.from_user.id, "top_title")

    if not rows:
        text += tr(message.from_user.id, "no_results")
    else:
        for i, row in enumerate(rows, 1):
            name = ("@" + row[0]) if row[0] else tr(message.from_user.id, "user")
            text += f"{i}. {name} — {row[1]} ta\n"

    text += tr(message.from_user.id, "top_note")
    await message.answer(text)


@dp.message(F.text.in_([BOT_TEXT[l]["services"] for l in BOT_TEXT]))
async def services(message: Message):
    await message.answer(
        tr(message.from_user.id, "services_info")
    )


@dp.message(F.text.in_([BOT_TEXT[l]["pubg"] for l in BOT_TEXT]))
async def pubg(message: Message):
    await message.answer(
        tr(message.from_user.id, "pubg_info")
    )


@dp.message(F.text.in_([BOT_TEXT[l]["numbers"] for l in BOT_TEXT]))
async def numbers(message: Message):
    await message.answer(
        tr(message.from_user.id, "numbers_info")
    )


@dp.message(F.text.in_([BOT_TEXT[l]["orders"] for l in BOT_TEXT]))
async def orders(message: Message):
    await show_user_orders(message)


@dp.message(Command("orders"))
async def orders_command(message: Message):
    await show_user_orders(message)


async def show_user_orders(message: Message):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, service, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
        (message.from_user.id,)
    )
    rows = cur.fetchall()
    con.close()
    if not rows:
        await message.answer(tr(message.from_user.id, "orders_info"))
        return
    labels = {"pending": "⏳ Kutilmoqda", "approved": "✅ Tasdiqlandi", "rejected": "❌ Rad etildi"}
    lines = ["📦 <b>Oxirgi buyurtmalaringiz</b>", ""]
    for order_id, service, status, created_at in rows:
        lines.append(
            f"#{order_id} · {html.escape(service)}\n"
            f"{labels.get(status, html.escape(status))} · {html.escape(created_at)}"
        )
    await message.answer("\n\n".join(lines))


def transition_order_status(order_id, status):
    """Move an order from pending exactly once; return (user_id, result)."""
    if status not in ("approved", "rejected"):
        raise ValueError("Noto‘g‘ri buyurtma holati")
    con = db()
    try:
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT user_id, status FROM orders WHERE id=?", (order_id,))
        row = cur.fetchone()
        if not row:
            con.rollback()
            return None, "not_found"
        user_id, current_status = row
        if current_status != "pending":
            con.rollback()
            return user_id, "already_processed"
        cur.execute(
            "UPDATE orders SET status=? WHERE id=? AND status='pending'",
            (status, order_id)
        )
        if cur.rowcount != 1:
            con.rollback()
            return user_id, "already_processed"
        con.commit()
        return user_id, "updated"
    except sqlite3.Error:
        con.rollback()
        raise
    finally:
        con.close()


@dp.message(Command("backupdb"))
async def admin_backup_database(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return
    backup_path = None
    source = None
    try:
        fd, backup_path = tempfile.mkstemp(prefix="idonat-backup-", suffix=".sqlite3")
        os.close(fd)
        source = sqlite3.connect(DB_NAME, timeout=20)
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
            source = None
        stamp = datetime.now(ZoneInfo("Asia/Tashkent")).strftime("%Y%m%d-%H%M%S")
        await message.answer_document(
            FSInputFile(backup_path, filename=f"idonat-backup-{stamp}.sqlite3"),
            caption="🛡️ iDonat ma’lumotlar bazasining zaxira nusxasi. Uni xavfsiz joyda saqlang."
        )
    except Exception as exc:
        print(f"Database backup failed: {exc}")
        await message.answer("❌ Zaxira nusxasini yaratib bo‘lmadi. Server jurnalini tekshiring.")
    finally:
        if source is not None:
            source.close()
        if backup_path and os.path.exists(backup_path):
            os.remove(backup_path)


@dp.message(Command("balancehistory"))
async def admin_balance_history(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /balancehistory USER_ID")
        return
    user_id = int(parts[1])
    con = db()
    try:
        rows = con.execute(
            "SELECT amount, balance_after, reason, reference, created_at "
            "FROM balance_ledger WHERE user_id=? ORDER BY id DESC LIMIT 15",
            (user_id,)
        ).fetchall()
        account = con.execute(
            "SELECT balance FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        con.close()
    if not account:
        await message.answer("Bunday foydalanuvchi topilmadi.")
        return
    lines = [
        f"💳 <b>Balans tarixi</b> · <code>{user_id}</code>",
        f"Joriy balans: <b>{account[0]:,} so‘m</b>",
        ""
    ]
    if not rows:
        lines.append("Hozircha yangi audit yozuvlari yo‘q.")
    else:
        for amount, balance_after, reason, reference, created_at in rows:
            lines.append(
                f"➕ {amount:,} so‘m · {html.escape(reason)}\n"
                f"Balans: {balance_after:,} · {html.escape(created_at)}\n"
                f"<code>{html.escape(reference)}</code>"
            )
    await message.answer("\n\n".join(lines))


@dp.message(Command("yupaycheck"))
async def admin_yupay_check(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return

    api_key = os.getenv("YUPAY_API_KEY", "").strip()
    if not api_key:
        await message.answer("❌ YUPAY_API_KEY topilmadi. Railway Variables bo‘limini tekshiring.")
        return

    timeout = ClientTimeout(total=15, connect=5)
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.get("https://api.yupay.uz/merchant/v1/me", headers=headers) as response:
                if response.status == 200:
                    await message.answer("✅ YuPay API kaliti ishlayapti. Hisob bilan xavfsiz ulanish tasdiqlandi.\n\nℹ️ Bu faqat tekshiruv: buyurtma berilmadi va mablag‘ yechilmadi.")
                elif response.status in (401, 403):
                    await message.answer("❌ YuPay kaliti qabul qilinmadi. Railway Variables’dagi YUPAY_API_KEY qiymatini tekshiring.")
                elif response.status == 429:
                    await message.answer("⏳ YuPay so‘rovlarni vaqtincha chekladi. Birozdan keyin qayta urinib ko‘ring.")
                else:
                    await message.answer(f"⚠️ YuPay tekshiruvi yakunlanmadi (HTTP {response.status}). Buyurtma berilmadi, mablag‘ yechilmadi.")
    except asyncio.TimeoutError:
        await message.answer("⏳ YuPay javobi kechikdi. Keyinroq qayta tekshiring.")
    except Exception as exc:
        print(f"YuPay xavfsiz tekshiruv xatosi: {type(exc).__name__}")
        await message.answer("⚠️ YuPay bilan ulanishda xatolik yuz berdi. Kalit chatga chiqarilmadi; keyinroq qayta urinib ko‘ring.")


@dp.message(Command("stats"))
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date().isoformat()
    con = db()
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users")
        users_count, total_balance = cur.fetchone()
        cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
        order_counts = dict(cur.fetchall())
        cur.execute("SELECT COUNT(*) FROM orders")
        orders_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM daily_bonus_claims WHERE claim_date=?", (today,))
        daily_claims = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(used_count), 0) FROM promo_codes")
        promo_uses = cur.fetchone()[0]
    finally:
        con.close()
    await message.answer(
        "📊 <b>iDonat — boshqaruv statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users_count:,}</b>\n"
        f"💰 Virtual balanslar yig‘indisi: <b>{total_balance:,} so‘m</b>\n"
        f"📦 Jami buyurtmalar: <b>{orders_count:,}</b>\n"
        f"⏳ Kutilmoqda: <b>{order_counts.get('pending', 0)}</b>\n"
        f"✅ Tasdiqlangan: <b>{order_counts.get('approved', 0)}</b>\n"
        f"❌ Rad etilgan: <b>{order_counts.get('rejected', 0)}</b>\n"
        f"🎁 Bugungi bonuslar: <b>{daily_claims}</b>\n"
        f"🎟 Promokod ishlatilishi: <b>{promo_uses}</b>"
    )


@dp.message(Command("pending"))
async def admin_pending_orders(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return
    con = db()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT id, user_id, service, details, created_at FROM orders "
            "WHERE status='pending' ORDER BY id DESC LIMIT 15"
        )
        rows = cur.fetchall()
    finally:
        con.close()
    if not rows:
        await message.answer("✅ Hozircha kutilayotgan buyurtma yo‘q.")
        return
    lines = ["⏳ <b>Kutilayotgan buyurtmalar</b>", ""]
    for order_id, user_id, service, details, created_at in rows:
        safe_details = html.escape(details[:180])
        if len(details) > 180:
            safe_details += "…"
        lines.append(
            f"<b>#{order_id}</b> · <code>{user_id}</code>\n"
            f"{html.escape(service)}\n{safe_details}\n"
            f"<i>{html.escape(created_at)}</i>\n"
            f"/orderstatus {order_id} approved  |  /orderstatus {order_id} rejected"
        )
    await message.answer("\n\n".join(lines))


@dp.message(Command("orderstatus"))
async def order_status_admin(message: Message):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("approved", "rejected"):
        await message.answer(
            "Buyurtma holatini o‘zgartirish:\n"
            "/orderstatus ID approved\n"
            "yoki\n/orderstatus ID rejected"
        )
        return
    order_id = int(parts[1])
    status = parts[2]
    try:
        user_id, result = transition_order_status(order_id, status)
    except sqlite3.Error as exc:
        print(f"Buyurtma holatini yangilash xatosi: {exc}")
        await message.answer("❌ Bazada xatolik. Keyinroq urinib ko‘ring.")
        return
    if result == "not_found":
        await message.answer("Bunday buyurtma topilmadi.")
        return
    if result == "already_processed":
        await message.answer("ℹ️ Bu buyurtma avval ko‘rib chiqilgan. Holat qayta o‘zgartirilmadi.")
        return
    label = "tasdiqlandi" if status == "approved" else "rad etildi"
    try:
        await bot.send_message(user_id, f"📦 <b>#{order_id}</b> buyurtmangiz {label}.")
    except Exception as exc:
        print(f"Buyurtma holati haqida foydalanuvchiga xabar yuborilmadi: {exc}")
    await message.answer(f"✅ Buyurtma #{order_id} holati yangilandi: {label}.")


@dp.message(F.text.in_([BOT_TEXT[l]["help"] for l in BOT_TEXT]))
async def help_user(message: Message):
    await message.answer(
        tr(message.from_user.id, "help_info")
    )


@dp.message(F.text.in_([BOT_TEXT[l]["back"] for l in BOT_TEXT]))
async def back(message: Message):
    await message.answer(
        tr(message.from_user.id, "back_info"),
        reply_markup=main_keyboard(message.from_user.id)
    )


@dp.message(F.text)
async def other_messages(message: Message):
    user_id = message.from_user.id

    if user_id in promo_waiting:
        promo_waiting.discard(user_id)
        await redeem_promo(message)
        return

    await message.answer(
        tr(message.from_user.id, "choose"),
        reply_markup=main_keyboard(message.from_user.id)
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
        now = int(time.time())
        # Allow a small clock skew, but reject expired or future-dated initData.
        if auth_date <= 0 or auth_date > now + 60 or now - auth_date > 86400:
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
        "SELECT balance, referrals, points, language FROM users WHERE user_id=?",
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
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date().isoformat()
    cur.execute(
        "SELECT 1 FROM daily_bonus_claims WHERE user_id=? AND claim_date=?",
        (user_id, today)
    )
    daily_claimed = cur.fetchone() is not None
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
        "level": (1 if (account[2] if account else 0) < 100 else 2 if (account[2] if account else 0) < 300 else 3 if (account[2] if account else 0) < 700 else 4 if (account[2] if account else 0) < 1500 else 5),
        "photo_url": telegram_user.get("photo_url", ""),
        "language": (account[3] if account and account[3] in ("uz", "ru", "en") else "uz"),
        "daily_claimed": daily_claimed,
        "referral_link": referral_link,
        "top10": leaders,
        "orders": []
    })


async def api_presence(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    telegram_user = validate_webapp_init_data(payload.get("initData", ""))
    if not telegram_user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)

    user_id = int(telegram_user["id"])
    now = time.time()
    con = db()
    cur = con.cursor()
    try:
        cur.execute(
            """INSERT INTO app_presence(user_id, last_seen) VALUES(?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen""",
            (user_id, now)
        )
        cur.execute("DELETE FROM app_presence WHERE last_seen < ?", (now - 86400,))
        cur.execute("SELECT COUNT(*) FROM app_presence WHERE last_seen >= ?", (now - 60,))
        online_count = cur.fetchone()[0]
        con.commit()
        return web.json_response({"ok": True, "online": online_count})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Faollik holatini yangilab bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_set_language(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    language = payload.get("language")
    if language not in ("uz", "ru", "en"):
        return web.json_response({"error": "Til noto‘g‘ri"}, status=400)
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (int(user["id"]), user.get("username", "") or "")
    )
    cur.execute(
        "UPDATE users SET language=? WHERE user_id=?",
        (language, int(user["id"]))
    )
    con.commit()
    con.close()
    return web.json_response({"ok": True, "language": language})


async def api_daily_claim(request):
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
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date().isoformat()
    con = db()
    cur = con.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, telegram_user.get("username", "") or "")
        )
        cur.execute(
            "INSERT INTO daily_bonus_claims (user_id, claim_date) VALUES (?, ?)",
            (user_id, today)
        )
        balance = credit_balance(cur, user_id, 50, "daily_bonus", f"{user_id}:{today}")
        cur.execute("SELECT points FROM users WHERE user_id=?", (user_id,))
        points = cur.fetchone()[0]
        con.commit()
        return web.json_response({
            "ok": True,
            "claimed": True,
            "bonus": 50,
            "points": points,
            "balance": balance
        })
    except sqlite3.IntegrityError:
        con.rollback()
        cur.execute("SELECT points, balance FROM users WHERE user_id=?", (user_id,))
        account = cur.fetchone() or (0, 0)
        return web.json_response({
            "ok": False,
            "claimed": True,
            "error": "Bugungi bonusni oldin olgansiz.",
            "points": account[0],
            "balance": account[1]
        }, status=409)
    finally:
        con.close()



async def api_promo(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    telegram_user = validate_webapp_init_data(payload.get("initData", ""))
    if not telegram_user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    code = str(payload.get("code", "")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,40}", code):
        return web.json_response({"error": "Promokod 3–40 belgidan iborat bo‘lishi kerak"}, status=400)
    user_id = int(telegram_user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT amount, limit_count, used_count FROM promo_codes WHERE code=?", (code,))
        promo = cur.fetchone()
        if not promo:
            con.rollback()
            return web.json_response({"error": "Promokod topilmadi"}, status=404)
        amount, limit_count, used_count = promo
        if used_count >= limit_count:
            con.rollback()
            return web.json_response({"error": "Promokod limiti tugagan"}, status=409)
        cur.execute("SELECT 1 FROM promo_redemptions WHERE user_id=? AND code=?", (user_id, code))
        if cur.fetchone():
            con.rollback()
            return web.json_response({"error": "Bu promokoddan avval foydalangansiz"}, status=409)
        cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                    (user_id, telegram_user.get("username", "") or ""))
        credit_balance(cur, user_id, amount, "promo", f"{user_id}:{code}")
        cur.execute("UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (code,))
        cur.execute("INSERT INTO promo_redemptions (user_id, code) VALUES (?, ?)", (user_id, code))
        cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        balance = cur.fetchone()[0]
        con.commit()
        return web.json_response({"ok": True, "amount": amount, "balance": balance})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Bazada xatolik yuz berdi"}, status=500)
    finally:
        con.close()


async def api_create_order(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "So‘rov formati noto‘g‘ri"}, status=400)
    telegram_user = validate_webapp_init_data(payload.get("initData", ""))
    if not telegram_user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)

    # Accept only services actually displayed in the Mini App.
    allowed_services = {
        "Telegram nakrutka", "Telegram Stars", "Telegram Premium",
        "PUBG UC", "Virtual raqamlar"
    }
    service = str(payload.get("service", "")).strip()
    details = str(payload.get("details", "")).strip()
    if service not in allowed_services or not details or len(details) > 500:
        return web.json_response(
            {"error": "Xizmatni tanlang va ma’lumotni 500 belgidan oshirmang"},
            status=400
        )

    user_id = int(telegram_user["id"])
    now = datetime.now(ZoneInfo("Asia/Tashkent"))
    created_at = now.isoformat(timespec="seconds")
    cutoff = (now - timedelta(seconds=60)).isoformat(timespec="seconds")
    con = db()
    cur = con.cursor()
    try:
        # Serialize the limit check and insert so parallel requests cannot bypass it.
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at>=?",
            (user_id, cutoff)
        )
        if cur.fetchone()[0] >= 5:
            con.rollback()
            return web.json_response(
                {"error": "Bir daqiqada ko‘pi bilan 5 ta buyurtma yuborish mumkin."},
                status=429
            )
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, telegram_user.get("username", "") or "")
        )
        cur.execute(
            "INSERT INTO orders (user_id, service, details, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user_id, service, details, created_at)
        )
        order_id = cur.lastrowid
        con.commit()
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Buyurtmani saqlab bo‘lmadi"}, status=500)
    finally:
        con.close()

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🆕 <b>Yangi buyurtma #{order_id}</b>\n"
                f"Foydalanuvchi: <code>{user_id}</code>\n"
                f"Xizmat: {html.escape(service)}\nMa’lumot: {html.escape(details)}"
            )
        except Exception as exc:
            # The order remains safely stored even if the notification cannot be delivered.
            print(f"Admin buyurtma xabari yuborilmadi: {exc}")
    return web.json_response({"ok": True, "order_id": order_id, "status": "pending"})


async def api_orders(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    telegram_user = validate_webapp_init_data(payload.get("initData", ""))
    if not telegram_user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, service, details, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 50",
        (int(telegram_user["id"]),)
    )
    rows = cur.fetchall()
    con.close()
    return web.json_response({"orders": [
        {"id": r[0], "service": r[1], "details": r[2], "status": r[3], "created_at": r[4]}
        for r in rows
    ]})


def xo_winner(board):
    for a, b, c in ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)):
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return "draw" if all(board) else ""


def rps_winner(a, b):
    if a == b:
        return 0
    if (a, b) in (("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")):
        return 1
    return 2


async def api_rps_queue(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    uid = int(user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "UPDATE rps_rooms SET status='finished', updated_at=? "
            "WHERE status IN ('waiting','playing') AND updated_at<?",
            (time.time(), time.time() - 86400)
        )
        cur.execute(
            "SELECT room_id, player_a, player_b, status FROM rps_rooms "
            "WHERE (player_a=? OR player_b=?) AND status IN ('waiting','playing') "
            "ORDER BY updated_at DESC LIMIT 1",
            (uid, uid)
        )
        own = cur.fetchone()
        requested_room = str(payload.get("room_id", "")).strip().upper()[:12]
        if own and not requested_room:
            room_id, pa, pb, status = own
        elif requested_room:
            cur.execute(
                "SELECT player_a, player_b, status FROM rps_rooms WHERE room_id=?",
                (requested_room,)
            )
            target = cur.fetchone()
            if not target or target[2] != "waiting" or target[1] is not None or target[0] == uid:
                con.rollback()
                return web.json_response({"error": "Xona kodi noto‘g‘ri yoki xona band"}, status=404)
            room_id, pa = requested_room, target[0]
            cur.execute(
                "UPDATE rps_rooms SET player_b=?, status='playing', updated_at=? "
                "WHERE room_id=? AND player_b IS NULL AND status='waiting'",
                (uid, time.time(), room_id)
            )
            pb, status = uid, "playing"
        else:
            room_id = uuid.uuid4().hex[:8].upper()
            cur.execute(
                "INSERT INTO rps_rooms (room_id, player_a, updated_at) VALUES (?, ?, ?)",
                (room_id, uid, time.time())
            )
            pa, pb, status = uid, None, "waiting"
        con.commit()
        return web.json_response({
            "ok": True, "room_id": room_id,
            "player": 1 if pa == uid else 2, "status": status
        })
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "O‘yin xonasiga ulanib bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_rps_state(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    room_id = str(payload.get("room_id", ""))[:20]
    uid = int(user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute(
            "SELECT player_a, player_b, choice_a, choice_b, round_no, score_a, score_b, "
            "resolved, status FROM rps_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
    finally:
        con.close()
    if not row or uid not in (row[0], row[1]):
        return web.json_response({"error": "O‘yin xonasi topilmadi"}, status=404)
    player = 1 if uid == row[0] else 2
    ready = row[1] is not None
    return web.json_response({
        "ok": True, "player": player, "status": row[8],
        "opponent_connected": ready, "round": row[4],
        "score_a": row[5], "score_b": row[6],
        "my_choice": row[2] if player == 1 else row[3],
        "opponent_choice": (row[3] if player == 1 else row[2]) if row[7] else "",
        "resolved": bool(row[7])
    })


async def api_rps_move(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    room_id = str(payload.get("room_id", ""))[:20]
    choice = str(payload.get("choice", ""))
    if choice not in ("rock", "paper", "scissors"):
        return web.json_response({"error": "Tanlov noto‘g‘ri"}, status=400)
    uid = int(user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT player_a, player_b, choice_a, choice_b, round_no, score_a, score_b, "
            "resolved, status FROM rps_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
        if not row or uid not in (row[0], row[1]):
            con.rollback()
            return web.json_response({"error": "O‘yin xonasi topilmadi"}, status=404)
        if row[1] is None or row[8] != "playing":
            con.rollback()
            return web.json_response({"error": "Raqib hali ulanmagan"}, status=409)
        player = 1 if uid == row[0] else 2
        ca, cb, rnd, sa, sb, resolved = row[2], row[3], row[4], row[5], row[6], row[7]
        if resolved:
            ca, cb, resolved = "", "", 0
            rnd += 1
        if (player == 1 and ca) or (player == 2 and cb):
            con.rollback()
            return web.json_response({"error": "Bu raundda tanlov yuborilgansiz"}, status=409)
        if player == 1:
            ca = choice
        else:
            cb = choice
        if ca and cb:
            result = rps_winner(ca, cb)
            if result == 1:
                sa += 1
            elif result == 2:
                sb += 1
            resolved = 1
        cur.execute(
            "UPDATE rps_rooms SET choice_a=?, choice_b=?, round_no=?, score_a=?, score_b=?, "
            "resolved=?, updated_at=? WHERE room_id=?",
            (ca, cb, rnd, sa, sb, resolved, time.time(), room_id)
        )
        con.commit()
        return web.json_response({"ok": True, "resolved": bool(resolved)})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Tanlovni saqlab bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_xo_queue(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    user_id = int(user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        # Expire abandoned rooms so old queue entries do not trap new players.
        cur.execute(
            "UPDATE xo_rooms SET status='finished', winner='draw', updated_at=? "
            "WHERE status IN ('waiting','playing') AND updated_at<?",
            (time.time(), time.time() - 86400)
        )
        cur.execute(
            "SELECT room_id, player_x, player_o, status FROM xo_rooms "
            "WHERE (player_x=? OR player_o=?) AND status IN ('waiting','playing') "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id, user_id)
        )
        own = cur.fetchone()
        if own:
            room_id, px, po, status = own
            symbol = "X" if px == user_id else "O"
        else:
            cur.execute(
                "SELECT room_id, player_x FROM xo_rooms "
                "WHERE status='waiting' AND player_o IS NULL AND player_x<>? "
                "ORDER BY updated_at ASC LIMIT 1",
                (user_id,)
            )
            waiting = cur.fetchone()
            if waiting:
                room_id, px = waiting
                cur.execute(
                    "UPDATE xo_rooms SET player_o=?, status='playing', updated_at=? "
                    "WHERE room_id=? AND player_o IS NULL AND status='waiting'",
                    (user_id, time.time(), room_id)
                )
                symbol = "O"
                status = "playing"
            else:
                room_id = uuid.uuid4().hex[:10].upper()
                cur.execute(
                    "INSERT INTO xo_rooms (room_id, player_x, updated_at) VALUES (?, ?, ?)",
                    (room_id, user_id, time.time())
                )
                symbol = "X"
                status = "waiting"
        con.commit()
        return web.json_response({"ok": True, "room_id": room_id, "symbol": symbol, "status": status})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "O‘yin xonasini yaratib bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_xo_state(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    room_id = str(payload.get("room_id", ""))[:20]
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT player_x, player_o, board, turn, status, winner FROM xo_rooms WHERE room_id=?",
        (room_id,)
    )
    row = cur.fetchone()
    con.close()
    if not row or int(user["id"]) not in (row[0], row[1]):
        return web.json_response({"error": "O‘yin xonasi topilmadi"}, status=404)
    symbol = "X" if int(user["id"]) == row[0] else "O"
    return web.json_response({
        "ok": True, "board": json.loads(row[2]), "turn": row[3],
        "status": row[4], "winner": row[5], "symbol": symbol,
        "opponent_connected": row[0] is not None and row[1] is not None
    })


async def api_xo_move(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    room_id = str(payload.get("room_id", ""))[:20]
    try:
        cell = int(payload.get("cell", -1))
    except (TypeError, ValueError):
        cell = -1
    if cell < 0 or cell > 8:
        return web.json_response({"error": "Katak noto‘g‘ri"}, status=400)
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT player_x, player_o, board, turn, status FROM xo_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
        if not row or int(user["id"]) not in (row[0], row[1]):
            con.rollback()
            return web.json_response({"error": "O‘yin xonasi topilmadi"}, status=404)
        symbol = "X" if int(user["id"]) == row[0] else "O"
        if row[4] != "playing" or row[1] is None:
            con.rollback()
            return web.json_response({"error": "Raqib hali ulanmagan"}, status=409)
        if row[3] != symbol:
            con.rollback()
            return web.json_response({"error": "Hozir sizning navbatingiz emas"}, status=409)
        board = json.loads(row[2])
        if board[cell]:
            con.rollback()
            return web.json_response({"error": "Bu katak band"}, status=409)
        board[cell] = symbol
        result = xo_winner(board)
        status = "finished" if result else "playing"
        winner = result if result else ""
        next_turn = "O" if symbol == "X" else "X"
        cur.execute(
            "UPDATE xo_rooms SET board=?, turn=?, status=?, winner=?, updated_at=? WHERE room_id=?",
            (json.dumps(board), next_turn, status, winner, time.time(), room_id)
        )
        con.commit()
        return web.json_response({"ok": True, "board": board, "status": status, "winner": winner})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Yurishni saqlab bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_chess_queue(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    uid = int(user["id"])
    requested_room = str(payload.get("room_id", "")).strip().upper()[:12]
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "UPDATE chess_rooms SET status='finished', winner='draw', updated_at=? "
            "WHERE status IN ('waiting','playing') AND updated_at<?",
            (time.time(), time.time() - 86400)
        )
        cur.execute(
            "SELECT room_id, player_white, player_black, status FROM chess_rooms "
            "WHERE (player_white=? OR player_black=?) AND status IN ('waiting','playing') "
            "ORDER BY updated_at DESC LIMIT 1", (uid, uid)
        )
        own = cur.fetchone()
        if own and not requested_room:
            room_id, white, black, status = own
        elif requested_room:
            cur.execute(
                "SELECT player_white, player_black, status FROM chess_rooms WHERE room_id=?",
                (requested_room,)
            )
            target = cur.fetchone()
            if not target or target[1] is not None or target[2] != "waiting" or target[0] == uid:
                con.rollback()
                return web.json_response({"error": "Xona kodi noto‘g‘ri yoki xona band"}, status=404)
            room_id, white = requested_room, target[0]
            cur.execute(
                "UPDATE chess_rooms SET player_black=?, status='playing', updated_at=? "
                "WHERE room_id=? AND player_black IS NULL AND status='waiting'",
                (uid, time.time(), room_id)
            )
            black, status = uid, "playing"
        else:
            room_id = uuid.uuid4().hex[:8].upper()
            initial_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            cur.execute(
                "INSERT INTO chess_rooms(room_id,player_white,fen,updated_at) VALUES(?,?,?,?)",
                (room_id, uid, initial_fen, time.time())
            )
            white, black, status = uid, None, "waiting"
        con.commit()
        return web.json_response({
            "ok": True, "room_id": room_id,
            "color": "white" if white == uid else "black", "status": status
        })
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Shaxmat xonasi yaratilmadi"}, status=500)
    finally:
        con.close()


async def api_chess_state(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    room_id = str(payload.get("room_id", ""))[:20]
    uid = int(user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute(
            "SELECT player_white,player_black,fen,moves,status,winner FROM chess_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
    finally:
        con.close()
    if not row or uid not in (row[0], row[1]):
        return web.json_response({"error": "Shaxmat xonasi topilmadi"}, status=404)
    try:
        board = chess.Board(row[2])
        moves = json.loads(row[3])
        outcome = board.outcome(claim_draw=True)
        status = row[4]
        winner = row[5]
        if outcome:
            status = "finished"
            winner = "white" if outcome.winner else "black" if outcome.winner is False else "draw"
        return web.json_response({
            "ok": True, "fen": board.fen(), "moves": moves, "status": status,
            "winner": winner, "color": "white" if uid == row[0] else "black",
            "turn": "white" if board.turn else "black"
        })
    except (ValueError, TypeError):
        return web.json_response({"error": "Shaxmat holati buzilgan"}, status=500)


async def api_chess_move(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    room_id = str(payload.get("room_id", ""))[:20]
    uci = str(payload.get("move", ""))[:5]
    uid = int(user["id"])
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT player_white,player_black,fen,moves,status FROM chess_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
        if not row or uid not in (row[0], row[1]):
            con.rollback()
            return web.json_response({"error": "Shaxmat xonasi topilmadi"}, status=404)
        white, black, fen, moves_json, status = row
        if black is None or status != "playing":
            con.rollback()
            return web.json_response({"error": "Raqib hali ulanmagan"}, status=409)
        if (uid == white) != (chess.Board(fen).turn == chess.WHITE):
            con.rollback()
            return web.json_response({"error": "Hozir sizning navbatingiz emas"}, status=409)
        board = chess.Board(fen)
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            con.rollback()
            return web.json_response({"error": "Yurish noto‘g‘ri"}, status=400)
        if move not in board.legal_moves:
            con.rollback()
            return web.json_response({"error": "Bu yurish shaxmat qoidalariga mos emas"}, status=409)
        san = board.san(move)
        board.push(move)
        moves = json.loads(moves_json)
        moves.append(san)
        outcome = board.outcome(claim_draw=True)
        next_status = "finished" if outcome else "playing"
        winner = ("white" if outcome.winner else "black" if outcome.winner is False else "draw") if outcome else ""
        cur.execute(
            "UPDATE chess_rooms SET fen=?,moves=?,status=?,winner=?,updated_at=? WHERE room_id=?",
            (board.fen(), json.dumps(moves), next_status, winner, time.time(), room_id)
        )
        con.commit()
        return web.json_response({"ok": True, "status": next_status, "winner": winner})
    except (sqlite3.Error, ValueError, TypeError):
        con.rollback()
        return web.json_response({"error": "Yurishni saqlab bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_checkers_queue(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
    uid = int(user["id"])
    initial = [""] * 64
    for r in range(3):
        for c in range(8):
            if (r+c)%2: initial[r*8+c] = "b"
    for r in range(5,8):
        for c in range(8):
            if (r+c)%2: initial[r*8+c] = "w"
    con=db(); cur=con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        # Close abandoned or incompatible rooms before matching a new opponent.
        cur.execute(
            "UPDATE checkers_rooms SET status='finished',winner='draw',updated_at=? "
            "WHERE status IN ('waiting','playing') AND (updated_at<? OR json_array_length(board)<>64)",
            (time.time(), time.time() - 86400)
        )
        cur.execute("SELECT room_id,player_x,player_o,status FROM checkers_rooms WHERE (player_x=? OR player_o=?) AND status IN ('waiting','playing') ORDER BY updated_at DESC LIMIT 1",(uid,uid))
        own=cur.fetchone()
        if own:
            room_id,px,po,status=own
            symbol="X" if px==uid else "O"
        else:
            cur.execute("SELECT room_id,player_x FROM checkers_rooms WHERE status='waiting' AND player_o IS NULL AND player_x<>? ORDER BY updated_at ASC LIMIT 1",(uid,))
            waiting=cur.fetchone()
            if waiting:
                room_id,px=waiting
                cur.execute("UPDATE checkers_rooms SET player_o=?,status='playing',updated_at=? WHERE room_id=? AND player_o IS NULL",(uid,time.time()))
                symbol="O"
            else:
                room_id=uuid.uuid4().hex[:10].upper()
                cur.execute("INSERT INTO checkers_rooms(room_id,player_x,board,updated_at) VALUES(?,?,?,?)",(room_id,uid,json.dumps(initial),time.time()))
                symbol="X"
        con.commit()
        return web.json_response({"ok":True,"room_id":room_id,"symbol":symbol})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error":"Xona yaratilmadi"},status=500)
    finally:
        con.close()


async def api_checkers_state(request):
    try: payload=await request.json()
    except Exception: return web.json_response({"error":"Noto‘g‘ri so‘rov"},status=400)
    user=validate_webapp_init_data(payload.get("initData",""))
    if not user: return web.json_response({"error":"Telegram orqali qayta oching"},status=401)
    room_id=str(payload.get("room_id",""))[:20]
    con=db(); cur=con.cursor()
    cur.execute("SELECT player_x,player_o,board,turn,status,winner FROM checkers_rooms WHERE room_id=?",(room_id,))
    row=cur.fetchone(); con.close()
    if not row or int(user["id"]) not in (row[0],row[1]):
        return web.json_response({"error":"O‘yin xonasi topilmadi"},status=404)
    return web.json_response({"ok":True,"board":json.loads(row[2]),"turn":row[3],"status":row[4],"winner":row[5],"symbol":"X" if int(user["id"])==row[0] else "O"})


def checkers_legal_boards(board, side):
    """Return every legal resulting board for one side under Russian 8x8 rules."""
    directions = ((-1, -1), (-1, 1), (1, -1), (1, 1))
    results = []

    def promote(piece, index):
        row = index // 8
        if piece == "w" and row == 0:
            return "W"
        if piece == "b" and row == 7:
            return "B"
        return piece

    def captures_from(start):
        initial_piece = board[start]

        def walk(position, state, current_piece, captured_count):
            row, col = divmod(position, 8)
            king = current_piece in ("W", "B")
            found = False

            for dr, dc in directions:
                rr, cc = row + dr, col + dc
                if king:
                    while 0 <= rr < 8 and 0 <= cc < 8 and not state[rr * 8 + cc]:
                        rr += dr
                        cc += dc
                    if not (0 <= rr < 8 and 0 <= cc < 8):
                        continue
                    enemy_index = rr * 8 + cc
                    enemy = state[enemy_index]
                    if not enemy or enemy.lower() == side:
                        continue
                    lr, lc = rr + dr, cc + dc
                    while 0 <= lr < 8 and 0 <= lc < 8 and not state[lr * 8 + lc]:
                        found = True
                        target = lr * 8 + lc
                        next_state = state.copy()
                        next_state[position] = ""
                        next_state[enemy_index] = ""
                        next_state[target] = current_piece
                        walk(target, next_state, current_piece, captured_count + 1)
                        lr += dr
                        lc += dc
                else:
                    mr, mc = row + dr, col + dc
                    tr, tc = row + 2 * dr, col + 2 * dc
                    if not (0 <= mr < 8 and 0 <= mc < 8 and
                            0 <= tr < 8 and 0 <= tc < 8):
                        continue
                    enemy_index = mr * 8 + mc
                    target = tr * 8 + tc
                    enemy = state[enemy_index]
                    if not enemy or enemy.lower() == side or state[target]:
                        continue
                    found = True
                    next_state = state.copy()
                    next_state[position] = ""
                    next_state[enemy_index] = ""
                    next_piece = promote(current_piece, target)
                    next_state[target] = next_piece
                    walk(target, next_state, next_piece, captured_count + 1)

            if not found and captured_count:
                results.append(state)

        walk(start, board.copy(), initial_piece, 0)

    for index, piece in enumerate(board):
        if piece and piece.lower() == side:
            captures_from(index)
    if results:
        return results

    for index, piece in enumerate(board):
        if not piece or piece.lower() != side:
            continue
        row, col = divmod(index, 8)
        king = piece in ("W", "B")
        move_dirs = directions if king else (
            ((-1, -1), (-1, 1)) if piece == "w" else ((1, -1), (1, 1))
        )
        for dr, dc in move_dirs:
            rr, cc = row + dr, col + dc
            while 0 <= rr < 8 and 0 <= cc < 8 and not board[rr * 8 + cc]:
                target = rr * 8 + cc
                next_state = board.copy()
                next_state[index] = ""
                next_state[target] = promote(piece, target)
                results.append(next_state)
                if not king:
                    break
                rr += dr
                cc += dc
    return results


async def api_checkers_resign(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)

    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)

    room_id = str(payload.get("room_id", ""))[:20]
    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT player_x, player_o, status FROM checkers_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
        if not row or int(user["id"]) not in (row[0], row[1]):
            con.rollback()
            return web.json_response({"error": "O‘yin xonasi topilmadi"}, status=404)
        player_x, player_o, status = row
        if status != "playing" or player_o is None:
            con.rollback()
            return web.json_response({"error": "Bu o‘yinda taslim bo‘lish mumkin emas"}, status=409)
        winner = "O" if int(user["id"]) == player_x else "X"
        cur.execute(
            "UPDATE checkers_rooms SET status='finished', winner=?, updated_at=? "
            "WHERE room_id=? AND status='playing'",
            (winner, time.time(), room_id)
        )
        if cur.rowcount != 1:
            con.rollback()
            return web.json_response({"error": "O‘yin holati o‘zgargan. Qayta tekshiring."}, status=409)
        con.commit()
        return web.json_response({"ok": True, "status": "finished", "winner": winner})
    except sqlite3.Error:
        con.rollback()
        return web.json_response({"error": "Taslim bo‘lishni saqlab bo‘lmadi"}, status=500)
    finally:
        con.close()


async def api_checkers_move(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)

    user = validate_webapp_init_data(payload.get("initData", ""))
    if not user:
        return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)

    room_id = str(payload.get("room_id", ""))[:20]
    submitted_board = payload.get("board")
    if (not isinstance(submitted_board, list) or len(submitted_board) != 64 or
            any(piece not in ("", "w", "b", "W", "B") for piece in submitted_board)):
        return web.json_response({"error": "Yurish ma’lumotlari noto‘g‘ri"}, status=400)

    con = db()
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT player_x, player_o, board, turn, status "
            "FROM checkers_rooms WHERE room_id=?",
            (room_id,)
        )
        row = cur.fetchone()
        if not row or int(user["id"]) not in (row[0], row[1]):
            con.rollback()
            return web.json_response({"error": "Xona topilmadi"}, status=404)

        player_x, player_o, saved_json, turn, room_status = row
        symbol = "X" if int(user["id"]) == player_x else "O"
        if player_o is None or room_status != "playing" or turn != symbol:
            con.rollback()
            return web.json_response({"error": "Hozir sizning navbatingiz emas"}, status=409)

        current_board = json.loads(saved_json)
        if len(current_board) != 64:
            con.rollback()
            return web.json_response({"error": "O‘yin taxtasi noto‘g‘ri"}, status=409)

        side = "w" if symbol == "X" else "b"
        legal_boards = checkers_legal_boards(current_board, side)
        if not any(candidate == submitted_board for candidate in legal_boards):
            con.rollback()
            return web.json_response({"error": "Bu qoida bo‘yicha mumkin bo‘lmagan yurish"}, status=409)

        next_side = "b" if side == "w" else "w"
        next_symbol = "O" if symbol == "X" else "X"
        opponent_has_piece = any(piece and piece.lower() == next_side for piece in submitted_board)
        opponent_can_move = opponent_has_piece and bool(checkers_legal_boards(submitted_board, next_side))
        next_status = "playing" if opponent_can_move else "finished"
        winner = "" if opponent_can_move else symbol

        cur.execute(
            "UPDATE checkers_rooms SET board=?, turn=?, status=?, winner=?, updated_at=? "
            "WHERE room_id=?",
            (json.dumps(submitted_board), next_symbol, next_status, winner, time.time(), room_id)
        )
        con.commit()
        return web.json_response({
            "ok": True, "turn": next_symbol, "status": next_status, "winner": winner
        })
    except (sqlite3.Error, ValueError, TypeError):
        con.rollback()
        return web.json_response({"error": "Yurishni saqlab bo‘lmadi"}, status=500)
    finally:
        con.close()


@web.middleware
async def require_channel_subscription(request, handler):
    if request.path.startswith("/api/"):
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Noto‘g‘ri so‘rov"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "So‘rov JSON obyekt bo‘lishi kerak"}, status=400)
        telegram_user = validate_webapp_init_data(payload.get("initData", ""))
        if not telegram_user:
            return web.json_response({"error": "Telegram orqali qayta oching"}, status=401)
        subscribed = await is_subscribed(int(telegram_user["id"]))
        if subscribed is None:
            return web.json_response({"error": "Botni @Cr7_Siu_Pubg kanaliga administrator qilib qo‘shing"}, status=503)
        if not subscribed:
            return web.json_response({"error": "Kanalga obuna bo‘ling: @Cr7_Siu_Pubg"}, status=403)
    return await handler(request)


async def mini_app_home(request):
    page = Path(__file__).parent / "webapp" / "index.html"
    if not page.exists():
        return web.Response(text="Mini App fayli topilmadi", status=404)
    return web.FileResponse(page)


async def health_check(request):
    """Report ready only when the SQLite database can actually be opened."""
    try:
        with db() as con:
            result = con.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            return web.json_response(
                {"ok": False, "app": "iDonat Robot", "database": "error"},
                status=503
            )
        return web.json_response(
            {"ok": True, "app": "iDonat Robot", "database": "ok"}
        )
    except (sqlite3.Error, OSError) as exc:
        print(f"Health check database error: {exc}")
        return web.json_response(
            {"ok": False, "app": "iDonat Robot", "database": "unavailable"},
            status=503
        )


async def start_web_server():
    app = web.Application(middlewares=[require_channel_subscription])
    app.router.add_get("/", mini_app_home)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/presence", api_presence)
    app.router.add_post("/api/language", api_set_language)
    app.router.add_post("/api/daily-claim", api_daily_claim)
    app.router.add_post("/api/promo", api_promo)
    app.router.add_post("/api/orders/create", api_create_order)
    app.router.add_post("/api/orders", api_orders)
    app.router.add_post("/api/rps/queue", api_rps_queue)
    app.router.add_post("/api/rps/state", api_rps_state)
    app.router.add_post("/api/rps/move", api_rps_move)
    app.router.add_post("/api/xo/queue", api_xo_queue)
    app.router.add_post("/api/xo/state", api_xo_state)
    app.router.add_post("/api/xo/move", api_xo_move)
    app.router.add_post("/api/chess/queue", api_chess_queue)
    app.router.add_post("/api/chess/state", api_chess_state)
    app.router.add_post("/api/chess/move", api_chess_move)
    app.router.add_post("/api/checkers/queue", api_checkers_queue)
    app.router.add_post("/api/checkers/state", api_checkers_state)
    app.router.add_post("/api/checkers/move", api_checkers_move)
    app.router.add_post("/api/checkers/resign", api_checkers_resign)
    app.router.add_get("/health", health_check)
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
