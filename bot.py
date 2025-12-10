import os
import json
import logging
import asyncio
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN отсутствует!")

USERS_FILE = "users.json"


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)


users = load_users()


def get_menu():
    k = [
        [KeyboardButton("расписание на сегодня")],
        [KeyboardButton("расписание на завтра")],
        [KeyboardButton("рассписание на неделю")],
        [KeyboardButton("уведомления")],
        [KeyboardButton("установить группу")],
        [KeyboardButton("помощь")],
    ]
    return ReplyKeyboardMarkup(k, resize_keyboard=True)


# ============ API Функции (оставляю как есть, ты вставишь свои) ===========

import urllib.request


def _http_get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except:
        return None


def get_current_week():
    try:
        with urllib.request.urlopen("https://iis.bsuir.by/api/v1/schedule/current-week") as r:
            return int(r.read().decode("utf-8"))
    except:
        return None


def get_shedule_for_variant(group):
    url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={group}"
    return _http_get_json(url)


def get_shedule(group):
    for g in [group, f"0{group}"]:
        data = get_shedule_for_variant(g)
        if data and "schedules" in data:
            return data["schedules"]
    return None


def format_schedule_day(schedules, day):
    if day not in schedules:
        return f"{day} — нет пар"

    lessons = schedules[day]
    res = f"расписание на {day}:\n\n"
    for l in lessons:
        res += f"{l['startLessonTime']} - {l['endLessonTime']} | {l['subject']}\n"
    return res


def format_schedule_week(schedules):
    res = "расписание на неделю:\n\n"
    for day, lessons in schedules.items():
        res += f"{day}:\n"
        for l in lessons:
            res += f"  {l['startLessonTime']} - {l['endLessonTime']} | {l['subject']}\n"
        res += "\n"
    return res


# ===================== HANDLERS ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Установи группу через меню ↓",
        reply_markup=get_menu(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "1) Нажми «установить группу»\n"
        "2) Введи номер группы\n"
        "3) Используй меню!"
    )


async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    uid = str(update.message.from_user.id)

    if text == "установить группу":
        context.user_data["await_group"] = True
        return await update.message.reply_text("Введите вашу группу:")

    if context.user_data.get("await_group"):
        group = text
        sch = get_shedule(group)
        if sch is None:
            return await update.message.reply_text("Такой группы нет!")

        users[uid] = {"group": group, "notify": False}
        save_users(users)

        context.user_data["await_group"] = False
        return await update.message.reply_text(
            f"Группа {group} сохранена!",
            reply_markup=get_menu(),
        )

    if uid not in users:
        return await update.message.reply_text("Сначала установите группу!")

    group = users[uid]["group"]
    schedules = get_shedule(group)

    weekdays = {
        "Monday": "Понедельник",
        "Tuesday": "Вторник",
        "Wednesday": "Среда",
        "Thursday": "Четверг",
        "Friday": "Пятница",
        "Saturday": "Суббота",
        "Sunday": "Воскресенье",
    }

    if text == "расписание на сегодня":
        today = weekdays[datetime.now().strftime("%A")]
        return await update.message.reply_text(format_schedule_day(schedules, today))

    if text == "расписание на завтра":
        tomorrow = weekdays[(datetime.now() + timedelta(days=1)).strftime("%A")]
        return await update.message.reply_text(format_schedule_day(schedules, tomorrow))

    if text == "рассписание на неделю":
        return await update.message.reply_text(format_schedule_week(schedules))

    if text == "уведомления":
        users[uid]["notify"] = not users[uid]["notify"]
        save_users(users)

        if users[uid]["notify"]:
            return await update.message.reply_text("Уведомления включены")
        return await update.message.reply_text("Уведомления отключены")

    if text == "помощь":
        return await help_cmd(update, context)


# ===================== JOB QUEUE ======================

async def notify_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%H:%M")
    weekday = datetime.now().strftime("%A")

    for uid, data in users.items():
        if not data["notify"]:
            continue

        sch = get_shedule(data["group"])
        lessons = sch.get(weekday, [])
        if not lessons:
            continue

        first = lessons[0]
        start = first["startLessonTime"]
        before10 = (datetime.strptime(start, "%H:%M") - timedelta(minutes=10)).strftime("%H:%M")

        if now == before10:
            await context.bot.send_message(uid, "Через 10 минут первая пара!")

# ===================== MAIN ======================


async def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))

    application.job_queue.run_repeating(notify_job, interval=30, first=10)

    print("Бот запущен...")
    await application.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
