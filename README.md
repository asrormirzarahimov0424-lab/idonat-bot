# iDonat Robot 🤖

Telegram bot va Telegram Mini App (Python, aiogram, aiohttp, SQLite).

## Ishga tushirish

1. Python 3.11 yoki yangiroq versiya.
2. `pip install -r requirements.txt`
3. Quyidagi environment variable'larni sozlang:
   - `BOT_TOKEN` — Telegram bot tokeni.
   - `WEBAPP_URL` — Mini App uchun HTTPS manzil.
   - `ADMIN_ID` — administratorning Telegram ID raqami (buyurtma xabarlari va admin buyruqlari uchun).
   - `DB_PATH` — ixtiyoriy SQLite fayl yo‘li; masalan, Railway persistent volume ulangan bo‘lsa `/data/idonat_robot.db`.
4. `python main.py`

## Hozir ishlaydigan qismlar

- Telegram bot menyusi va Mini App ochish tugmasi.
- Telegram Mini App `initData` imzosini tekshirish.
- Kunlik 50 so‘m bonus (bir foydalanuvchiga kuniga bir marta).
- Referal havolasi va referal TOP 10.
- Promokod yaratish va bir foydalanuvchi uchun bir martalik ishlatish.
- Buyurtma so‘rovini bazaga yozish, foydalanuvchiga ko‘rsatish va admin orqali holatini o‘zgartirish.
- X-O: kompyuterga qarshi 5 daraja va onlayn o‘yin.
- Shashka: 8×8 rus qoidalari, kompyuterga qarshi 5 daraja va onlayn o‘yin.

## Hali ulanmagan qismlar

- Balansni haqiqiy pul bilan to‘ldirish va to‘lov provayderi.
- PUBG UC, Telegram Stars/Premium, virtual raqamlar va boshqa xizmatlarni avtomatik yetkazib berish.
- iDonat AI, Premium obuna va mukofotli yutuqlar tizimi.

Buyurtma yuborish hozircha faqat so‘rov yaratadi; provayder va to‘lov tizimi ulanmaguncha foydalanuvchidan pul yechilmaydi. PUBG UC faqat rasmiy yoki vakolatli yetkazib beruvchi orqali avtomatik berilishi kerak.

## Xavfsizlik va saqlash

- `BOT_TOKEN` ni GitHub'ga yoki chatga joylamang.
- Railway'da SQLite ma'lumotlari saqlanib qolishi uchun persistent volume ulang va `DB_PATH` ni volume ichidagi faylga sozlang. Volume bo‘lmasa, qayta deploy yoki restartdan keyin lokal DB yo‘qolishi mumkin.
- Real to‘lovni provayder sozlanib, sinovdan o‘tmaguncha qabul qilmang.
