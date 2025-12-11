import os
import json
import logging
import urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv

from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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

# ============= FLASK (только для порта) =============
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Telegram Bot is running (polling mode)"

@app.route("/health")
def health():
    return "OK", 200
# ====================================================

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

users = load_users()

def get_menu():
    return ReplyKeyboardMarkup([
        ["расписание на сегодня"],
        ["расписание на завтра"],
        ["рассписание на неделю"],
        ["уведомления"],
        ["установить группу"],
        ["помощь"]
    ], resize_keyboard=True)

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
        with urllib.request.urlopen(
            "https://iis.bsuir.by/api/v1/schedule/current-week"
        ) as r:
            return int(r.read().decode("utf-8"))
    except:
        return None

def get_schedule(group):
    url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={group}"
    data = _http_get_json(url)
    if not data or "schedules" not in data:
        return None
    return data["schedules"]

DAY_RU = {
    "Monday": "Понедельник",
    "Tuesday": "Вторник",
    "Wednesday": "Среда",
    "Thursday": "Четверг",
    "Friday": "Пятница",
    "Saturday": "Суббота",
    "Sunday": "Воскресенье",
}

def format_schedule_day(schedules, eng_day):
    week = get_current_week()
    lessons = schedules.get(eng_day, [])
    if not lessons:
        return f"{DAY_RU.get(eng_day, eng_day)}: занятий нет"

    text = f"Расписание на {DAY_RU[eng_day]}:\n\n"
    for lesson in lessons:
        if isinstance(lesson.get("weekNumber"), list) and week not in lesson["weekNumber"]:
            continue

        text += (
            f"{lesson['startLessonTime']} - {lesson['endLessonTime']} | "
            f"{lesson['subject']} | "
            f"{', '.join(lesson.get('auditories', []))}\n"
        )
    return text

def format_schedule_week(schedules):
    text = "Расписание на неделю:\n\n"
    for day, lessons in schedules.items():
        ru = DAY_RU.get(day, day)
        text += f"{ru}:\n"
        if not lessons:
            text += "  нет занятий\n\n"
            continue
        for lesson in lessons:
            text += (
                f"  {lesson['startLessonTime']} - {lesson['endLessonTime']} | "
                f"{lesson['subject']} | "
                f"{', '.join(lesson.get('auditories', []))}\n"
            )
        text += "\n"
    return text

# ================= HANDLERS ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "привет, чтобы работать с ботом надо установить группу",
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

        await update.message.reply_text(
            f"Группа {group} сохранена!",
            reply_markup=get_menu()
        )
        return

    if uid not in users:
        await update.message.reply_text("сначала установи группу.")
        return

    group = users[uid]["group"]
    sched = get_schedule(group)
    if not sched:
        await update.message.reply_text("ошибка загрузки расписания")
        return

    if text == "расписание на сегодня":
        d = datetime.now().strftime("%A")
        await update.message.reply_text(format_schedule_day(sched, d))
        return

    if text == "расписание на завтра":
        d = (datetime.now() + timedelta(days=1)).strftime("%A")
        await update.message.reply_text(format_schedule_day(sched, d))
        return

    if text == "рассписание на неделю":
        await update.message.reply_text(format_schedule_week(sched))
        return

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

async def notifications(context: ContextTypes.DEFAULT_TYPE):
    """Улучшенные уведомления с интервальной проверкой"""
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_weekday = now.strftime("%A")

    for uid, data in users.items():
        if not data.get("notify", False):
            continue

        user_group = data.get("group")
        if not user_group:
            continue

        schedules = get_schedule(user_group)
        if not schedules:
            continue

        today_lessons = schedules.get(current_weekday, [])
        if not today_lessons:
            continue

        first_lesson = today_lessons[0]
        first_lesson_start_str = first_lesson.get("startLessonTime")

        if not first_lesson_start_str:
            continue

        try:
            # Преобразуем время начала пары
            first_lesson_start = datetime.strptime(first_lesson_start_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            # Время за 10 минут до пары
            notification_time = first_lesson_start - timedelta(minutes=10)
            
            # Проверяем интервал ±30 секунд
            time_diff = abs((now - notification_time).total_seconds())
            
            if time_diff <= 30:
                try:
                    await context.bot.send_message(
                        chat_id=int(uid),
                        text=f"🧑‍🏫 Через 10 минут первая пара!\n📚 {first_lesson.get('subject', 'Предмет')}\n📍 Ауд: {', '.join(first_lesson.get('auditories', ['не указана']))}"
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки уведомления: {e}")
        except Exception as e:
            logging.error(f"Ошибка обработки времени: {e}")

# ================== ЗАПУСК ========================

def run_flask():
    """Запуск Flask в отдельном потоке"""
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Flask запускается на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def run_telegram_bot():
    """Запуск Telegram бота в основном потоке"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.TEXT, handle))
    
    application.job_queue.run_repeating(notifications, interval=30, first=10)
    
    logging.info("🤖 Telegram Bot запускается...")
    application.run_polling()

if __name__ == "__main__":
    import threading
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем Telegram бота в основном потоке
    run_telegram_bot()