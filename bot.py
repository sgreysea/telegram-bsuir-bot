import os
import json
import logging
from datetime import datetime, timedelta
import urllib.request
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден в переменных окружения!")

USERS_FILE = "users.json"


# -----------------------------------------------------------
#                 ФАЙЛЫ С ПОЛЬЗОВАТЕЛЯМИ
# -----------------------------------------------------------
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

users = load_users()


# -----------------------------------------------------------
#                      МЕНЮ
# -----------------------------------------------------------
def get_menu():
    kb = [
        [KeyboardButton("расписание на сегодня")],
        [KeyboardButton("расписание на завтра")],
        [KeyboardButton("рассписание на неделю")],
        [KeyboardButton("уведомления")],
        [KeyboardButton("установить группу")],
        [KeyboardButton("помощь")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# -----------------------------------------------------------
#                    API BSUIR
# -----------------------------------------------------------
def _get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except:
        return None

def get_current_week():
    try:
        with urllib.request.urlopen("https://iis.bsuir.by/api/v1/schedule/current-week") as r:
            return int(r.read().decode("utf-8"))
    except:
        return None

def get_schedule(group):
    url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={group}"
    data = _get_json(url)
    if not data or "schedules" not in data:
        return None
    return data["schedules"]


# -----------------------------------------------------------
#                ФОРМАТИРОВАНИЕ РАСПИСАНИЯ
# -----------------------------------------------------------
def format_day(schedules, day):
    week = get_current_week()

    lessons = schedules.get(day)
    if not lessons:
        return f"{day}: занятий нет"

    result = f"расписание на {day}:\n\n"

    for pair in lessons:
        # фильтрация по неделе
        weeks = pair.get("weekNumber")
        if isinstance(weeks, list) and week not in weeks:
            continue

        time = f"{pair['startLessonTime']} - {pair['endLessonTime']}"
        subject = pair["subject"]
        aud = ", ".join(pair.get("auditories", []))

        result += f"{time} | {subject} | {aud}\n"

    return result


def format_week(schedules):
    result = "расписание на неделю:\n\n"
    for day, lessons in schedules.items():
        result += f"{day}:\n"
        for pair in lessons:
            time = f"{pair['startLessonTime']} - {pair['endLessonTime']}"
            subject = pair["subject"]
            aud = ", ".join(pair.get("auditories", []))
            result += f"  {time} | {subject} | {aud}\n"
        result += "\n"
    return result


# -----------------------------------------------------------
#             ОБРАБОТЧИКИ КОМАНД
# -----------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот с расписанием БГУИР.\nУстанови свою группу.",
        reply_markup=get_menu()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "1) Нажми 'установить группу'\n"
        "2) Введи номер группы\n"
        "3) Используй меню.\n",
        reply_markup=get_menu()
    )


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user = str(update.message.from_user.id)

    # установка группы
    if text == "установить группу":
        context.user_data["await_group"] = True
        await update.message.reply_text("Введите номер группы:")
        return

    if context.user_data.get("await_group"):
        group = text
        schedules = get_schedule(group)
        if not schedules:
            await update.message.reply_text("Такой группы нет!")
            return

        users[user] = {"group": group}
        save_users(users)
        context.user_data["await_group"] = False
        await update.message.reply_text(f"Группа {group} сохранена!", reply_markup=get_menu())
        return

    # если нет группы
    if user not in users:
        await update.message.reply_text("Сначала установите группу!")
        return

    group = users[user]["group"]
    schedules = get_schedule(group)
    if not schedules:
        await update.message.reply_text("Ошибка при получении расписания")
        return

    # дни недели
    weekdays = {
        "monday": "Понедельник",
        "tuesday": "Вторник",
        "wednesday": "Среда",
        "thursday": "Четверг",
        "friday": "Пятница",
        "saturday": "Суббота",
        "sunday": "Воскресенье"
    }

    if text == "расписание на сегодня":
        ru = weekdays[datetime.now().strftime("%A").lower()]
        await update.message.reply_text(format_day(schedules, ru))
        return

    if text == "расписание на завтра":
        ru = weekdays[(datetime.now() + timedelta(days=1)).strftime("%A").lower()]
        await update.message.reply_text(format_day(schedules, ru))
        return

    if text == "рассписание на неделю":
        await update.message.reply_text(format_week(schedules))
        return


# -----------------------------------------------------------
#                       ГЛАВНАЯ ФУНКЦИЯ
# -----------------------------------------------------------
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.TEXT, handle))

    print("Бот запущен...")
    await application.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
