import os
import json
import logging
import urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv

from flask import Flask
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import threading
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found in .env")
    exit(1)

USERS_FILE = "users.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s"
)

app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Telegram Bot is running 24/7", 200


# ---------------------- USER STORAGE ----------------------

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

users = load_users()

# ---------------------- MENU ----------------------

def get_menu():
    return ReplyKeyboardMarkup([
        ["расписание на сегодня"],
        ["расписание на завтра"],
        ["расписание на неделю"],
        ["уведомления"],
        ["установить группу"],
        ["помощь"]
    ], resize_keyboard=True)


# ---------------------- API HELPERS ----------------------

def _http_get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logging.error("HTTP Error: %s", e)
        return None


def get_current_week():
    try:
        with urllib.request.urlopen("https://iis.bsuir.by/api/v1/schedule/current-week") as r:
            return int(r.read().decode("utf-8"))
    except:
        return None


def get_schedule(group):
    url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={group}"
    data = _http_get_json(url)

    if not data or "schedules" not in data:
        return None

    try:
        # ВАЖНО! Теперь возвращаем ПРАВИЛЬНЫЙ словарь
        return data["schedules"][0]["schedule"]
    except:
        return None


# ---------------------- SCHEDULE FORMATTING ----------------------

def format_schedule_day(schedules, day_key):
    """day_key: 'monday', 'tuesday', ..."""
    week = get_current_week()
    lessons = schedules.get(day_key, [])

    if not lessons:
        return f"{day_key}: занятий нет"

    text = f"Расписание на {day_key}:\n\n"

    for lesson in lessons:
        weeks = lesson.get("weekNumber")

        # показываем только подходящую неделю
        if isinstance(weeks, list) and week not in weeks:
            continue

        text += (
            f"{lesson['startLessonTime']} - {lesson['endLessonTime']} | "
            f"{lesson['subject']} | "
            f"{', '.join(lesson.get('auditories', []))}\n"
        )

    if text.strip() == f"Расписание на {day_key}:":
        return f"{day_key}: занятий нет (по неделе)"

    return text


def format_schedule_week(schedules):
    current_week = get_current_week()
    logging.info(f"Текущая неделя: {current_week}")

    text = "Расписание на неделю"
    if current_week:
        text += f" (неделя {current_week})"
    text += ":\n\n"

    # Порядок дней
    days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    ru_days = {
        "monday": "Понедельник",
        "tuesday": "Вторник",
        "wednesday": "Среда",
        "thursday": "Четверг",
        "friday": "Пятница",
        "saturday": "Суббота",
        "sunday": "Воскресенье",
    }

    for day_key in days_order:
        text += f"{ru_days[day_key]}:\n"

        lessons = schedules.get(day_key, [])
        if not lessons:
            text += "  нет занятий\n\n"
            continue

        for lesson in lessons:
            weeks = lesson.get("weekNumber", "не указано")
            text += (
                f"  {lesson['startLessonTime']} - {lesson['endLessonTime']} | "
                f"{lesson['subject']} | "
                f"{', '.join(lesson.get('auditories', []))} | "
                f"недели: {weeks}\n"
            )

        text += "\n"

    return text


# ---------------------- TELEGRAM HANDLERS ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "привет! установи свою группу, чтобы я работал.",
        reply_markup=get_menu()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ИНСТРУКЦИЯ:\n1. нажми «установить группу»\n2. введи номер\n3. пользуйся меню",
        reply_markup=get_menu()
    )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    uid = str(update.message.from_user.id)

    # ---------- установка группы ----------
    if text == "установить группу":
        context.user_data["await_group"] = True
        await update.message.reply_text("введи номер группы:")
        return

    if context.user_data.get("await_group"):
        group = text
        sched = get_schedule(group)
        if not sched:
            await update.message.reply_text("группа не найдена.")
            return

        users[uid] = {"group": group, "notify": False}
        save_users(users)
        context.user_data["await_group"] = False

        await update.message.reply_text(f"группа {group} сохранена", reply_markup=get_menu())
        return

    # если группа не установлена
    if uid not in users:
        await update.message.reply_text("сначала установи группу")
        return

    group = users[uid]["group"]
    sched = get_schedule(group)

    if not sched:
        await update.message.reply_text("ошибка загрузки расписания")
        return

    days_map = {
        "monday": "понедельник",
        "tuesday": "вторник",
        "wednesday": "среда",
        "thursday": "четверг",
        "friday": "пятница",
        "saturday": "суббота",
        "sunday": "воскресенье"
    }
    reverse_map = {v: k for k, v in days_map.items()}

    # ---------- сегодня ----------
    if text == "расписание на сегодня":
        day_key = reverse_map[datetime.now().strftime("%A").lower()]
        await update.message.reply_text(format_schedule_day(sched, day_key))
        return

    # ---------- завтра ----------
    if text == "расписание на завтра":
        day_key = reverse_map[(datetime.now() + timedelta(days=1)).strftime("%A").lower()]
        await update.message.reply_text(format_schedule_day(sched, day_key))
        return

    # ---------- неделя ----------
    if text == "расписание на неделю":
        await update.message.reply_text(format_schedule_week(sched))
        return

    # ---------- уведомления ----------
    if text == "уведомления":
        users[uid]["notify"] = not users[uid]["notify"]
        save_users(users)

        await update.message.reply_text(
            "уведомления включены" if users[uid]["notify"] else "уведомления отключены",
            reply_markup=get_menu()
        )
        return

    if text == "помощь":
        await help_cmd(update, context)
        return

    await update.message.reply_text("Используй меню", reply_markup=get_menu())


# ---------------------- NOTIFICATIONS ----------------------

async def notifications(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    day_key = now.strftime("%A").lower()

    for uid, data in users.items():
        if not data.get("notify"):
            continue

        group = data.get("group")
        schedules = get_schedule(group)
        if not schedules:
            continue

        lessons = schedules.get(day_key, [])
        if not lessons:
            continue

        first = lessons[0]
        start = first.get("startLessonTime")
        if not start:
            continue

        lesson_time = datetime.strptime(start, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        notify_time = lesson_time - timedelta(minutes=10)

        if abs((now - notify_time).total_seconds()) <= 30:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=f"Через 10 минут первая пара!\n{first.get('subject')}"
                )
            except Exception as e:
                logging.error(e)


# ---------------------- LAUNCH ----------------------

def run_flask_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def run_telegram_bot():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_cmd))
        application.add_handler(MessageHandler(filters.TEXT, handle))

        application.job_queue.run_repeating(notifications, interval=30, first=10)

        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        loop.run_until_complete(application.updater.start_polling())

        loop.run_forever()

    except Exception as e:
        logging.error(f"Ошибка запуска бота: {e}")


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()

    run_flask_server()
