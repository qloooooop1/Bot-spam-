import asyncio
import logging
import os
import re
import sqlite3

from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

# ================== الإعدادات ==================
TOKEN = os.getenv("TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ================== قاعدة البيانات SQLite ==================
DB_FILE = "database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
                 chat_id INTEGER PRIMARY KEY,
                 protect_numbers INTEGER DEFAULT 1,
                 protect_links INTEGER DEFAULT 1,
                 ban_mode TEXT DEFAULT "immediate",
                 spam_count INTEGER DEFAULT 0,
                 notification_delete_minutes INTEGER DEFAULT 2,
                 notify_numbers INTEGER DEFAULT 1,
                 notify_links INTEGER DEFAULT 1,
                 notify_ban_mode INTEGER DEFAULT 1,
                 notify_delete_time INTEGER DEFAULT 1,
                 notify_mute INTEGER DEFAULT 1
                 )''')
    conn.commit()
    conn.close()
    logger.info("قاعدة البيانات جاهزة")

init_db()

def add_group(chat_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

def get_settings(chat_id: int) -> dict | None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT protect_numbers, protect_links, ban_mode, spam_count, notification_delete_minutes, notify_numbers, notify_links, notify_ban_mode, notify_delete_time, notify_mute FROM groups WHERE chat_id = ?", (chat_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "protect_numbers": bool(row[0]),
            "protect_links": bool(row[1]),
            "ban_mode": row[2],
            "spam_count": row[3],
            "notification_delete_minutes": row[4],
            "notify_numbers": bool(row[5]),
            "notify_links": bool(row[6]),
            "notify_ban_mode": bool(row[7]),
            "notify_delete_time": bool(row[8]),
            "notify_mute": bool(row[9])
        }
    return None

def update_setting(chat_id: int, key: str, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE groups SET {key} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()
    conn.close()

def increment_spam_count(chat_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE groups SET spam_count = spam_count + 1 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def get_all_groups() -> list:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM groups")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# ================== دوال الكشف عن السبام ==================
def normalize_digits(text: str) -> str:
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣۴۵۶７۸۹', '012345678901234567890123456789')
    return text.translate(trans)

PHONE_PATTERN = re.compile(r'(?:\+?966|00966|966|05|5|0)?(\d[\s\W_*/.-]*){8,12}', re.IGNORECASE)
PHONE_CONTEXT_PATTERN = re.compile(r'(?:اتصل|رقمي|واتس|هاتف|موبايل|mobile|phone|call|contact|whatsapp|واتساب|📞|☎️)[\s\W_*/]{0,10}(?:\+\d{1,4}[\s\W_*/.-]*\d{5,15}|\d{9,15})', re.IGNORECASE | re.UNICODE)
WHATSAPP_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:chat\.whatsapp\.com|wa\.me)/[^\s]*|\+\w{8,}', re.IGNORECASE)
TELEGRAM_INVITE_PATTERN = re.compile(r'(?:https?://)?t\.me/(?:joinchat/|[+])[\w-]{10,}', re.IGNORECASE)
TIKTOK_PATTERN = re.compile(r'(?:https?://)?(?:vm\.|www\.)?tiktok\.com/[^\s]*', re.IGNORECASE)
SHORT_LINK_PATTERN = re.compile(r'(?:https?://)?(bit\.ly|tinyurl\.com|goo\.gl|t\.co)/[^\s]*', re.IGNORECASE)

ALLOWED_DOMAINS = ["youtube.com", "youtu.be", "instagram.com", "instagr.am", "x.com", "twitter.com"]

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def is_banned(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("kicked", "banned", "left")
    except Exception:
        return True

def contains_spam(text: str) -> bool:
    if not text:
        return False

    normalized = normalize_digits(text)

    if PHONE_PATTERN.search(normalized):
        return True

    if PHONE_CONTEXT_PATTERN.search(normalized):
        return True

    if (WHATSAPP_INVITE_PATTERN.search(text) or TELEGRAM_INVITE_PATTERN.search(text) or TIKTOK_PATTERN.search(text) or SHORT_LINK_PATTERN.search(text)):
        return True

    urls = re.findall(r'https?://[^\s]+|www\.[^\s]+|[^\s]+\.[^\s]{2,}', text, re.IGNORECASE)
    for url in urls:
        clean_url = url.replace(' ', '').lower()
        if not any(domain in clean_url for domain in ALLOWED_DOMAINS):
            return True

    has_phone = bool(PHONE_PATTERN.search(normalized))
    has_link = bool(re.search(r'https?://|www\.|[^\s]+\.[^\s/]+', text, re.IGNORECASE))
    if has_phone and has_link:
        return True

    return False

# ================== لوحة الإعدادات ==================
async def get_admin_panel(chat_id: int, user_id: int) -> (str, InlineKeyboardMarkup):
    settings = get_settings(chat_id)
    if not settings:
        return None, None

    delete_options = {0: "عدم الحذف", 1: "1 دقيقة", 2: "2 دقيقة", 3: "3 دقائق", 5: "5 دقائق", 10: "10 دقائق"}
    current_delete = delete_options.get(settings["notification_delete_minutes"], "غير محدد")

    text = (
        f"🛡️ <b>لوحة التحكم - الحارس الأمني</b>\n\n"
        f"📊 <b>إحصائيات:</b>\n"
        f"• عدد السبام المكتشف: {settings['spam_count']}\n\n"
        f"⚙️ <b>إعدادات الحماية:</b>\n"
        f"• حماية الأرقام: {'مفعلة ✅' if settings['protect_numbers'] else 'معطلة ❌'} (كشف وحظر الأرقام الهواتف).\n"
        f"• حماية الروابط: {'مفعلة ✅' if settings['protect_links'] else 'معطلة ❌'} (كشف وحظر الروابط المشبوهة).\n"
        f"• وضع الحظر: {'فوري 🚫' if settings['ban_mode'] else 'لين ⚠️'} (فوري = حظر مباشر، لين = تحذير ثم حظر).\n"
        f"• مدة حذف الإشعار: {current_delete} (بعد كم دقيقة يحذف الإشعار).\n\n"
        f"🔔 <b>إعدادات الإشعارات:</b>\n"
        f"• إشعار حماية الأرقام: {'مفعل ✅' if settings['notify_numbers'] else 'معطل ❌'}\n"
        f"• إشعار حماية الروابط: {'مفعل ✅' if settings['notify_links'] else 'معطل ❌'}\n"
        f"• إشعار وضع الحظر: {'مفعل ✅' if settings['notify_ban_mode'] else 'معطل ❌'}\n"
        f"• إشعار مدة الحذف: {'مفعل ✅' if settings['notify_delete_time'] else 'معطل ❌'}\n"
        f"• إشعار الكتم: {'مفعل ✅' if settings['notify_mute'] else 'معطل ❌'} (إشعار عند كتم عضو في وضع لين).\n"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"حماية الأرقام {'إيقاف' if settings['protect_numbers'] else 'تفعيل'}", callback_data=f"toggle_numbers_{chat_id}")],
        [InlineKeyboardButton(text=f"حماية الروابط {'إيقاف' if settings['protect_links'] else 'تفعيل'}", callback_data=f"toggle_links_{chat_id}")],
        [InlineKeyboardButton(text=f"وضع الحظر {'لين' if settings['ban_mode'] == 'immediate' else 'فوري'}", callback_data=f"toggle_mode_{chat_id}")],
        [InlineKeyboardButton(text="⏱ مدة حذف الإشعار ▼", callback_data=f"delete_menu_{chat_id}")],
        [InlineKeyboardButton(text="🔔 إعدادات الإشعارات ▼", callback_data=f"notify_menu_{chat_id}")],
        [InlineKeyboardButton(text="🔄 تحديث اللوحة", callback_data=f"refresh_{chat_id}")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="back_to_main")]
    ])

    return text, keyboard

# قائمة مدة الحذف
async def get_delete_menu(chat_id: int) -> (str, InlineKeyboardMarkup):
    settings = get_settings(chat_id)
    current = settings["notification_delete_minutes"]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'✅ ' if current == 0 else ''}عدم الحذف", callback_data=f"set_delete_{chat_id}_0")],
        [InlineKeyboardButton(text=f"{'✅ ' if current == 1 else ''}1 دقيقة", callback_data=f"set_delete_{chat_id}_1")],
        [InlineKeyboardButton(text=f"{'✅ ' if current == 2 else ''}2 دقيقة", callback_data=f"set_delete_{chat_id}_2")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"refresh_{chat_id}")]
    ])

    return "⏱ اختر مدة حذف الإشعار:", keyboard

# قائمة إعدادات الإشعارات
async def get_notify_menu(chat_id: int) -> (str, InlineKeyboardMarkup):
    settings = get_settings(chat_id)

    text = (
        "🔔 <b>إعدادات الإشعارات:</b>\n\n"
        f"• حماية الأرقام: {'مفعل ✅' if settings['notify_numbers'] else 'معطل ❌'}\n"
        f"• حماية الروابط: {'مفعل ✅' if settings['notify_links'] else 'معطل ❌'}\n"
        f"• وضع الحظر: {'مفعل ✅' if settings['notify_ban_mode'] else 'معطل ❌'}\n"
        f"• مدة الحذف: {'مفعل ✅' if settings['notify_delete_time'] else 'معطل ❌'}\n"
        f"• الكتم: {'مفعل ✅' if settings['notify_mute'] else 'معطل ❌'}\n"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"إشعار حماية الأرقام {'إيقاف' if settings['notify_numbers'] else 'تفعيل'}", callback_data=f"toggle_notify_numbers_{chat_id}")],
        [InlineKeyboardButton(text=f"إشعار حماية الروابط {'إيقاف' if settings['notify_links'] else 'تفعيل'}", callback_data=f"toggle_notify_links_{chat_id}")],
        [InlineKeyboardButton(text=f"إشعار وضع الحظر {'إيقاف' if settings['notify_ban_mode'] else 'تفعيل'}", callback_data=f"toggle_notify_ban_mode_{chat_id}")],
        [InlineKeyboardButton(text=f"إشعار مدة الحذف {'إيقاف' if settings['notify_delete_time'] else 'تفعيل'}", callback_data=f"toggle_notify_delete_time_{chat_id}")],
        [InlineKeyboardButton(text=f"إشعار الكتم {'إيقاف' if settings['notify_mute'] else 'تفعيل'}", callback_data=f"toggle_notify_mute_{chat_id}")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"refresh_{chat_id}")]
    ])

    return text, keyboard

# ================== Handlers ==================

@dp.message(Command(commands=["start"]))
async def start_command(message: types.Message):
    user_id = message.from_user.id

    groups = get_all_groups()

    admin_groups = [g for g in groups if await is_admin(g, user_id)]

    if admin_groups:
        for chat_id in admin_groups:
            chat = await bot.get_chat(chat_id)
            group_title = chat.title or "مجموعة"
            text = f"👑 <b>مرحبا يا أدمن {group_title}!</b>\n\nلوحة التحكم:"
            panel_text, keyboard = await get_admin_panel(chat_id, user_id)
            if panel_text:
                await message.answer(text)
                await message.answer(panel_text, reply_markup=keyboard)
    else:
        intro_text = (
            "🛡️ <b>مرحباً بك في بوت الحارس الأمني!</b>\n\n"
            "🔒 <i>حماية متقدمة من السبام.</i>\n\n"
            "📌 يعمل فقط في المجموعات المسجلة.\n\n"
            "🌟 للتسجيل، تواصل معنا 👇"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 تسجيل مجموعتك", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="❓ استفسار", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="🌟 معلومات إضافية", callback_data="more_info")]
        ])
        await message.answer(intro_text, reply_markup=keyboard)

@dp.callback_query()
async def handle_callback_query(callback: types.CallbackQuery):
    data = callback.data

    if data == "more_info":
        more_info_text = (
            "🛡️ <b>معلومات إضافية:</b>\n\n"
            "• لوحة تحكم خاصة للأدمن مع إعدادات منفصلة لكل مجموعة.\n"
            "• تحكم كامل في الإشعارات (تشغيل/إيقاف لكل نوع، مثل إشعار الكتم أو تغيير الحماية).\n"
            "• مدة حذف الإشعار قابلة للتخصيص.\n"
            "• إحصائيات وعدادات مستقلة لكل مجموعة.\n"
            "• المزيد قادم!"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")]
        ])
        await callback.message.answer(more_info_text, reply_markup=keyboard)
        await callback.answer()
        return

    chat_id = int(data.split("_")[-1]) if "_" in data else None

    if data == "back_to_main":
        await start_command(callback.message)
        await callback.answer()
        return

    if data.startswith("toggle_numbers_"):
        if await is_admin(chat_id, callback.from_user.id):
            current = get_settings(chat_id)["protect_numbers"]
            new_value = int(not current)
            update_setting(chat_id, "protect_numbers", new_value)
            status = "مفعلة ✅" if new_value else "معطلة ❌"
            if get_settings(chat_id)["notify_numbers"]:
                await bot.send_message(chat_id, f"🔔 تم {'تفعيل' if new_value else 'إيقاف'} حماية الأرقام")
            await callback.answer(f"حماية الأرقام: {status}")
            panel_text, keyboard = await get_admin_panel(chat_id, callback.from_user.id)
            await callback.message.edit_text(panel_text, reply_markup=keyboard)
        return

    # مشابه للـ toggle الأخرى (links, mode) مع إشعار إذا مفعل

    if data.startswith("delete_menu_"):
        text, keyboard = await get_delete_menu(chat_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
        return

    if data.startswith("set_delete_"):
        minutes = int(data.split("_")[-1])
        if await is_admin(chat_id, callback.from_user.id):
            update_setting(chat_id, "notification_delete_minutes", minutes)
            status = "عدم الحذف" if minutes == 0 else f"{minutes} دقيقة"
            if get_settings(chat_id)["notify_delete_time"]:
                await bot.send_message(chat_id, f"🔔 تم تعيين مدة حذف الإشعار: {status}")
            await callback.answer(f"مدة الحذف: {status}")
            panel_text, keyboard = await get_admin_panel(chat_id, callback.from_user.id)
            await callback.message.edit_text(panel_text, reply_markup=keyboard)
        return

    if data.startswith("notify_menu_"):
        text, keyboard = await get_notify_menu(chat_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()
        return

    # toggle لكل إشعار (numbers, links, ban_mode, delete_time, mute) بدون إشعار إضافي (لأنه إعداد إشعار نفسه)

    if data.startswith("refresh_"):
        if await is_admin(chat_id, callback.from_user.id):
            panel_text, keyboard = await get_admin_panel(chat_id, callback.from_user.id)
            await callback.message.edit_text(panel_text, reply_markup=keyboard)
            await callback.answer("تم التحديث")
        return

# ================== handler عام ==================
@dp.message()
async def check_message(message: types.Message):
    if message.chat.type in ["supergroup", "group"]:
        add_group(message.chat.id)

    if message.chat.type == 'private':
        contact_text = (
            "🛡️ <b>شكرًا لاهتمامك!</b>\n\n"
            "📩 تواصل معنا لتسجيل مجموعتك 👇"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")]
        ])
        await message.answer(contact_text, reply_markup=keyboard)
        return

    settings = get_settings(message.chat.id)
    if not settings:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    if await is_admin(chat_id, user_id):
        return

    text = (message.text or message.caption or "").strip()
    if not contains_spam(text):
        return

    increment_spam_count(chat_id)

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"فشل حذف: {e}")

    if not await is_banned(chat_id, user_id):
        try:
            await bot.ban_chat_member(chat_id, user_id)
            action = "حظر"
        except Exception as e:
            logger.warning(f"فشل الحظر: {e}")
            action = "حذف"
    else:
        action = "حذف (محظور مسبقًا)"

    notification = (
        f"🚫 <b>تم {action} العضو</b>\n\n"
        f"👤 <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
        f"📛 السبب: سبام\n"
        f"🛡️ المجموعة محمية"
    )

    try:
        notify_msg = await bot.send_message(chat_id, notification)
        delete_minutes = settings["notification_delete_minutes"]
        if delete_minutes > 0:
            asyncio.create_task(delete_after_delay(notify_msg, delete_minutes * 60))
    except Exception as e:
        logger.warning(f"فشل الإشعار: {e}")

async def delete_after_delay(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

# ================== Webhook ==================
app = FastAPI()

WEBHOOK_PATH = f"/bot/{TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook تم تفعيله: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"خطأ Webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    try:
        update_dict = await request.json()
        update = types.Update.model_validate(update_dict, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.error(f"خطأ تحديث: {e}")
    return Response(content="OK", status_code=200)

@app.get("/")
async def root():
    return {"status": "البوت يعمل بنجاح! 🟢"}