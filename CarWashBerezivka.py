import asyncio
import aiosqlite
import os
import re
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path="D:/web/python/main.env")
API_TOKEN = os.getenv("API_TOKEN")
print("API_TOKEN:", API_TOKEN)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

MAIN_ADMIN_ID = 863294823

user_booking = {}

# --- Ініціалізація БД ---
async def init_db():
    async with aiosqlite.connect("carwash.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                duration INTEGER -- зберігаємо в хвилинах
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                phone_number TEXT,
                program_id INTEGER,
                car_number TEXT,
                booking_datetime TEXT,
                FOREIGN KEY(program_id) REFERENCES programs(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()

# --- Допоміжні функції ---
async def get_programs():
    async with aiosqlite.connect("carwash.db") as db:
        async with db.execute("SELECT id, name, duration FROM programs") as cursor:
            return await cursor.fetchall()

async def is_admin(user_id: int) -> bool:
    if user_id == MAIN_ADMIN_ID:
        return True
    async with aiosqlite.connect("carwash.db") as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)) as cursor:
            return bool(await cursor.fetchone())

async def get_available_hours(program_id, booking_date):
    async with aiosqlite.connect("carwash.db") as db:
        cursor = await db.execute("SELECT duration FROM programs WHERE id=?", (program_id,))
        row = await cursor.fetchone()
        if not row:
            return []
        duration = row[0]

        all_hours = [datetime.combine(booking_date, datetime.min.time()) + timedelta(hours=h) for h in range(9, 19)]

        cursor = await db.execute("""
            SELECT booking_datetime, p.duration
            FROM bookings b
            LEFT JOIN programs p ON b.program_id = p.id
            WHERE DATE(booking_datetime)=?
        """, (booking_date.isoformat(),))   # тут isoformat() дає YYYY-MM-DD

        booked = await cursor.fetchall()
        available = []
        for start in all_hours:
            end = start + timedelta(minutes=duration)
            conflict = False
            for b_dt, b_dur in booked:
                b_start = datetime.strptime(b_dt, "%Y-%m-%d %H:%M:%S")  # виправлено
                b_end = b_start + timedelta(minutes=b_dur)
                if not (end <= b_start or start >= b_end):
                    conflict = True
                    break
            if not conflict:
                available.append(start.strftime("%H:%M"))
        return available


# Генерація кнопок для вибору дат
def generate_date_buttons(days_ahead=7):
    today = datetime.today().date()
    buttons = [[KeyboardButton(text=(today + timedelta(days=i)).strftime("%d.%m.%Y"))] for i in range(days_ahead)]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- Команди ---
@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привіт! Я бот для запису на мийку. Використай /help для списку команд.")

@router.message(Command("help"))
async def help_command(message: types.Message):
    base_text = (
        "📌 Доступні команди:\n\n"
        "/start - почати спілкування\n"
        "/help - список команд\n"
        "/programs - програми мийки\n"
        "/book - записати авто\n"
    )
    admin_text = ""
    if await is_admin(message.from_user.id):
        admin_text = (
            "\n🛠 Адмін-команди:\n"
            "/show_booking [дата|user_id|номер авто] - показати бронювання\n"
            "/edit <ID> <дата> <година> - змінити бронювання\n"
            "/delete <ID> - видалити бронювання\n"
            "/add_program <назва> <год:хв:сек>\n"
            "/add_admin <user_id>\n"
            "/del_admin <user_id>\n"
            "/admins - список адмінів\n"
        )
    await message.answer(base_text + admin_text)

@router.message(Command("programs"))
async def show_programs(message: types.Message):
    programs = await get_programs()
    if not programs:
        await message.answer("Програми ще не додані.")
        return
    text = "Програми мийки:\n\n"
    for p in programs:
        text += f"{p[0]} - {p[1]} ({p[2]} хв)\n"
    await message.answer(text)

@router.message(Command("add_admin"))
async def add_admin(message: types.Message):
    if message.from_user.id != MAIN_ADMIN_ID:
        await message.answer("❌ Лише головний адмін може додавати адмінів")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("⚠ Використання: /add_admin <user_id>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ user_id має бути числом")
        return
    async with aiosqlite.connect("carwash.db") as db:
        try:
            await db.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
            await db.commit()
            await message.answer(f"✅ {user_id} доданий у адміни")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Вже є адміном")

@router.message(Command("del_admin"))
async def del_admin(message: types.Message):
    if message.from_user.id != MAIN_ADMIN_ID:
        await message.answer("❌ Лише головний адмін може видаляти адмінів")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("⚠ Використання: /del_admin <user_id>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ user_id має бути числом")
        return
    async with aiosqlite.connect("carwash.db") as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (target_id,))
        await db.commit()
    await message.answer(f"🗑 {target_id} видалений з адмінів")

@router.message(Command("admins"))
async def list_admins(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Немає прав")
        return

    async with aiosqlite.connect("carwash.db") as db:
        rows = await db.execute_fetchall("SELECT user_id FROM admins")

    # Додаємо головного адміна в список
    admins_ids = [MAIN_ADMIN_ID] + [r[0] for r in rows]

    text = "📋 Адміни:\n"
    for admin_id in admins_ids:
        try:
            user = await bot.get_chat(admin_id)
            username = f"@{user.username}" if user.username else "Не вказано"
        except Exception:
            username = "Не вказано"
        text += f"{admin_id} | {username}\n"

    await message.answer(text)

@router.message(Command("show_booking"))
async def show_booking(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Немає прав")
        return

    args = message.text.split(maxsplit=1)

    async with aiosqlite.connect("carwash.db") as db:
        rows = []
        if len(args) == 1:
            # 🔹 Без аргументів → всі бронювання
            cursor = await db.execute("""
                SELECT b.id, b.user_id, b.username, b.phone_number, p.name, b.car_number, b.booking_datetime
                FROM bookings b
                LEFT JOIN programs p ON b.program_id = p.id
                ORDER BY booking_datetime
            """)
            rows = await cursor.fetchall()
        else:
            query = args[1].strip()
            # 🔹 Якщо дата
            try:
                date = datetime.strptime(query, "%d.%m.%Y").date()
                cursor = await db.execute("""
                    SELECT b.id, b.user_id, b.username, b.phone_number, p.name, b.car_number, b.booking_datetime
                    FROM bookings b
                    LEFT JOIN programs p ON b.program_id = p.id
                    WHERE DATE(booking_datetime)=?
                    ORDER BY booking_datetime
                """, (date.isoformat(),))
                rows = await cursor.fetchall()
            except ValueError:
                # 🔹 Якщо user_id
                if query.isdigit():
                    cursor = await db.execute("""
                        SELECT b.id, b.user_id, b.username, b.phone_number, p.name, b.car_number, b.booking_datetime
                        FROM bookings b
                        LEFT JOIN programs p ON b.program_id = p.id
                        WHERE b.user_id=?
                        ORDER BY booking_datetime
                    """, (int(query),))
                    rows = await cursor.fetchall()
                else:
                    # 🔹 Якщо номер авто
                    cursor = await db.execute("""
                        SELECT b.id, b.user_id, b.username, b.phone_number, p.name, b.car_number, b.booking_datetime
                        FROM bookings b
                        LEFT JOIN programs p ON b.program_id = p.id
                        WHERE b.car_number=?
                        ORDER BY booking_datetime
                    """, (query.upper(),))
                    rows = await cursor.fetchall()

    if not rows:
        await message.answer("📭 Немає бронювань за цим запитом")
        return

    text = "📋 Бронювання:\n\n"
    for r in rows:
        booking_time = datetime.fromisoformat(r[6])
        text += (
            f"ID: {r[0]}\n"
            f"👤 UserID: {r[1]} | @{r[2]}\n"
            f"📞 {r[3]}\n"
            f"🚗 {r[5]}\n"
            f"📅 {booking_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🧾 Програма: {r[4]}\n"
            f"---\n"
        )

    await message.answer(text)

@router.message(Command("delete"))
async def delete_booking(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Немає прав")
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("⚠ Використання: /delete <ID>")
        return

    booking_id = int(parts[1])
    async with aiosqlite.connect("carwash.db") as db:
        cursor = await db.execute("SELECT id FROM bookings WHERE id=?", (booking_id,))
        row = await cursor.fetchone()
        if not row:
            await message.answer("❌ Такого бронювання не існує")
            return
        await db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        await db.commit()
    await message.answer(f"🗑 Бронювання {booking_id} видалено")

@router.message(Command("edit"))
async def edit_booking(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Немає прав")
        return

    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("⚠ Використання: /edit <ID> <дата> <година>\nПриклад: /edit 5 25.08.2025 14:30")
        return

    try:
        booking_id = int(parts[1])
        new_date = datetime.strptime(parts[2], "%d.%m.%Y").date()
        new_time = datetime.strptime(parts[3], "%H:%M").time()
        new_dt = datetime.combine(new_date, new_time)
    except Exception as e:
        await message.answer("❌ Невірний формат дати або часу")
        return

    async with aiosqlite.connect("carwash.db") as db:
        cursor = await db.execute("SELECT id FROM bookings WHERE id=?", (booking_id,))
        row = await cursor.fetchone()
        if not row:
            await message.answer("❌ Такого бронювання не існує")
            return
        await db.execute("UPDATE bookings SET booking_datetime=? WHERE id=?", (new_dt.isoformat(), booking_id))
        await db.commit()
    await message.answer(f"✏ Бронювання {booking_id} змінено на {new_dt.strftime('%d.%m.%Y %H:%M')}")


@router.message(Command("add_program"))
async def add_program(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Немає прав")
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("⚠ Використання: /add_program <назва> <год:хв:сек>")
        return
    duration_str = parts[-1]
    try:
        h, m, s = map(int, duration_str.split(":"))
        duration_minutes = h*60 + m + s//60
    except:
        await message.answer("❌ Невірний формат")
        return
    name = " ".join(parts[1:-1])
    async with aiosqlite.connect("carwash.db") as db:
        try:
            await db.execute("INSERT INTO programs (name, duration) VALUES (?, ?)", (name, duration_minutes))
            await db.commit()
            await message.answer(f"✅ Додано '{name}' ({duration_minutes} хв)")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Програма вже існує")

# --- Бронювання ---
@router.message(Command("book"))
async def book_program(message: types.Message):
    programs = await get_programs()
    if not programs:
        await message.answer("Програми ще не додані.")
        return
    buttons = [[KeyboardButton(text=f"{p[0]} - {p[1]}")] for p in programs]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Оберіть програму:", reply_markup=keyboard)
    user_booking[message.from_user.id] = {}

@router.message()
async def process_booking(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_booking:
        return
    data = user_booking[user_id]

    # 1️⃣ Програма
    if "program_id" not in data:
        try:
            data["program_id"] = int(message.text.split(" - ")[0])
        except:
            await message.answer("Оберіть програму кнопкою.")
            return
        await message.answer("Оберіть дату:", reply_markup=generate_date_buttons())
        return

    # 2️⃣ Дата
    if "booking_date" not in data:
        try:
            date = datetime.strptime(message.text, "%d.%m.%Y").date()
            if date < datetime.today().date():
                raise ValueError
            data["booking_date"] = date
        except:
            await message.answer("❌ Невірна дата")
            return

        hours = await get_available_hours(data["program_id"], data["booking_date"])
        if not hours:
            await message.answer("❌ Немає вільних годин, оберіть іншу дату", reply_markup=generate_date_buttons())
            data.pop("booking_date")
            return

        buttons = [[KeyboardButton(text=h)] for h in hours]
        await message.answer("Оберіть годину:", reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True))
        return


    # 3️⃣ Час
    if "booking_time" not in data:
        hours = await get_available_hours(data["program_id"], data["booking_date"])
        if message.text not in hours:
            await message.answer("❌ Ця година вже зайнята")
            return
        data["booking_time"] = message.text
        await message.answer("Введіть номер авто:", reply_markup=ReplyKeyboardRemove())
        return

    # 4️⃣ Авто
    if "car_number" not in data:
        if not re.match(r"^[A-ZА-ЯІЇЄ]{2}\d{4}[A-ZА-ЯІЇЄ]{2}$", message.text.upper()):
            await message.answer("❌ Невірний формат номера. Приклад: AA1234BB")
            return
        data["car_number"] = message.text.upper()
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📞 Поділитися номером", request_contact=True)]], resize_keyboard=True)
        await message.answer("Надішліть свій номер телефону:", reply_markup=kb)
        return

    # 5️⃣ Телефон
    if "phone_number" not in data:
        if message.contact and message.contact.phone_number:
            data["phone_number"] = message.contact.phone_number
        else:
            await message.answer("❌ Використайте кнопку, щоб поділитися номером")
            return

        booking_dt = datetime.combine(data["booking_date"], datetime.strptime(data["booking_time"], "%H:%M").time())
        booking_str = booking_dt.strftime("%Y-%m-%d %H:%M:%S")
        username = message.from_user.username or "Не вказано"
        async with aiosqlite.connect("carwash.db") as db:
            await db.execute("""
                INSERT INTO bookings (user_id, username, phone_number, program_id, car_number, booking_datetime)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, data["phone_number"], data["program_id"], data["car_number"], booking_str))
            await db.commit()

        await message.answer(
            f"✅ Запис підтверджено:\n"
            f"📅 {data['booking_date']} ⏰ {data['booking_time']}\n"
            f"🚗 {data['car_number']}\n"
            f"📞 {data['phone_number']}",
            reply_markup=ReplyKeyboardRemove()
        )
        user_booking.pop(user_id)

# --- Старт ---
async def main():
    await init_db()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
