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

@app.route("/health")
def health():
    return "OK", 200

@app.route("/ping")
def ping():
    return "pong", 200

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

    # ВАЖНО: создаем словарь для перевода
    ru = {
        "monday": "Понедельник",
        "tuesday": "Вторник", 
        "wednesday": "Среда",
        "thursday": "Четверг",
        "friday": "Пятница",
        "saturday": "Суббота",
        "sunday": "Воскресенье"
    }

    if text == "расписание на сегодня":
        d = ru[datetime.now().strftime("%A").lower()]
        await update.message.reply_text(format_schedule_day(sched, d))
        return

    if text == "расписание на завтра":
        d = ru[(datetime.now() + timedelta(days=1)).strftime("%A").lower()]
        await update.message.reply_text(format_schedule_day(sched, d))
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
        return
        
    # Если текст не распознан
    await update.message.reply_text(
        "Используйте меню для навигации",
        reply_markup=get_menu()
    )

async def notifications(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    current_time = now.strftime("%H:%M")
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

# ============= ЗАПУСК ВСЕГО =============

def run_flask_server():
    """Запуск Flask сервера для Render health check"""
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🌐 Flask сервер запущен на порту {port}")
    # Важно: use_reloader=False для избежания двойного запуска
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def run_telegram_bot():
    """Запуск Telegram бота с Webhook"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Создаем и настраиваем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_cmd))
        application.add_handler(MessageHandler(filters.TEXT, handle))
        
        application.job_queue.run_repeating(notifications, interval=30, first=10)
        
        logging.info("🤖 Telegram Bot запускается с Webhook...")
        
        # ЗАПУСКАЕМ БОТА В ЭТОМ ПОТОКЕ
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(application.start())
        
        # 1. Получаем порт из переменных окружения Render
        port = int(os.environ.get("PORT", 10000))
        
        # 2. Получаем публичный URL вашего приложения
        # На Render это обычно: https://your-app-name.onrender.com
        # Нужно установить переменную окружения RENDER_EXTERNAL_URL
        webhook_url = os.environ.get("RENDER_EXTERNAL_URL")
        
        if not webhook_url:
            # Если переменной нет, можно сгенерировать из имени приложения
            render_service_name = os.environ.get("RENDER_SERVICE_NAME", "")
            if render_service_name:
                webhook_url = f"https://{render_service_name}.onrender.com"
            else:
                # Fallback: для локального тестирования
                webhook_url = f"https://example.com"  # Нужно заменить на реальный
        
        # 3. Настраиваем Webhook
        webhook_path = "/webhook"  # Путь для webhook
        full_webhook_url = f"{webhook_url}{webhook_path}"
        
        logging.info(f"🌐 Настраиваю Webhook: {full_webhook_url}")
        
        # 4. Запускаем Webhook
        loop.run_until_complete(
            application.bot.set_webhook(
                url=full_webhook_url,
                secret_token="YOUR_SECRET_TOKEN"  # Опционально для безопасности
            )
        )
        
        # 5. Запускаем Flask в ЭТОМ ЖЕ ПОТОКЕ (важно!)
        from flask import request
        
        @app.route(webhook_path, methods=['POST'])
        async def webhook():
            """Обработчик webhook от Telegram"""
            if request.headers.get('content-type') == 'application/json':
                json_string = await request.get_data()
                update = Update.de_json(json.loads(json_string), application.bot)
                await application.process_update(update)
            return '', 200
        
        @app.route("/check-notifications")
        def check_notifications():
            """Старый endpoint для уведомлений - оставляем для UptimeRobot"""
            # ... ваш существующий код ...
            pass
        
        logging.info(f"✅ Telegram Bot готов! Webhook настроен на {full_webhook_url}")
        logging.info(f"📡 Сервер запускается на порту {port}")
        
        # 6. Запускаем Flask (он будет обрабатывать и webhook, и health checks)
        # Удаляем use_reloader, так как он создает дополнительные процессы
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        
    except Exception as e:
        logging.error(f"❌ Ошибка запуска Telegram бота: {e}")

if __name__ == "__main__":
    run_telegram_bot()