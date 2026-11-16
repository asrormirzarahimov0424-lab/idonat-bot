import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Uni hostingdagi Environment Variables bo'limiga kiriting.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Xizmatlar"), KeyboardButton(text="🎮 PUBG UC")],
        [KeyboardButton(text="📞 Virtual raqamlar"), KeyboardButton(text="💳 Balans")],
        [KeyboardButton(text="📦 Buyurtmalarim"), KeyboardButton(text="👨‍💻 Yordam")],
    ],
    resize_keyboard=True
)

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🤖 iDonat Robotga xush kelibsiz!\n\nKerakli bo‘limni tanlang.",
        reply_markup=keyboard
    )

@dp.message(F.text == "🛍 Xizmatlar")
async def services(message: Message):
    await message.answer(
        "🛍 Xizmatlar bo‘limi\n\n"
        "Bu demo versiya. Faqat platforma qoidalariga mos, haqiqiy reklama va marketing xizmatlari "
        "taklif qilinadi. Buyurtma va to‘lovlar provayder ulangandan keyin yoqiladi."
    )

@dp.message(F.text == "🎮 PUBG UC")
async def pubg(message: Message):
    await message.answer(
        "🎮 PUBG Mobile UC\n\n"
        "UC avtomatik yetkazilishi uchun rasmiy yoki vakolatli yetkazib beruvchi API ulanishi kerak. "
        "Hozircha to‘lov yoki Player ID so‘ralmaydi."
    )

@dp.message(F.text == "📞 Virtual raqamlar")
async def numbers(message: Message):
    await message.answer(
        "📞 Virtual raqamlar\n\n"
        "Faqat qonuniy va ishonchli aloqa provayderlari xizmatlari qo‘shiladi. "
        "Spam yoki platforma cheklovlarini chetlab o‘tish uchun xizmat ko‘rsatilmaydi."
    )

@dp.message(F.text == "💳 Balans")
async def balance(message: Message):
    await message.answer(
        "💳 Balansingiz: 0 so‘m\n\n"
        "To‘lov tizimi ulanmaguncha balans to‘ldirish vaqtincha o‘chirilgan."
    )

@dp.message(F.text == "📦 Buyurtmalarim")
async def orders(message: Message):
    await message.answer("📦 Hozircha buyurtmalaringiz yo‘q.")

@dp.message(F.text == "👨‍💻 Yordam")
async def help_message(message: Message):
    await message.answer("👨‍💻 Yordam uchun bot administratori bilan bog‘laning.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
