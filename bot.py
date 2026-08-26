# -*- coding: utf-8 -*-
"""
Umka men СӨЙЛЕ — Telegram-бот
Функции:
1. /start [soyle|phrases] — приветствие с авто-определением лид-магнита (10 техник / 20 фраз)
2. Ежедневная drip-рассылка с кнопкой оплаты на каждый день
3. Выбор уровня A1-A2/B1, ссылка на оферту и сбор заявки/оплаты на курс
4. /stats — статистика пользователей (только для админа ID: 720532587)
5. Выдача PDF-гайда "Mastering B2 & C1 Grammar" по ключевым словам
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")

# =========================================================
# ОКОНЧАТЕЛЬНЫЙ ПУТЬ К БАЗЕ ДАННЫХ (Persistent Volume Railway)
# =========================================================
DB_PATH = "/data/users.db"

# ЛИД-МАГНИТТЕР ЖОЛЫ
LEADMAGNET_10_TECHNIQUES = os.path.join(
    os.path.dirname(__file__), "10_techniques_speaking_english_v3.pdf"
)
LEADMAGNET_20_PHRASES = os.path.join(
    os.path.dirname(__file__), "20_phrases_leadmagnet.pdf"
)
LEADMAGNET_B2_C1 = os.path.join(
    os.path.dirname(__file__), "Umka_Mastering_B2_C1_Grammar.pdf"
)

# ADMIN TELEGRAM ID
ADMIN_ID = 720532587

# ССЫЛКИ НА ОФЕРТУ И ОПЛАТУ
OFERTA_URL = "https://docs.google.com/document/d/1S7fn8GOsMarOyeEOa54TM_Eu63cKLy9b5qIXUkGGMPc/edit?usp=sharing"
PAYMENT_URL = "https://pay.kaspi.kz/pay/3t1bdvs4"

# ЦЕНА КУРСА
COURSE_PRICE = "24 990 ₸"

# КІЛТ СӨЗДЕР ТІЗІМІ (B2/C1 ГАЙДЫ ҮШІН)
KEYWORDS_B2_C1 = ["гайд", "b2", "c1", "грамматика", "grammar", "guide", "мастеринг"]

# B2/C1 ТЕКСТІК РЕЗЕРВІ (ФАЙЛ СЕРВЕРДЕ ТАБЫЛМАЙ ҚАЛСА)
B2_C1_TEXT = (
    "✨ <b>MASTERING B2 & C1: Ағылшын тіліндегі 5 күрделі грамматикалық конструкция</b>\n\n"
    "1️⃣ <b>Inversion (Сөз кезегін төңкеру)</b>\n"
    "❌ <i>Hardly I had entered the room when the phone rang.</i>\n"
    "✅ <b>Hardly had I entered the room when the phone rang.</b>\n"
    "<i>(Бөлмеге кіре бергенім сол еді, телефон шырылдап қоя берді.)</i>\n\n"
    "2️⃣ <b>Mixed Conditionals (Аралас шартты сөйлемдер)</b>\n"
    "❌ <i>If I studied harder, I would have a good job now.</i>\n"
    "✅ <b>If I had studied harder at university, I would have a good job now.</b>\n"
    "<i>(Егер университетте жақсырақ оқығанымда, қазір жақсы жұмысым болар еді.)</i>\n\n"
    "3️⃣ <b>Perfect Passive Participle</b>\n"
    "❌ <i>After the car was repaired, we left.</i>\n"
    "✅ <b>Having been repaired, the car was ready for the trip.</b>\n"
    "<i>(Көлік жөнделіп болған соң, жолға дайын болды.)</i>\n\n"
    "4️⃣ <b>Subjunctive Mood (Пәрменді/тілек рай)</b>\n"
    "❌ <i>She insisted that he goes with her.</i>\n"
    "✅ <b>She insisted that he go with her.</b>\n"
    "<i>(Ол оның өзімен бірге баруын талап етті.)</i>\n\n"
    "5️⃣ <b>Cleft Sentences (Ойды бөліп көрсету)</b>\n"
    "❌ <i>I just need some rest.</i>\n"
    "✅ <b>What I really need is some rest.</b>\n"
    "<i>(Маған қазір шын мәнінде керегі — сәл демалыс.)</i>\n\n"
    "© 2026 Umka men СӨЙЛЕ"
)


# ---------- БАЗА ДАННЫХ ----------


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
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
        c.execute(
            "UPDATE users SET phone=?, registered=1 WHERE chat_id=?",
            (phone, chat_id),
        )
    conn.commit()
    conn.close()


def get_all_users_for_drip():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT chat_id, joined_at, drip_day, registered FROM users WHERE"
        " registered=0"
    )
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE level IS NOT NULL")
    with_level = c.fetchone()[0]

    c.execute(
        "SELECT COUNT(*) FROM users WHERE registered=1 OR phone IS NOT NULL"
    )
    registered = c.fetchone()[0]

    conn.close()
    return total, with_level, registered


# ---------- ТЕКСТЫ DRIP-ЦЕПОЧКИ ----------

DRIP_MESSAGES = {
    1: (
        "Кеше гайдты алдың ба? 🙂\n\nАйтпақшы, байқадың ба — грамматиканы білу"
        " мен сөйлей алу екі бөлек нәрсе екенін?\n\nКөбіміз мектепте,"
        " университетте жылдар бойы ережелерді жаттаймыз. Бірақ нағыз әңгімеге"
        " тап болғанда — сөз таппай, үнсіз қаламыз.\n\nКлубқа қосылып, сөйлеуді"
        f" бүгін бастауға болады — {COURSE_PRICE} 👇"
    ),
    2: (
        "Білесің бе, тіпті ағылшын тілі мұғалімдерінің өзі көбіне"
        " носительмен сөйлеуден қорқады.\n\nСебебі — оларды да аударуға"
        " үйреткен, сөйлеуге емес.\n\nМәселе сенде емес. Мәселе — практиканың"
        f" жоқтығында.\n\nОрныңды {COURSE_PRICE}-ге бекіту үшін төмендегі"
        " батырманы бас 👇"
    ),
    3: (
        "Соңғы бір апта ішінде маған көп адам жазды: \"қалайша тынымсыз үйреніп"
        ' жүріп, сөйлей алмаймын?"\n\nСондықтан бір шешім дайындадым —'
        " грамматика + тірі сөйлеу практикасын біріктірген формат.\n\nОрынды"
        f" қазір {COURSE_PRICE}-ге бекітуге болады 👇"
    ),
    4: (
        "Таныстырамын: <b>Umka men СӨЙЛЕ</b> клубы.\n\n✅ Күнделікті грамматика"
        " — Telegram-чатта\n✅ Аптасына 2 рет тірі Speaking Club — Google"
        " Meet\n✅ A1-A2 деңгейі — қазақ мұғалімімен, өз тіліңде қолдау\n✅ B1"
        " деңгейі — шетелдік мұғаліммен, нағыз практика\n💰 Бағасы:"
        f" {COURSE_PRICE} / айына\n\nКлубқа қосылу үшін төлемді қазір жасай"
        " аласыз 👇"
    ),
    5: (
        "Клубқа қосылғандар не дейді:\n\n\"Алғаш рет носительмен 5 минут"
        " үзіліссіз сөйлестім — бұрын мұндай болған емес еді\" — қатысушыдан"
        " пікір\n\nОрындар мұғалімнің кестесіне байланысты шектеулі. Топтар"
        " толықса, келесі айға дейін күту керек болады.\n\nҚатысуды"
        f" {COURSE_PRICE}-ге бекіту 👇"
    ),
    6: (
        "Соңғы күн еске салу 🔔\n\n<b>Umka men СӨЙЛЕ</b> —"
        f" {COURSE_PRICE} / айына\nКүнделікті грамматика + 8 тірі speaking club"
        " кездесуі\n\nОрныңды қазір бекіт — төменде батырманы бас 👇"
    ),
}


# ---------- КЛАВИАТУРЫ ----------


def level_keyboard():
    keyboard = [
        [InlineKeyboardButton("A1-A2", callback_data="level_A1")],
        [
            InlineKeyboardButton(
                "B1 — сөйлей аламын, практика керек", callback_data="level_B1"
            )
        ],
        [
            InlineKeyboardButton(
                f"💳 {COURSE_PRICE} — Tөлем жасау (Kaspi Pay)", url=PAYMENT_URL
            )
        ],
        [InlineKeyboardButton("📄 Жария оферта", url=OFERTA_URL)],
    ]
    return InlineKeyboardMarkup(keyboard)


def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                f"💳 {COURSE_PRICE} — Tөлем жасау (Kaspi Pay)", url=PAYMENT_URL
            )
        ],
        [InlineKeyboardButton("📄 Жария оферта шарты", url=OFERTA_URL)],
    ]
    return InlineKeyboardMarkup(keyboard)


def contact_keyboard():
    keyboard = [[KeyboardButton("📱 Нөмірімді жіберу", request_contact=True)]]
    return ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=True
    )


# ---------- ХЕНДЛЕРЫ ----------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    args = context.args
    key = args[0].lower() if args else "soyle"

    if key == "soyle":
        welcome = (
            "Сәлем! 👋 Umka men СӨЙЛЕ клубына қош келдің.\n\n"
            "<b>«10 тиімді техника» гайдыңды жүктеп ал! 🎁</b>\n\n"
            "⚡️ <b>Маңызды:</b> Хабарландыруларды өшірме!\n"
            "Күнделікті саған <b>1 минуттық микро-пайдалы материалдар</b> жіберіп"
            " отырамын:\n"
            "• 🎙 Дұрыс дыбыстау мен айтылым сырлары\n"
            "• 💡 Формуласыз, жеңіл грамматика\n"
            "• 🗣 Носительдердің шынайы өмірде қолданатын фразалары\n\n"
            f"📚 <b>Umka men СӨЙЛЕ</b> клубы — {COURSE_PRICE} / айына.\n\n"
            "Эфирдеміз! Келесі микро-сабақ ертең дәл осы уақытта келеді. Keep in"
            " touch! 🚀"
        )
        await update.message.reply_text(welcome, parse_mode="HTML")

        if os.path.exists(LEADMAGNET_10_TECHNIQUES):
            with open(LEADMAGNET_10_TECHNIQUES, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename="10_techniques_speaking_english.pdf",
                    caption=(
                        "«Ағылшынша тез сөйлеп кетудің 10 тиімді техникасы»"
                        " гайды 🎁"
                    ),
                )
        else:
            await update.message.reply_text("(гайд файлы табылмады)")

    elif key == "phrases":
        welcome = (
            "Сәлем! 👋 Umka men СӨЙЛЕ клубына қош келдің.\n\n"
            "<b>«20 пайдалы фраза» гайдыңды жүктеп ал! 🎁</b>\n\n"
            f"📚 <b>Umka men СӨЙЛЕ</b> клубы — {COURSE_PRICE} / айына.\n\n"
            "Эфирдеміз! Келесі микро-сабақ ертең келеді. Keep in touch! 🚀"
        )
        await update.message.reply_text(welcome, parse_mode="HTML")

        if os.path.exists(LEADMAGNET_20_PHRASES):
            with open(LEADMAGNET_20_PHRASES, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename="20_phrases_leadmagnet.pdf",
                    caption="«20 пайдалы фраза» гайды 🎁",
                )
        else:
            await update.message.reply_text("(гайд файлы табылмады)")

    else:
        welcome = (
            "Сәлем! 👋 Umka men СӨЙЛЕ клубына қош келдің.\n\n"
            f"📚 <b>Umka men СӨЙЛЕ</b> клубы — {COURSE_PRICE} / айына."
        )
        await update.message.reply_text(welcome, parse_mode="HTML")

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
            "Түсінікті! A1-A2 деңгейінде — қазақ мұғалімімен, өз тіліңде"
            " қолдау алып, қорықпай жаттығасың. 💪"
        )
    else:
        reply = (
            "Керемет! B1 деңгейінде — шетелдік мұғаліммен нағыз тірі"
            " практика аласың. 🌍"
        )

    course_info = (
        "📚 <b>Umka men СӨЙЛЕ — қысқаша</b>\n\n✅ Күнделікті грамматика —"
        " Telegram-чатта\n✅ Аптасына 2 рет тірі Speaking Club\n✅ Сенің"
        f" деңгейің: <b>{level}</b>\n💰 Бағасы: {COURSE_PRICE} / айына\n\nТөлемді"
        " немесе офертаны төмендегі батырмалардан аша аласың:"
    )

    await query.edit_message_text(reply)
    await context.bot.send_message(
        chat_id,
        course_info,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(
        "Тамаша! Орынды бекіту үшін атыңды жаз (тек аты жеткілікті):",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data["awaiting_name"] = True


async def text_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    text = update.message.text.strip().lower()

    # Пайдаланушы базада бар ма, тексереміз / сақтаймыз
    upsert_user(chat_id)

    # 1. Егер пайдаланушы есімін жазып жатса
    if context.user_data.get("awaiting_name"):
        name = update.message.text.strip()
        set_contact(chat_id, name=name)
        context.user_data["awaiting_name"] = False
        await update.message.reply_text(
            f"Рахмет, {name}! Енді нөміріңді жібер — батырманы бас немесе қолмен"
            " жаз:",
            reply_markup=contact_keyboard(),
        )
        return

    # 2. Кілт сөздерді тексеру (B2 / C1 Гайд)
    if any(keyword in text for keyword in KEYWORDS_B2_C1):
        if os.path.exists(LEADMAGNET_B2_C1):
            with open(LEADMAGNET_B2_C1, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="Umka_Mastering_B2_C1_Grammar.pdf",
                    caption="📘 <b>Mastering B2 & C1 Grammar</b> гайды! 🎁",
                    parse_mode="HTML",
                )
        else:
            await update.message.reply_text(B2_C1_TEXT, parse_mode="HTML")
        return

    # 3. Басқа әдепкі жауап
    await update.message.reply_text(
        "Хабарламаңды алдым! Сұрағың болса, тікелей осында жаз — жауап беремін"
        " 🙂"
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    contact = update.message.contact
    phone = contact.phone_number
    set_contact(chat_id, phone=phone)
    await update.message.reply_text(
        "Тіркелдің! ✅ Жақын арада саған топ пен сабақ кестесі туралы жеке"
        " жазамын. Қош келдің!",
        reply_markup=ReplyKeyboardRemove(),
    )


# ---------- ПЛАНИРОВЩИК ----------


async def send_daily_drip(app: Application):
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
                    chat_id,
                    text,
                    parse_mode="HTML",
                    reply_markup=level_keyboard(),
                )
                bump_drip_day(chat_id, next_day)
                logger.info(
                    f"Отправлено сообщение дня {next_day} пользователю {chat_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Не удалось отправить сообщение {chat_id}: {e}"
                )


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
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler)
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_drip, "cron", hour=11, minute=0, args=[app])
    scheduler.start()

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
