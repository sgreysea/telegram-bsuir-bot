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

# ============= FLASK СЕРВЕР (ДЛЯ PORT HEALTH CHECK) =============
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Telegram Bot is running 24/7", 200

@app.route("/health")
def health():
    return "OK", 200

@app.route("/ping")
def ping():
    return "pong", 200

# ============= ФУНКЦИИ БОТА =============

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
WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def format_schedule_day(schedules, eng_day):
    """Расписание на конкретный день с фильтрацией по неделям"""
    current_week = get_current_week()
    lessons = schedules.get(eng_day, [])
    
    if not lessons:
        return f"{DAY_RU.get(eng_day, eng_day)}: занятий нет"
    
    # Фильтруем занятия по текущей неделе
    filtered_lessons = []
    for lesson in lessons:
        weeks = lesson.get("weekNumber")
        
        # Если нет информации о неделях - показываем занятие
        if weeks is None:
            filtered_lessons.append(lesson)
            continue
            
        # Если неделя указана как список (для четных/нечетных)
        if isinstance(weeks, list):
            # Преобразуем все элементы списка в int
            week_numbers = []
            for w in weeks:
                try:
                    week_numbers.append(int(w))
                except:
                    continue
            
            if current_week in week_numbers:
                filtered_lessons.append(lesson)
        
        # Если неделя указана как число
        else:
            try:
                # Пытаемся преобразовать в int
                week_num = int(weeks)
                if week_num == current_week:
                    filtered_lessons.append(lesson)
            except:
                # Если не получается преобразовать, показываем занятие
                filtered_lessons.append(lesson)
    
    if not filtered_lessons:
        return f"{DAY_RU.get(eng_day, eng_day)}: нет занятий на этой неделе"
    
    text = f"Расписание на {DAY_RU.get(eng_day, eng_day)}"
    if current_week:
        text += f" (неделя {current_week})"
    text += ":\n\n"
    
    # Сортируем занятия по времени начала
    filtered_lessons.sort(key=lambda x: x.get('startLessonTime', '00:00'))
    
    for lesson in filtered_lessons:
        subject = lesson.get('subject', 'Не указано')
        start_time = lesson.get('startLessonTime', '??:??')
        end_time = lesson.get('endLessonTime', '??:??')
        auditories = ', '.join(lesson.get('auditories', [])) or 'не указана'
        
        text += f"{start_time} - {end_time} | {subject} | {auditories}\n"
    
    return text

def format_schedule_week(schedules):
    """Расписание на неделю с фильтрацией по текущей неделе"""
    current_week = get_current_week()
    if current_week is None:
        return "Не удалось определить текущую неделю"
    
    text = f"📅 Расписание на неделю (неделя {current_week}):\n\n"
    
    # Идем по дням в правильном порядке
    for eng_day in WEEK_ORDER:
        ru_day = DAY_RU.get(eng_day, eng_day)
        lessons = schedules.get(eng_day, [])
        
        if not lessons:
            text += f"📌 {ru_day}: нет занятий\n\n"
            continue
        
        # Фильтруем занятия по текущей неделе
        filtered_lessons = []
        for lesson in lessons:
            weeks = lesson.get("weekNumber")
            
            # Если нет информации о неделях - показываем
            if weeks is None:
                filtered_lessons.append(lesson)
                continue
                
            # Если неделя указана как список
            if isinstance(weeks, list):
                # Преобразуем все в int
                week_numbers = []
                for w in weeks:
                    try:
                        week_numbers.append(int(w))
                    except:
                        continue
                
                if current_week in week_numbers:
                    filtered_lessons.append(lesson)
            
            # Если неделя указана как число
            else:
                try:
                    week_num = int(weeks)
                    if week_num == current_week:
                        filtered_lessons.append(lesson)
                except:
                    # Если не получается преобразовать, показываем
                    filtered_lessons.append(lesson)
        
        if not filtered_lessons:
            text += f"📌 {ru_day}: нет занятий на этой неделе\n\n"
            continue
        
        # Сортируем занятия по времени
        filtered_lessons.sort(key=lambda x: x.get('startLessonTime', '00:00'))
        
        text += f"📌 {ru_day}:\n"
        for lesson in filtered_lessons:
            subject = lesson.get('subject', 'Не указано')
            start_time = lesson.get('startLessonTime', '??:??')
            end_time = lesson.get('endLessonTime', '??:??')
            auditories = ', '.join(lesson.get('auditories', [])) or 'не указана'
            
            text += f"  🕒 {start_time} - {end_time}\n"
            text += f"  📚 {subject}\n"
            text += f"  📍 {auditories}\n\n"
    
    return text

# ============= ОБРАБОТЧИКИ ТЕЛЕГРАМ =============

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
        # Получаем английское название сегодняшнего дня
        today = datetime.now()
        eng_day = today.strftime("%A")
        ru_day = DAY_RU.get(eng_day, eng_day)
        
        # Проверяем, есть ли расписание на этот день
        if eng_day not in sched:
            current_week = get_current_week()
            week_info = f" (неделя {current_week})" if current_week else ""
            await update.message.reply_text(f"{ru_day}{week_info}: занятий нет")
            return
            
        schedule_text = format_schedule_day(sched, eng_day)
        await update.message.reply_text(schedule_text)
        return

    if text == "расписание на завтра":
        # Получаем английское название завтрашнего дня
        tomorrow = datetime.now() + timedelta(days=1)
        eng_day = tomorrow.strftime("%A")
        ru_day = DAY_RU.get(eng_day, eng_day)
        
        # Проверяем, есть ли расписание на этот день
        if eng_day not in sched:
            current_week = get_current_week()
            week_info = f" (неделя {current_week})" if current_week else ""
            await update.message.reply_text(f"{ru_day}{week_info}: занятий нет")
            return
            
        schedule_text = format_schedule_day(sched, eng_day)
        await update.message.reply_text(schedule_text)
        return

    if text == "рассписание на неделю":
        schedule_text = format_schedule_week(sched)
        await update.message.reply_text(schedule_text)
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
            first_lesson_start = datetime.strptime(first_lesson_start_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            notification_time = first_lesson_start - timedelta(minutes=10)
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

# ============= ЗАПУСК ВСЕГО =============

def run_flask_server():
    """Запуск Flask сервера для Render health check"""
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🌐 Flask сервер запущен на порту {port}")
    # Важно: use_reloader=False для избежания двойного запуска
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def run_telegram_bot():
    """Запуск Telegram бота в отдельном потоке"""
    try:
        # Создаем новое asyncio событие для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Создаем и настраиваем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_cmd))
        application.add_handler(MessageHandler(filters.TEXT, handle))
        
        application.job_queue.run_repeating(notifications, interval=30, first=10)
        
        logging.info("🤖 Telegram Bot запускается...")
        
        # Запускаем бота в этом event loop
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        logging.info("✅ Telegram Bot запущен и работает")
        
        # Запускаем polling
        loop.run_until_complete(application.updater.start_polling())
        
        # Держим loop активным
        loop.run_forever()
        
    except Exception as e:
        logging.error(f"❌ Ошибка запуска Telegram бота: {e}")

if __name__ == "__main__":
    # Запускаем Flask сервер в главном потоке (Render увидит порт)
    # Telegram бот запускается в отдельном потоке
    
    # Создаем поток для Telegram бота
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask в главном потоке (это важно для Render)
    run_flask_server()