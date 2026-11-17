import os
import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "idonat_robot.db"

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                referrals INTEGER DEFAULT 0,
                referred_by INTEGER
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                amount INTEGER,
                max_uses INTEGER,
                uses INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                user_id INTEGER,
                code TEXT,
                PRIMARY KEY(user_id, code)
            )
        """)

init_db()
keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Xizmatlar"), KeyboardButton(text="🎮 PUBG UC")],
        [KeyboardButton(text="📞 Virtual raqamlar"), KeyboardButton(text="💳 Balans")],
        [KeyboardButton(text="📦 Buyurtmalarim"), KeyboardButton(text="👨‍💻 Yordam")],
    ],
    resize_keyboard=True
)

balance_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Mening balansim")],
        [KeyboardButton(text="🤝 Referal"), KeyboardButton(text="🎟 Promokod")],
        [KeyboardButton(text="🏆 TOP 10")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ],
    resize_keyboard=True
)

def get_user(user_id):
    with sqlite3.connect(DB_PATH) as db:
        return db.execute(
            "SELECT balance, referrals FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    with sqlite3.connect(DB_PATH) as db:
        exists = db.execute(
            "SELECT user_id FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        if not exists:
            db.execute("INSERT INTO users(user_id) VALUES(?)", (user_id,))
            if len(args) > 1 and args[1].startswith("ref_"):
                try:
                    inviter = int(args[1][4:])
                    if inviter != user_id:
                        inviter_exists = db.execute(
                            "SELECT user_id FROM users WHERE user_id=?",
                            (inviter,)
                        ).fetchone()
                        if inviter_exists:
                            db.execute(
                                "UPDATE users SET balance=balance+100, referrals=referrals+1 WHERE user_id=?",
                                (inviter,)
                            )
                except ValueError:
                    pass

    await message.answer(
        "🤖 iDonat Robotga xush kelibsiz!\n\nKerakli bo‘limni tanlang.",
        reply_markup=keyboard
    )
    @dp.message(F.text == "🛍 Xizmatlar")
async def services(message: Message):
    await message.answer(
        "🛍 Xizmatlar bo‘limi\n\n"
        "Bu demo versiya. Xizmatlar provayder ulangandan keyin yoqiladi."
    )

@dp.message(F.text == "🎮 PUBG UC")
async def pubg(message: Message):
    await message.answer(
        "🎮 PUBG Mobile UC\n\n"
        "UC yetkazib berish uchun rasmiy provayder API ulanishi kerak."
    )

@dp.message(F.text == "📞 Virtual raqamlar")
async def numbers(message: Message):
    await message.answer(
        "📞 Virtual raqamlar\n\n"
        "Faqat qonuniy aloqa xizmatlari qo‘shiladi."
    )

@dp.message(F.text == "💳 Balans")
async def balance(message: Message):
    user = get_user(message.from_user.id)
    amount = user[0] if user else 0
    await message.answer(
        f"💳 Balansingiz: {amount} so‘m\n\nBo‘limni tanlang.",
        reply_markup=balance_keyboard
    )

@dp.message(F.text == "💰 Mening balansim")
async def my_balance(message: Message):
    user = get_user(message.from_user.id)
    amount = user[0] if user else 0
    await message.answer(f"💰 Sizning balansingiz: {amount} so‘m")
    @dp.message(F.text == "🤝 Referal")
async def referral(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    referrals = user[1] if user else 0
    link = f"https://t.me/iDonat_Robot?start=ref_{user_id}"

    await message.answer(
        f"🤝 Referal tizimi\n\n"
        f"🎁 Har bir yangi taklif qilingan foydalanuvchi uchun 100 so‘m.\n"
        f"👥 Takliflaringiz: {referrals} ta\n\n"
        f"🔗 Sizning havolangiz:\n{link}"
    )

@dp.message(F.text == "🏆 TOP 10")
async def top10(message: Message):
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(
            "SELECT user_id, referrals FROM users "
            "WHERE referrals > 0 ORDER BY referrals DESC LIMIT 10"
        ).fetchall()

    if not rows:
        await message.answer("🏆 Hozircha reytingda foydalanuvchilar yo‘q.")
        return

    result = "🏆 TOP 10 REFERAL\n\n"
    for i, row in enumerate(rows, 1):
        result += f"{i}. ID: {row[0]} — {row[1]} ta\n"

    await message.answer(result)
    @dp.message(F.text == "🎟 Promokod")
async def promo_start(message: Message):
    await message.answer("🎟 Promokodingizni yuboring:")

@dp.message(F.text == "⬅️ Orqaga")
async def back(message: Message):
    await message.answer("Asosiy menyu:", reply_markup=keyboard)

@dp.message(F.text == "📦 Buyurtmalarim")
async def orders(message: Message):
    await message.answer("📦 Hozircha buyurtmalaringiz yo‘q.")

@dp.message(F.text == "👨‍💻 Yordam")
async def help_message(message: Message):
    await message.answer("👨‍💻 Yordam uchun bot administratori bilan bog‘laning.")
    @dp.message(F.text.startswith("/addpromo"))
async def add_promo(message: Message):
    if ADMIN_ID == 0 or message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Ruxsat yo‘q.")
        return

    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Format: /addpromo KOD MIQDOR LIMIT")
        return

    try:
        code = parts[1].upper()
        amount = int(parts[2])
        limit = int(parts[3])

        if amount <= 0 or limit <= 0:
            raise ValueError

        with sqlite3.connect(DB_PATH) as db:
            db.execute(
                "INSERT INTO promo_codes(code, amount, max_uses) VALUES(?,?,?)",
                (code, amount, limit)
            )
        await message.answer("✅ Promokod yaratildi!")
    except sqlite3.IntegrityError:
        await message.answer("Bu promokod avval yaratilgan.")
    except ValueError:
        await message.answer("Miqdor va limit musbat son bo‘lishi kerak.")

@dp.message()
async def use_promo(message: Message):
    code = message.text.strip().upper()
    user_id = message.from_user.id

    with sqlite3.connect(DB_PATH) as db:
        promo = db.execute(
            "SELECT amount, max_uses, uses FROM promo_codes WHERE code=?",
            (code,)
        ).fetchone()

        if not promo:
            return

        amount, max_uses, uses = promo

        if uses >= max_uses:
            await message.answer("⛔ Bu promokod tugagan.")
            return

        used = db.execute(
            "SELECT 1 FROM promo_redemptions WHERE user_id=? AND code=?",
            (user_id, code)
        ).fetchone()

        if used:
            await message.answer("Siz bu promokoddan foydalangansiz.")
            return

        db.execute(
            "INSERT INTO promo_redemptions(user_id, code) VALUES(?,?)",
            (user_id, code)
        )
        db.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (amount, user_id)
        )
        db.execute(
            "UPDATE promo_codes SET uses=uses+1 WHERE code=?", (code,)
        )

    await message.answer(f"✅ Promokod qabul qilindi! +{amount} so‘m")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
 
