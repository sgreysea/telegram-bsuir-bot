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
    print("ERROR: BOT_TOKEN не нашелся .env")
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
        ["расписание на неделю"],
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
        if isinstance(weeks, list) and week not in weeks:
            continue
        text += (
            f"{lesson['startLessonTime']} - {lesson['endLessonTime']} | "
            f"{lesson['subject']} | "
            f"{', '.join(lesson.get('auditories', []))}\n"
        )
    return text

week_order = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье"
]

def format_schedule_week(schedules):
    week = get_current_week()
    text = f"расписание на {week}-ю неделю:\n\n"

    for day in week_order:
        lessons = schedules.get(day, [])
        text += f"{day}:\n"

        shown = False
        for lesson in lessons:
            weeks = lesson.get("weekNumber")

            # Фильтр по неделям
            if isinstance(weeks, list) and week not in weeks:
                continue

            shown = True
            text += (
                f"  {lesson['startLessonTime']} - {lesson['endLessonTime']} | "
                f"{lesson['subject']} | "
                f"{', '.join(lesson.get('auditories', []))}\n"
            )

        if not shown:
            text += "  нет занятий\n"

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
        "2. введи номер своей группы\n"
        "3. пользуйся меню чтобы вывести расписание\n\n",
        reply_markup=get_menu()
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    uid = str(update.message.from_user.id)

    if text == "помощь":
        await help_cmd(update, context)

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

    user = users.get(uid)
    if not user or "group" not in user:
        await update.message.reply_text("сначала установи группу.")
        return

    group = user["group"]

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

    if text == "расписание на неделю":
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
    if uid not in users:
        await update.message.reply_text("сначала установи группу.")
        return

def get_ru_weekday(dt=None):
    if dt is None:
        dt = datetime.now()
    ru_days = {
        0: "Понедельник",
        1: "Вторник",
        2: "Среда",
        3: "Четверг",
        4: "Пятница",
        5: "Суббота",
        6: "Воскресенье",
    }
    return ru_days[dt.weekday()]

sent_notifications = {}  

async def notifications(context: ContextTypes.DEFAULT_TYPE):
    global users, sent_notifications
    users = load_users()

    now = datetime.now()
    now_time = now.time()
    weekday = get_ru_weekday()

    current_week = get_current_week()
    if not current_week:
        return

    for uid, data in users.items():

        if not data.get("notify", False):
            continue

        if uid not in sent_notifications:
            sent_notifications[uid] = {"next10": set()}

        try:
            sched = get_schedule(data["group"])
            if not sched:
                continue

            lessons = sched.get(weekday, [])
            if not lessons:
                continue

            # сортировка по времени
            try:
                lessons = sorted(
                    lessons,
                    key=lambda x: datetime.strptime(x["startLessonTime"], "%H:%M")
                )
            except:
                pass

            for i, lesson in enumerate(lessons):
                # Фильтруем по неделе
                weeks = lesson.get("weekNumber")
                if isinstance(weeks, list) and current_week not in weeks:
                    continue
                # время пары
                try:
                    start_t = datetime.strptime(lesson["startLessonTime"], "%H:%M").time()
                    end_t = datetime.strptime(lesson["endLessonTime"], "%H:%M").time()
                except:
                    continue
                start_dt = datetime.combine(now.date(), start_t)
                end_dt = datetime.combine(now.date(), end_t)
                now_dt = datetime.combine(now.date(), now_time)
                if start_t <= now_time <= end_t:
                    minutes_left = (end_dt - now_dt).total_seconds() / 60
                    if 9 <= minutes_left <= 11:   # окно 30 секунд
                        # нельзя слать повторно
                        notif_key = f"{lesson['startLessonTime']}_next10"
                        if notif_key in sent_notifications[uid]["next10"]:
                            continue
                        sent_notifications[uid]["next10"].add(notif_key)
                        # ищем следующую пару
                        if i + 1 < len(lessons):
                            next_lesson = lessons[i + 1]
                            # фильтруем по неделе
                            next_weeks = next_lesson.get("weekNumber")
                            if isinstance(next_weeks, list) and current_week not in next_weeks:
                                continue

                            subject = next_lesson.get("subject", "следующая пара")
                            aud = next_lesson.get("auditories", ["ауд. не указана"])[0]
                            next_start = next_lesson["startLessonTime"]
                            next_end = next_lesson["endLessonTime"]

                            msg = (
                                f"через 10 минут закончится пара\n\n"
                                f"следующая пара:\n"
                                f"{subject}\n"
                                f"{next_start}-{next_end}\n"
                                f"{aud}"
                            )

                            await context.bot.send_message(chat_id=int(uid), text=msg)

        except Exception as e:
            logging.error(f"ошибка пользователя? {uid}: {e}")
            continue

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