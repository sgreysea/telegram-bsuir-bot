import os
import json
import logging
import asyncio
import urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
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

def format_schedule_day(schedules, day):
    week = get_current_week()
    lessons = schedules.get(day, [])
    if not lessons:
        return f"{day}: занятий нет"
    text = f"расписание на {day}:\n\n"
    for lesson in lessons:
        weeks = lesson.get("weekNumber")
        # check by week
        if isinstance(weeks, list) and week not in weeks:
            continue
        text += (
            f"{lesson['startLessonTime']} - {lesson['endLessonTime']} | "
            f"{lesson['subject']} | "
            f"{', '.join(lesson.get('auditories', []))}\n"
        )
    return text

def format_schedule_week(schedules):
    text = "расписание на неделю:\n\n"
    for day, lessons in schedules.items():
        text += f"{day}:\n"
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "привет, чтобы работать с ботом надо установить группу", reply_markup=get_menu()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ИНСТРУКЦИЯ:\n"
        "1. нажми «установить группу»\n"
        "2. введи номер\n"
        "3. пользуйся меню\n\n",
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
        await update.message.reply_text(f"Группа {group} сохранена!", reply_markup=get_menu())
        return

    if uid not in users:
        await update.message.reply_text("сначала установи группу.")
        return

    group = users[uid]["group"]
    sched = get_schedule(group)
    if not sched:
        await update.message.reply_text("ошибка загрузки расписания")
        return

    ru = {
        "monday": "Понедельник",
        "tuesday": "Вторник",
        "wednesday": "Среда",
        "thursday": "Четверг",
        "friday": "Пятница",
        "saturday": "Суббота",
        "sunday": "Воскресенье",
    }

    if text == "расписание на сегодня":
        d = ru[datetime.now().strftime("%A").lower()]
        await update.message.reply_text(format_schedule_day(sched, d))
        return

    if text == "расписание на завтра":
        d = ru[(datetime.now() + timedelta(days=1)).strftime("%A").lower()]
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
    now = datetime.now().strftime("%H:%M")
    weekday = datetime.now().strftime("%A")

    for uid, data in users.items():
        if not data["notify"]:
            continue

        sched = get_schedule(data["group"])
        lessons = sched.get(weekday, [])

        if not lessons:
            continue

        first = lessons[0]["startLessonTime"]
        before10 = (datetime.strptime(first, "%H:%M") - timedelta(minutes=10)).strftime("%H:%M")

        if now == before10:
            await context.bot.send_message(chat_id=int(uid), text="через 10 минут первая пара!")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT, handle))
    
    app.job_queue.run_repeating(notifications, interval=30, first=10)
    
    print("бот запускается...")
    app.run_polling()

if __name__ == "__main__":

    main()
