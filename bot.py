import os
import json
import logging
import asyncio
import urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv
import signal
import sys

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

# ============= ОБЩИЕ ФУНКЦИИ =============

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

# ============= ФУНКЦИИ ФОРМАТИРОВАНИЯ РАСПИСАНИЯ =============

def format_schedule_day(schedules, day):
    """day: русское название дня ('Понедельник', 'Вторник' и т.д.)"""
    current_week = get_current_week()
    
    # Словарь для перевода русского названия в английский ключ
    ru_to_en = {
        "Понедельник": "monday",
        "Вторник": "tuesday", 
        "Среда": "wednesday",
        "Четверг": "thursday",
        "Пятница": "friday",
        "Саббота": "saturday",
        "Суббота": "saturday",  # Два варианта на случай опечаток
        "Воскресенье": "sunday"
    }
    
    # Получаем английский ключ
    en_day_key = ru_to_en.get(day)
    if not en_day_key:
        return f"Ошибка: день '{day}' не найден"
    
    lessons = schedules.get(en_day_key, [])
    
    if not lessons:
        return f"{day}: занятий нет"
    
    # ФИЛЬТРАЦИЯ по текущей неделе
    filtered_lessons = []
    for lesson in lessons:
        weeks = lesson.get("weekNumber")
        
        if weeks is None:
            filtered_lessons.append(lesson)
            continue
        
        if isinstance(weeks, list):
            # Преобразуем все элементы в int
            week_numbers = []
            for w in weeks:
                try:
                    week_numbers.append(int(w))
                except:
                    continue
            
            if current_week in week_numbers:
                filtered_lessons.append(lesson)
        
        elif isinstance(weeks, int):
            if weeks == current_week:
                filtered_lessons.append(lesson)
        
        elif isinstance(weeks, str):
            try:
                week_num = int(weeks)
                if week_num == current_week:
                    filtered_lessons.append(lesson)
            except ValueError:
                filtered_lessons.append(lesson)
    
    if not filtered_lessons:
        return f"{day}: нет занятий на этой неделе"
    
    text = f"расписание на {day}"
    if current_week:
        text += f" (неделя {current_week})"
    text += ":\n\n"
    
    for lesson in filtered_lessons:
        text += (
            f"{lesson['startLessonTime']} - {lesson['endLessonTime']} | "
            f"{lesson['subject']} | "
            f"{', '.join(lesson.get('auditories', []))}\n"
        )
    return text

def format_schedule_week(schedules):
    current_week = get_current_week()
    
    text = "расписание на неделю"
    if current_week:
        text += f" (неделя {current_week})"
    text += ":\n\n"
    
    # Словарь для перевода английских ключей в русские названия
    ru_days = {
        "monday": "Понедельник",
        "tuesday": "Вторник", 
        "wednesday": "Среда",
        "thursday": "Четверг",
        "friday": "Пятница",
        "saturday": "Суббота",
        "sunday": "Воскресенье"
    }
    
    # Правильный порядок дней недели
    days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    
    for day_key in days_order:
        ru_day = ru_days.get(day_key, day_key)
        lessons = schedules.get(day_key, [])
        
        text += f"{ru_day}:\n"
        
        if not lessons:
            text += "  нет занятий\n\n"
            continue
        
        # ФИЛЬТРАЦИЯ по текущей неделе
        filtered_lessons = []
        for lesson in lessons:
            weeks = lesson.get("weekNumber")
            
            if weeks is None:
                filtered_lessons.append(lesson)
                continue
            
            if isinstance(weeks, list):
                week_numbers = []
                for w in weeks:
                    try:
                        week_numbers.append(int(w))
                    except:
                        continue
                
                if current_week in week_numbers:
                    filtered_lessons.append(lesson)
            
            elif isinstance(weeks, int):
                if weeks == current_week:
                    filtered_lessons.append(lesson)
            
            elif isinstance(weeks, str):
                try:
                    week_num = int(weeks)
                    if week_num == current_week:
                        filtered_lessons.append(lesson)
                except ValueError:
                    filtered_lessons.append(lesson)
        
        if not filtered_lessons:
            text += "  нет занятий на этой неделе\n\n"
            continue
        
        # Сортируем по времени
        filtered_lessons.sort(key=lambda x: x.get('startLessonTime', '00:00'))
        
        for lesson in filtered_lessons:
            text += (
                f"  {lesson['startLessonTime']} - {lesson['endLessonTime']} | "
                f"{lesson['subject']} | "
                f"{', '.join(lesson.get('auditories', []))}\n"
            )
        text += "\n"
    
    return text

# ============= ОБРАБОТЧИКИ ТЕЛЕГРАМ БОТА =============

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
    now = datetime.now()
    current_weekday = now.strftime("%A").lower()

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

# ============= FLASK APP И WEBHOOK =============

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

# ============= ОСНОВНОЙ ЗАПУСК =============

def signal_handler(sig, frame):
    """Обработчик сигналов для корректного завершения"""
    print("\n🚪 Корректное завершение работы...")
    sys.exit(0)

def run_telegram_bot():
    """Запуск Telegram бота"""
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_cmd))
        app.add_handler(MessageHandler(filters.TEXT, handle))
        
        app.job_queue.run_repeating(notifications, interval=30, first=10)
        
        logging.info("🤖 Telegram Bot запускается...")
        
        # Запускаем polling с настройками для стабильности
        app.run_polling(
            drop_pending_updates=True,
            close_loop=False,
            stop_signals=None,  # Не реагировать на сигналы остановки
            allowed_updates=Update.ALL_TYPES
        )
        
    except KeyboardInterrupt:
        logging.info("Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"❌ Ошибка запуска Telegram бота: {e}")
        import traceback
        traceback.print_exc()

def run_flask_server():
    """Запуск Flask сервера"""
    port = int(os.environ.get("PORT", 10000))
    
    # Настройка обработки ошибок для Flask
    import werkzeug
    werkzeug.serving.log.setLevel(logging.ERROR)
    
    logging.info(f"🌐 Flask сервер запущен на порту {port}")
    
    # Запускаем Flask с минимальными настройками для Render
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,  # КРИТИЧЕСКИ ВАЖНО: отключаем релоадер
        threaded=True,
        passthrough_errors=True
    )

if __name__ == "__main__":
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    import threading
    
    # Получаем порт
    port = int(os.environ.get("PORT", 10000))
    
    print("=" * 50)
    print(f"🚀 Запуск приложения на порту {port}")
    print("=" * 50)
    
    # Запускаем Telegram бота в отдельном потоке
    bot_thread = threading.Thread(
        target=run_telegram_bot,
        daemon=True,  # Демонизируем поток - он завершится при завершении main
        name="TelegramBotThread"
    )
    bot_thread.start()
    
    # Даем боту время на инициализацию
    import time
    time.sleep(2)
    
    # Запускаем Flask в главном потоке (это важно для Render!)
    run_flask_server()