# -*- coding: utf-8 -*-
"""
Umka men СӨЙЛЕ — Telegram-бот
Функции:
1. /start — приветствие с ценой + мгновенная выдача лид-магнита (PDF) + кнопки Оплаты и Оферты
2. Ежедневная drip-рассылка с кнопкой оплаты на каждый день
3. Выбор уровня A1-A2/B1, ссылка на оферту и сбор заявки/оплаты на курс
4. /stats — статистика пользователей (только для админа ID: 720532587)

Запуск: python3 bot.py
Требуется переменная окружения BOT_TOKEN (токен от @BotFather)
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
LEADMAGNET_PATH = os.path.join(os.path.dirname(__file__), "20_phrases_leadmagnet.pdf")

# ADMIN TELEGRAM ID
ADMIN_ID = 720532587

# ССЫЛКИ НА ОФЕРТУ И ОПЛАТУ
OFERTA_URL = "https://docs.google.com/document/d/1S7fn8GOsMarOyeEOa54TM_Eu63cKLy9b5qIXUkGGMPc/edit?usp=sharing"
PAYMENT_URL = "https://pay.kaspi.kz/pay/3t1bdvs4"

# ЦЕНА КУРСА — меняешь один раз здесь, обновится везде в боте
COURSE_PRICE = "24 990 ₸"

# ---------- БАЗА ДАННЫХ ----------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            joined_at TEXT,
            drip_day INTEGER DEFAULT 0,
            level TEXT,
            name TEXT,
            phone TEXT,
            registered INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def upsert_user(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM users WHERE chat_id=?", (chat_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (chat_id, joined_at, drip_day) VALUES (?, ?, 0)",
            (chat_id, datetime.utcnow().isoformat()),
        )
        conn.commit()
    conn.close()


def set_level(chat_id, level):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET level=? WHERE chat_id=?", (level, chat_id))
    conn.commit()
    conn.close()


def set_contact(chat_id, name=None, phone=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if name is not None:
        c.execute("UPDATE users SET name=? WHERE chat_id=?", (name, chat_id))
    if phone is not None:
        c.execute("UPDATE users SET phone=?, registered=1 WHERE chat_id=?", (phone, chat_id))
    conn.commit()
    conn.close()


def get_all_users_for_drip():
    """Пользователи, кому пора отправить следующее сообщение цепочки."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id, joined_at, drip_day, registered FROM users WHERE registered=0")
    rows = c.fetchall()
    conn.close()
    return rows


def bump_drip_day(chat_id, day):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET drip_day=? WHERE chat_id=?", (day, chat_id))
    conn.commit()
    conn.close()


def get_user_stats():
    """Статистика для админа."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE level IS NOT NULL")
    with_level = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE registered=1 OR phone IS NOT NULL")
    registered = c.fetchone()[0]

    conn.close()
    return total, with_level, registered


# ---------- ТЕКСТЫ DRIP-ЦЕПОЧКИ (по дням после /start) ----------

DRIP_MESSAGES = {
    1: (
        "Кеше гайдты алдың ба? 🙂\n\n"
        "Айтпақшы, байқадың ба — грамматиканы білу мен сөйлей алу екі бөлек нәрсе екенін?\n\n"
        "Көбіміз мектепте, университетте жылдар бойы ережелерді жаттаймыз. Бірақ "
        "нағыз әңгімеге тап болғанда — сөз таппай, үнсіз қаламыз.\n\n"
        f"Клубқа қосылып, сөйлеуді бүгін бастауға болады — {COURSE_PRICE} 👇"
    ),
    2: (
        "Білесің бе, тіпті ағылшын тілі мұғалімдерінің өзі көбіне носительмен "
        "сөйлеуден қорқады.\n\n"
        "Себебі — оларды да аударуға үйреткен, сөйлеуге емес.\n\n"
        "Мәселе сенде емес. Мәселе — практиканың жоқтығында.\n\n"
        f"Орныңды {COURSE_PRICE}-ге бекіту үшін төмендегі батырманы бас 👇"
    ),
    3: (
        "Соңғы бір апта ішінде маған көп адам жазды: \"қалайша тынымсыз үйреніп жүріп, "
        "сөйлей алмаймын?\"\n\n"
        "Сондықтан бір шешім дайындадым — грамматика + тірі сөйлеу практикасын "
        "біріктірген формат.\n\n"
        f"Орынды қазір {COURSE_PRICE}-ге бекітуге болады 👇"
    ),
    4: (
        "Таныстырамын: <b>Umka men СӨЙЛЕ</b> клубы.\n\n"
        "✅ Күнделікті грамматика — Telegram-чатта\n"
        "✅ Аптасына 2 рет тірі Speaking Club — Google Meet\n"
        "✅ A1-A2 деңгейі — қазақ мұғалімімен, өз тіліңде қолдау\n"
        "✅ B1 деңгейі — шетелдік мұғаліммен, нағыз практика\n"
        f"💰 Бағасы: {COURSE_PRICE} / айына\n\n"
        "Клубқа қосылу үшін төлемді қазір жасай аласыз 👇"
    ),
    5: (
        "Клубқа қосылғандар не дейді:\n\n"
        "\"Алғаш рет носительмен 5 минут үзіліссіз сөйлестім — бұрын мұндай болған "
        "емес еді\" — қатысушыдан пікір\n\n"
        "Орындар мұғалімнің кестесіне байланысты шектеулі. Топтар толықса, "
        "келесі айға дейін күту керек болады.\n\n"
        f"Қатысуды {COURSE_PRICE}-ге бекіту 👇"
    ),
    6: (
        "Соңғы күн еске салу 🔔\n\n"
        f"<b>Umka men СӨЙЛЕ</b> — {COURSE_PRICE} / айына\n"
        "Күнделікті грамматика + 8 тірі speaking club кездесуі\n\n"
        "Орныңды қазір бекіт — төменде батырманы бас 👇"
    ),
}

FINAL_CTA_TEXT = "Орынды қазір бекіту үшін деңгейіңді таңдаңыз немесе төлем жасаңыз:"


# ---------- КЛАВИАТУРЫ ----------

def level_keyboard():
    keyboard = [
        [InlineKeyboardButton("A1-A2", callback_data="level_A1")],
        [InlineKeyboardButton("B1 — сөйлей аламын, практика керек", callback_data="level_B1")],
        [InlineKeyboardButton(f"💳 {COURSE_PRICE} — Tөлем жасау (Kaspi Pay)", url=PAYMENT_URL)],
        [InlineKeyboardButton("📄 Жария оферта", url=OFERTA_URL)],
    ]
    return InlineKeyboardMarkup(keyboard)


def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton(f"💳 {COURSE_PRICE} — Tөлем жасау (Kaspi Pay)", url=PAYMENT_URL)],
        [InlineKeyboardButton("📄 Жария оферта шарты", url=OFERTA_URL)],
    ]
    return InlineKeyboardMarkup(keyboard)


def contact_keyboard():
    keyboard = [[KeyboardButton("📱 Нөмірімді жіберу", request_contact=True)]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


# ---------- ХЕНДЛЕРЫ ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    welcome = (
        "Сәлем! 👋 Umka men СӨЙЛЕ клубына қош келдің.\n\n"
        "<b>«20 фраза» гайдыңды жүктеп ал! 🎁</b>\n\n"
        "⚡️ <b>Маңызды:</b> Хабарландыруларды (уведомления) өшірме!\n"
        "Күнделікті саған <b>1 минуттық микро-пайдалы материалдар</b> жіберіп отырамын:\n"
        "• 🎙 Дұрыс дыбыстау мен айтылым сырлары (произношение)\n"
        "• 💡 Формуласыз, жеңіл грамматика\n"
        "• 🗣 Носительдердің шынайы өмірде қолданатын фразалары\n\n"
        f"📚 <b>Umka men СӨЙЛЕ</b> клубы — {COURSE_PRICE} / айына. Күнделікті "
        "грамматика + аптасына 2 рет тірі Speaking Club (A1-A2 немесе B1 деңгейінде).\n\n"
        "Эфирдеміз! Келесі микро-сабақ ертең дәл осы уақытта келеді. Keep in touch! 🚀"
    )
    await update.message.reply_text(welcome, parse_mode="HTML")

    if os.path.exists(LEADMAGNET_PATH):
        with open(LEADMAGNET_PATH, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="20_phrases.pdf",
                caption="Міне, гайдың дайын 🎁",
            )
    else:
        await update.message.reply_text("(гайд файлы табылмады, кейінірек жіберемін)")

    await update.message.reply_text(
        "Деңгейіңді таңда немесе төлемді қазір жаса:",
        reply_markup=level_keyboard(),
    )


async def level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    level = "A1" if query.data == "level_A1" else "B1"
    set_level(chat_id, level)

    if level == "A1":
        reply = (
            "Түсінікті! A1-A2 деңгейінде — қазақ мұғалімімен, өз тіліңде қолдау "
            "алып, қорықпай жаттығасың. 💪"
        )
    else:
        reply = (
            "Керемет! B1 деңгейінде — шетелдік мұғаліммен нағыз тірі практика "
            "аласың. 🌍"
        )

    course_info = (
        "📚 <b>Umka men СӨЙЛЕ — қысқаша</b>\n\n"
        "✅ Күнделікті грамматика — Telegram-чатта\n"
        "✅ Аптасына 2 рет тірі Speaking Club\n"
        f"✅ Сенің деңгейің: <b>{level}</b>\n"
        f"💰 Бағасы: {COURSE_PRICE} / айына\n\n"
        "Төлемді немесе офертаны төмендегі батырмалардан аша аласың:"
    )

    await query.edit_message_text(reply)
    await context.bot.send_message(
        chat_id, course_info, parse_mode="HTML", reply_markup=main_menu_keyboard()
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats — статистика только для админа"""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    total, with_level, registered = get_user_stats()
    text = (
        "📊 Статистика бота:\n\n"
        f"👤 Всего зашли в бот: {total}\n"
        f"🎯 Выбрали уровень (A1-A2/B1): {with_level}\n"
        f"📱 Оставили контакты / заявку: {registered}"
    )
    await update.message.reply_text(text)


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/join — начать оформление заявки на курс (текстом, запасной вариант)"""
    await update.message.reply_text(
        "Тамаша! Орынды бекіту үшін атыңды жаз (тек аты жеткілікті):",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data["awaiting_name"] = True


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if context.user_data.get("awaiting_name"):
        name = update.message.text.strip()
        set_contact(chat_id, name=name)
        context.user_data["awaiting_name"] = False
        await update.message.reply_text(
            f"Рахмет, {name}! Енді нөміріңді жібер — батырманы бас немесе қолмен жаз:",
            reply_markup=contact_keyboard(),
        )
        return

    await update.message.reply_text(
        "Хабарламаңды алдым! Сұрағың болса, тікелей осында жаз — жауап беремін 🙂"
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    contact = update.message.contact
    phone = contact.phone_number
    set_contact(chat_id, phone=phone)
    await update.message.reply_text(
        "Тіркелдің! ✅ Жақын арада саған топ пен сабақ кестесі туралы жеке "
        "жазамын. Қош келдің!",
        reply_markup=ReplyKeyboardRemove(),
    )


# ---------- ПЛАНИРОВЩИК (ежедневная drip-рассылка) ----------

async def send_daily_drip(app: Application):
    """Раз в день рассылает следующее сообщение цепочки с кнопкой оплаты."""
    users = get_all_users_for_drip()
    now = datetime.utcnow()

    for chat_id, joined_at_str, drip_day, registered in users:
        joined_at = datetime.fromisoformat(joined_at_str)
        days_passed = (now - joined_at).days

        next_day = drip_day + 1
        if days_passed >= next_day and next_day in DRIP_MESSAGES:
            try:
                text = DRIP_MESSAGES[next_day]
                await app.bot.send_message(
                    chat_id, text, parse_mode="HTML", reply_markup=level_keyboard()
                )
                bump_drip_day(chat_id, next_day)
                logger.info(f"Отправлено сообщение дня {next_day} пользователю {chat_id}")
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение {chat_id}: {e}")


# ---------- ЗАПУСК ----------

def main():
    init_db()

    if BOT_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        print("⚠ Сначала укажи токен бота в переменной окружения BOT_TOKEN")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("join", register_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(level_callback, pattern="^level_"))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    scheduler = AsyncIOScheduler()
    # Ежедневная рассылка в 11:00 по времени сервера — поменяй час при необходимости
    scheduler.add_job(send_daily_drip, "cron", hour=11, minute=0, args=[app])
    scheduler.start()

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
