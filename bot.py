import os
import logging
import json
import asyncio
import urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

USERS_FILE = "users.json"#файл для данных юзеров
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

import os
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logging.error("BOT_TOKEN не установлен!")
    exit(1)

user_groups = {}

def get_menu():
    keyboard = [
        [KeyboardButton('расписание на сегодня')],
        [KeyboardButton('расписание на завтра')],
        [KeyboardButton('рассписание на неделю')],
        [KeyboardButton('уведомления')],
        [KeyboardButton('установить группу')],
        [KeyboardButton('помощь')]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

users = load_users()

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

def _http_get_json(url, log_prefix=""):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read().decode("utf-8")
            logging.info("%s: raw response length=%d", log_prefix, len(data))
            return json.loads(data)
    except Exception as e:
        logging.exception("%s: ошибка HTTP запроса %s", log_prefix, e)
        return None

def get_current_week():
    url = "https://iis.bsuir.by/api/v1/schedule/current-week"
    try:
        with urllib.request.urlopen(url) as response:
            data = response.read().decode("utf-8")
            return int(data)
    except Exception as e:
        print("возникла ошибочка, при получении недели:", e)
        return None

def get_shedule_for_variant(group_variant):
    url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={group_variant}"
    json_data = _http_get_json(url, f"schedule?studentGroup={group_variant}")
    return json_data

def get_shedule(group):
    variants = [group]
    if not group.startswith("0"):
        variants.append("0" + group)
    tried = set()

    for v in variants:
        if v in tried:
            continue
        tried.add(v)

        json_data = get_shedule_for_variant(v)
        if not json_data:
            continue

        if isinstance(json_data, dict) and "schedules" in json_data:
            schedules = json_data["schedules"]
            if isinstance(schedules, dict):
                logging.info("найдено расписание для группы variant=%s", v)
                return schedules
            else:
                logging.warning("schedules найден, но тип=%s", type(schedules).__name__)

        else:
            logging.debug("Ответ для %s: %s", v, json.dumps(json_data, ensure_ascii=False)[:2000])

    return None


def format_schedule_week(schedules):
    current_week = get_current_week()
    result = "расписание на неделю:\n\n"

    for day, lessons in schedules.items():
        result += f"{day}"
        filtered = []

        for lesson in lessons:
            weeks = lesson.get("weekNumber")

            if isinstance(weeks, list):
                if current_week in weeks:
                    filtered.append(lesson)
            else:
                filtered.append(lesson)

        if not filtered:
            result += " нет занятий\n"
            continue

        for lesson in filtered:
            time = f"{lesson['startLessonTime']} - {lesson['endLessonTime']}"
            subject = lesson['subject']
            aud = ", ".join(lesson.get("auditories", []))
            result += f"  {time} | {subject} | {aud}\n"

        result += "\n"

    return result


def format_schedule_day(schedules, weekday_name):
    current_week = get_current_week()
    logging.info("текущая неделя: %s", current_week)

    if weekday_name not in schedules:
        return f"{weekday_name} - занятий нет, отдыхаем)"

    lessons = schedules[weekday_name]
    if not isinstance(lessons, list):
        logging.error("jib,rf %s", type(lessons).__name__)
        return f"{weekday_name} - занятий нет, отдыхаем)"

    filtered = []
    for lesson in lessons:
        if not isinstance(lesson, dict):
            continue

        weeks = lesson.get("weekNumber")
        if weeks is None:
            filtered.append(lesson)
            continue

        if isinstance(weeks, list):
            normalized = []
            for w in weeks:
                try:
                    normalized.append(int(w))
                except:
                    pass
            if current_week is None or current_week in normalized:
                filtered.append(lesson)

        else:
            try:
                wnum = int(weeks)
                if current_week is None or wnum == current_week:
                    filtered.append(lesson)
            except:
                filtered.append(lesson)

    lessons = filtered

    if not lessons:
        return f"{weekday_name} - занятий нет, отдыхаем)"

    result = f"расписание на {weekday_name}:\n\n"
    for lesson in lessons:
        start = lesson.get("startLessonTime") or ""
        end = lesson.get("endLessonTime") or ""
        subject = lesson.get("subject") or "без названия"
        aud_list = lesson.get("auditories") or []
        aud = ", ".join(aud_list)

        result += f"{start} - {end} | {subject} | {aud}\n"

    return result

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет я бот с расписанием БГУИР.\n Установи свою группу через меню",
        reply_markup=get_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
ИНСТРУКЦИЯ:
1. нажми установить группу
2. введи ПРАВИЛЬНЫЙ номер группы
3. используй кнопочки из меню для вывода рассписания
удачи:)
    """
    await update.message.reply_text(help_text, reply_markup=get_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = update.message.from_user.id

    if text == "установить группу":
        await update.message.reply_text("введите номер группы:")
        context.user_data["awaiting_group"] = True
        return

    if context.user_data.get("awaiting_group"):
        group = text.strip()
        schedules = get_shedule(group)

        if schedules is None:
            await update.message.reply_text("такой группы не существует!")
            return

        user_groups[user_id] = group
        users[str(user_id)] = {"group": group, "notify": False}
        save_users(users)

        context.user_data["awaiting_group"] = False

        await update.message.reply_text(
            f"группа {group} сохранена!",
            reply_markup=get_menu()
        )
        return

    if str(user_id) not in users:
        await update.message.reply_text("сначала установите группу")
        return

    group = users[str(user_id)]["group"]
    schedules = get_shedule(group)

    if schedules is None:
        await update.message.reply_text("случилась ошиюка, при получении расписания")
        return
    weekdays = {
        "Monday": "Понедельник",
        "Tuesday": "Вторник",
        "Wednesday": "Среда",
        "Thursday": "Четверг",
        "Friday": "Пятница",
        "Saturday": "Суббота",
        "Sunday": "Воскресенье"
    }
    if text == "расписание на сегодня":
        weekday_ru = weekdays[datetime.now().strftime("%A")]
        await update.message.reply_text(format_schedule_day(schedules, weekday_ru))
        return
    if text == "расписание на завтра":
        weekday_ru = weekdays[(datetime.now() + timedelta(days=1)).strftime("%A")]
        await update.message.reply_text(format_schedule_day(schedules, weekday_ru))
        return
    if text == "рассписание на неделю":
        await update.message.reply_text(format_schedule_week(schedules))
        return
    if text == "уведомления":
        cur = users[str(user_id)]["notify"]
        users[str(user_id)]["notify"] = not cur
        save_users(users)
        if cur:
            await update.message.reply_text("уведомления отключены", reply_markup=get_menu())
        else:
            await update.message.reply_text("уведомления включены", reply_markup=get_menu())
        return
    if text == "помощь":
        await help_command(update, context)

async def notification_loop(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    now = datetime.now().strftime("%H:%M")
    weekday = datetime.now().strftime("%A")
    for user_id, data in users.items():
        if not data["notify"] or not data["group"]:
            continue
        schedules = get_shedule(data["group"])
        todays = schedules.get(weekday, [])
        if todays:
            first = todays[0]
            start = first["startLessonTime"]
            # 10 минут до пары
            t10 = (datetime.strptime(start, "%H:%M") - timedelta(minutes=10)).strftime("%H:%M")
            if now == t10:
                try:
                    await app.bot.send_message(chat_id=int(user_id), text="через 10 минут первая пара!")
                except:
                    pass

        # уведомления о следующей паре
        for i, lesson in enumerate(todays):
            end_time = lesson["endLessonTime"]
            t5 = (datetime.strptime(end_time, "%H:%M") - timedelta(minutes=5)).strftime("%H:%M")
            if now == t5:
                if i + 1 < len(todays):
                    next_lesson = todays[i+1]
                    aud = ", ".join(next_lesson.get("auditories", []))
                    text = (
                        "через 5 минут закончится пара.\n"
                        f"следующая: {next_lesson['subject']}\nаудитория: {aud}"
                    )
                else:
                    text = "через 5 минут закончится последняя пара на сегодня!"
                try:
                    await app.bot.send_message(chat_id=int(user_id), text=text)
                except:
                    pass

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f'ошибка: {context.error}')

async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    # команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    # сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # ошибки
    application.add_error_handler(error_handler)
    # уведомления
    application.job_queue.run_repeating(
        notification_loop,
        interval=30,
        first=5
    )
    # запуск бота 
    await application.initialize()
    await application.start()
    print("бот запущен...")

    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
