import asyncio
import logging
import os
import re
import time
import json
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

# ================== الإعدادات ==================
TOKEN = os.getenv("TOKEN")

ALLOWED_GROUP_IDS = [-1001224326322, -1002370282238]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# قاعدة البيانات في قناة تيليجرام
DB_CHAT_ID = -1002370282238
SETTINGS_MESSAGE_ID = None

# تحويل الأرقام العربية إلى لاتينية
def normalize_digits(text: str) -> str:
    trans = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣۴۵۶۷۸۹',
        '012345678901234567890123456789'
    )
    return text.translate(trans)

# أنماط كشف السبام
PHONE_PATTERN = re.compile(r'(?:\+?966|00966|966|05|5|0)?(\d[\s\W_*/.-]*){8,12}', re.IGNORECASE)
PHONE_CONTEXT_PATTERN = re.compile(r'(?:اتصل|رقمي|واتس|هاتف|موبايل|mobile|phone|call|contact|whatsapp|واتساب|📞|☎️)[\s\W_*/]{0,10}(?:\+\d{1,4}[\s\W_*/.-]*\d{5,15}|\d{9,15})', re.IGNORECASE | re.UNICODE)
WHATSAPP_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:chat\.whatsapp\.com|wa\.me)/[^\s]*|\+\w{8,}', re.IGNORECASE)
TELEGRAM_INVITE_PATTERN = re.compile(r'(?:https?://)?t\.me/(?:joinchat/|[+])[\w-]{10,}|(?:https?://)?t\.me/[^\s/]+', re.IGNORECASE)
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

    if PHONE_PATTERN.search(normalized) or PHONE_CONTEXT_PATTERN.search(normalized):
        return True

    if any(pattern.search(text) for pattern in [WHATSAPP_INVITE_PATTERN, TELEGRAM_INVITE_PATTERN, TIKTOK_PATTERN, SHORT_LINK_PATTERN]):
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

# إعدادات البوت
settings = {}
temp_duration = {}
temp_night = {}

unit_seconds = {'minute': 60, 'hour': 3600, 'day': 86400, 'month': 2592000, 'year': 31536000}
unit_to_text_dict = {'minute': 'دقيقة', 'hour': 'ساعة', 'day': 'يوم', 'month': 'شهر', 'year': 'سنة'}

def seconds_to_value_unit(seconds: int):
    if seconds == 0:
        return 0, 'minute'
    for unit, secs in sorted(unit_seconds.items(), key=lambda x: x[1], reverse=True):
        if seconds >= secs:
            value = seconds // secs
            return value, unit
    return seconds // 60, 'minute'

def mode_to_text(mode):
    if mode == 'mute':
        return 'كتم عند المخالفة الأولى'
    elif mode == 'ban':
        return 'حظر عند المخالفة الأولى'
    elif mode == 'mute_then_ban':
        return 'كتم الأولى + حظر الثانية'
    return mode

# ================== قاعدة البيانات ==================
async def load_settings_from_tg():
    global settings, SETTINGS_MESSAGE_ID
    settings = {}
    for gid in ALLOWED_GROUP_IDS:
        group_str = str(gid)
        settings[group_str] = {
            'mode': 'ban',
            'mute_duration': 86400,
            'violations': {},
            'night_mode_enabled': False,
            'night_start': '22:00',
            'night_end': '06:00',
            'night_announce_msg_id': None
        }

    try:
        dummy = await bot.send_message(DB_CHAT_ID, "تحميل الإعدادات...")
        history = await bot.get_chat_history(DB_CHAT_ID, limit=50)
        await bot.delete_message(DB_CHAT_ID, dummy.message_id)

        json_msg = None
        for msg in history[::-1]:
            if msg.text and msg.text.strip().startswith('{') and msg.text.strip().endswith('}'):
                try:
                    loaded = json.loads(msg.text)
                    if isinstance(loaded, dict):
                        json_msg = msg
                        break
                except:
                    continue

        if json_msg:
            loaded = json.loads(json_msg.text)
            for group_str in settings:
                if group_str in loaded:
                    settings[group_str].update(loaded[group_str])
                    settings[group_str].setdefault('violations', {})
                    settings[group_str].setdefault('night_mode_enabled', False)
                    settings[group_str].setdefault('night_start', '22:00')
                    settings[group_str].setdefault('night_end', '06:00')
                    settings[group_str].setdefault('night_announce_msg_id', None)
            SETTINGS_MESSAGE_ID = json_msg.message_id
        else:
            await save_settings_to_tg()
    except Exception as e:
        logger.error(f"خطأ تحميل: {e}")
        await save_settings_to_tg()

async def save_settings_to_tg():
    global SETTINGS_MESSAGE_ID
    text = json.dumps(settings, ensure_ascii=False, indent=2)
    try:
        if SETTINGS_MESSAGE_ID is not None:
            await bot.edit_message_text(chat_id=DB_CHAT_ID, message_id=SETTINGS_MESSAGE_ID, text=text)
        else:
            msg = await bot.send_message(DB_CHAT_ID, text=text)
            SETTINGS_MESSAGE_ID = msg.message_id
    except Exception as e:
        logger.error(f"خطأ حفظ: {e}")
        try:
            msg = await bot.send_message(DB_CHAT_ID, text=text)
            SETTINGS_MESSAGE_ID = msg.message_id
        except:
            pass

# ================== الوضع الليلي ==================
async def night_mode_checker():
    while True:
        now = datetime.now().time()
        for gid in ALLOWED_GROUP_IDS:
            group_str = str(gid)
            if group_str in settings and settings[group_str]['night_mode_enabled']:
                start = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
                end = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
                is_night = (start <= now < end) if start < end else (start <= now or now < end)

                if is_night and settings[group_str]['night_announce_msg_id'] is None:
                    announce_text = (
                        "🌙 <b>تم تفعيل الوضع الليلي</b>\n\n"
                        f"🚫 المشاركات متوقفة مؤقتًا حتى الساعة {settings[group_str]['night_end']}.\n"
                        "🛡️ استريحوا وناموا جيدًا!"
                    )
                    msg = await bot.send_message(gid, announce_text)
                    settings[group_str]['night_announce_msg_id'] = msg.message_id
                    await save_settings_to_tg()
                elif not is_night and settings[group_str]['night_announce_msg_id'] is not None:
                    try:
                        await bot.delete_message(gid, settings[group_str]['night_announce_msg_id'])
                    except:
                        pass
                    settings[group_str]['night_announce_msg_id'] = None
                    await save_settings_to_tg()
        await asyncio.sleep(60)

# ================== لوحة تحرير مدة الكتم ==================
def get_duration_editor(group_id):
    value = temp_duration[group_id]['value']
    unit = temp_duration[group_id]['unit']
    unit_text = unit_to_text_dict.get(unit, unit)
    
    if unit == 'year' and value >= 100:
        text = "⚠️ <b>تحذير:</b> مدة الكتم طويلة جداً (100 سنة أو أكثر)!\n"
    elif unit == 'month' and value >= 120:
        text = "⚠️ <b>تحذير:</b> مدة الكتم طويلة جداً (10 سنوات أو أكثر)!\n"
    else:
        text = ""
    
    text += f"🕒 <b>تحرير مدة الكتم</b>\n\nالقيمة الحالية: {value} {unit_text}\n\nاستخدم الأزرار للتعديل:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="-10", callback_data=f"dur_minus10_{group_id}"),
            InlineKeyboardButton(text="-1", callback_data=f"dur_minus1_{group_id}"),
            InlineKeyboardButton(text=f"{value}", callback_data="ignore"),
            InlineKeyboardButton(text="+1", callback_data=f"dur_plus1_{group_id}"),
            InlineKeyboardButton(text="+10", callback_data=f"dur_plus10_{group_id}")
        ],
        [
            InlineKeyboardButton(text="⬇️ تغيير الوحدة", callback_data="ignore")
        ],
        [
            InlineKeyboardButton(text=f"✓ دقيقة" if unit == 'minute' else "دقيقة", callback_data=f"dur_unit_minute_{group_id}"),
            InlineKeyboardButton(text=f"✓ ساعة" if unit == 'hour' else "ساعة", callback_data=f"dur_unit_hour_{group_id}"),
            InlineKeyboardButton(text=f"✓ يوم" if unit == 'day' else "يوم", callback_data=f"dur_unit_day_{group_id}")
        ],
        [
            InlineKeyboardButton(text=f"✓ شهر" if unit == 'month' else "شهر", callback_data=f"dur_unit_month_{group_id}"),
            InlineKeyboardButton(text=f"✓ سنة" if unit == 'year' else "سنة", callback_data=f"dur_unit_year_{group_id}")
        ],
        [
            InlineKeyboardButton(text="💾 حفظ", callback_data=f"dur_save_{group_id}"),
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}"),
            InlineKeyboardButton(text="❌ إلغاء", callback_data=f"dur_cancel_{group_id}")
        ]
    ])
    return text, keyboard

# ================== لوحة تحرير توقيت الوضع الليلي ==================
def get_night_editor(group_id):
    start = temp_night[group_id]['start']
    end = temp_night[group_id]['end']
    
    # تحويل الوقت إلى صيغة 12 ساعة مع AM/PM
    def format_12h(time_str):
        try:
            hour, minute = map(int, time_str.split(':'))
            period = "صباحاً" if hour < 12 else "مساءً"
            hour_12 = hour if hour <= 12 else hour - 12
            if hour_12 == 0:
                hour_12 = 12
            return f"{hour_12}:{minute:02d} {period}"
        except:
            return time_str
    
    start_12h = format_12h(start)
    end_12h = format_12h(end)
    
    text = f"🌙 <b>تحرير توقيت الوضع الليلي</b>\n\n"
    text += f"⏰ وقت الإغلاق: {start} ({start_12h})\n"
    text += f"⏰ وقت الفتح: {end} ({end_12h})\n\n"
    text += "استخدم الأزرار لتعديل الوقت:"
    
    # تقسيم الأزرار بشكل أكثر تنظيماً
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # ساعة الإغلاق
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🕐 ساعة الإغلاق:", callback_data="ignore")
    ])
    
    hour_buttons = []
    for h in [22, 23, 0, 1, 2, 3, 4, 5]:
        hour_str = f"{h:02d}"
        hour_buttons.append(InlineKeyboardButton(
            text=f"{hour_str}:00", 
            callback_data=f"night_start_{hour_str}:00_{group_id}"
        ))
    
    for i in range(0, len(hour_buttons), 4):
        keyboard.inline_keyboard.append(hour_buttons[i:i+4])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="↔️ تعديل الوقت", callback_data="ignore")
    ])
    
    # أزرار تعديل دقيقة الإغلاق
    start_hour, start_minute = map(int, start.split(':'))
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ -30 دقيقة", callback_data=f"night_start_min30_{group_id}"),
        InlineKeyboardButton(text="-15 دقيقة", callback_data=f"night_start_min15_{group_id}"),
        InlineKeyboardButton(text=f"{start_minute:02d}", callback_data="ignore"),
        InlineKeyboardButton(text="+15 دقيقة", callback_data=f"night_start_plus15_{group_id}"),
        InlineKeyboardButton(text="+30 دقيقة ▶️", callback_data=f"night_start_plus30_{group_id}")
    ])
    
    # ساعة الفتح
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🕐 ساعة الفتح:", callback_data="ignore")
    ])
    
    hour_buttons_end = []
    for h in [6, 7, 8, 9, 10, 11, 12, 13]:
        hour_str = f"{h:02d}"
        hour_buttons_end.append(InlineKeyboardButton(
            text=f"{hour_str}:00", 
            callback_data=f"night_end_{hour_str}:00_{group_id}"
        ))
    
    for i in range(0, len(hour_buttons_end), 4):
        keyboard.inline_keyboard.append(hour_buttons_end[i:i+4])
    
    # أزرار تعديل دقيقة الفتح
    end_hour, end_minute = map(int, end.split(':'))
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="◀️ -30 دقيقة", callback_data=f"night_end_min30_{group_id}"),
        InlineKeyboardButton(text="-15 دقيقة", callback_data=f"night_end_min15_{group_id}"),
        InlineKeyboardButton(text=f"{end_minute:02d}", callback_data="ignore"),
        InlineKeyboardButton(text="+15 دقيقة", callback_data=f"night_end_plus15_{group_id}"),
        InlineKeyboardButton(text="+30 دقيقة ▶️", callback_data=f"night_end_plus30_{group_id}")
    ])
    
    # أزرار التحكم
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="💾 حفظ", callback_data=f"night_save_{group_id}"),
        InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}"),
        InlineKeyboardButton(text="❌ إلغاء", callback_data=f"night_cancel_{group_id}")
    ])
    
    return text, keyboard

# ================== handler /start ==================
@dp.message(Command(commands=["start"]))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    if message.chat.type != 'private':
        return

    admin_groups = []
    for gid in ALLOWED_GROUP_IDS:
        if await is_admin(gid, user_id):
            chat = await bot.get_chat(gid)
            admin_groups.append((gid, chat.title or f"Group {gid}"))

    if admin_groups:
        intro_text = "🛡️ <b>مرحباً بك في لوحة تحكم بوت الحارس الأمني!</b>\n\nاختر المجموعة التي تريد إدارتها:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for gid, title in admin_groups:
            keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"⚙️ إدارة {title}", callback_data=f"manage_{gid}")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="❓ مساعدة أو استفسار", url="https://t.me/ql_om")])
        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        intro_text = (
            "🛡️ <b>مرحباً بك في بوت الحارس الأمني الذكي!</b>\n\n"
            "🔒 <i>بوت حماية متقدم لحماية مجموعاتك من السبام والروابط المشبوهة بذكاء عالي.</i>\n\n"
            "📌 البوت يعمل فقط في المجموعات المسجلة.\n\n"
            "تواصل معنا للتسجيل 👇"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 تسجيل مجموعتك", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="🌟 معلومات إضافية", callback_data="more_info")]
        ])
        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)

# ================== لوحة التحكم الرئيسية ==================
def get_main_control_panel(group_id):
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    current_duration = settings[group_str]['mute_duration']
    duration_value, duration_unit = seconds_to_value_unit(current_duration)
    night_enabled = settings[group_str]['night_mode_enabled']
    night_start = settings[group_str]['night_start']
    night_end = settings[group_str]['night_end']
    
    # تحويل الوقت إلى صيغة 12 ساعة
    def format_12h(time_str):
        try:
            hour, minute = map(int, time_str.split(':'))
            period = "صباحاً" if hour < 12 else "مساءً"
            hour_12 = hour if hour <= 12 else hour - 12
            if hour_12 == 0:
                hour_12 = 12
            return f"{hour_12}:{minute:02d} {period}"
        except:
            return time_str
    
    night_start_12h = format_12h(night_start)
    night_end_12h = format_12h(night_end)
    
    text = f"🛡️ <b>لوحة تحكم – المجموعة</b>\n\n"
    text += f"<b>وضع الحماية:</b> {mode_to_text(current_mode)}\n"
    text += f"<b>مدة الكتم:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
    text += f"<b>الوضع الليلي:</b> {'✅ مفعل' if night_enabled else '❌ معطل'}\n"
    if night_enabled:
        text += f"<b>الإغلاق:</b> {night_start} ({night_start_12h})\n"
        text += f"<b>الفتح:</b> {night_end} ({night_end_12h})\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ وضع الحماية", callback_data=f"mode_menu_{group_id}")],
        [InlineKeyboardButton(text="⏱️ مدة الكتم", callback_data=f"dur_{group_id}")],
        [InlineKeyboardButton(text="🌙 الوضع الليلي", callback_data=f"night_menu_{group_id}")],
        [InlineKeyboardButton(text="🔄 تحديث اللوحة", callback_data=f"refresh_{group_id}")],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="main_menu")]
    ])
    
    return text, keyboard

# ================== قائمة وضع الحماية ==================
def get_mode_menu(group_id):
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    
    text = "🛡️ <b>اختر وضع الحماية:</b>\n\n"
    text += f"وضع الحماية الحالي: {mode_to_text(current_mode)}\n\n"
    text += "• <b>كتم أولى:</b> كتم العضو عند المخالفة الأولى\n"
    text += "• <b>حظر فوري:</b> حظر العضو عند المخالفة الأولى\n"
    text += "• <b>كتم ثم حظر:</b> كتم أولاً، ثم حظر عند المخالفة الثانية\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ كتم أولى" if current_mode == 'mute' else "كتم أولى", callback_data=f"mode_mute_{group_id}")],
        [InlineKeyboardButton(text=f"✅ حظر فوري" if current_mode == 'ban' else "حظر فوري", callback_data=f"mode_ban_{group_id}")],
        [InlineKeyboardButton(text=f"✅ كتم ثم حظر" if current_mode == 'mute_then_ban' else "كتم ثم حظر", callback_data=f"mode_mtb_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

# ================== قائمة الوضع الليلي ==================
def get_night_menu(group_id):
    group_str = str(group_id)
    night_enabled = settings[group_str]['night_mode_enabled']
    night_start = settings[group_str]['night_start']
    night_end = settings[group_str]['night_end']
    
    def format_12h(time_str):
        try:
            hour, minute = map(int, time_str.split(':'))
            period = "صباحاً" if hour < 12 else "مساءً"
            hour_12 = hour if hour <= 12 else hour - 12
            if hour_12 == 0:
                hour_12 = 12
            return f"{hour_12}:{minute:02d} {period}"
        except:
            return time_str
    
    text = "🌙 <b>إعدادات الوضع الليلي</b>\n\n"
    text += f"الحالة: {'✅ <b>مفعل</b>' if night_enabled else '❌ <b>معطل</b>'}\n"
    text += f"وقت الإغلاق: {night_start} ({format_12h(night_start)})\n"
    text += f"وقت الفتح: {night_end} ({format_12h(night_end)})\n\n"
    text += "الوضع الليلي يمنع المشاركات من غير الأدمن خلال الفترة المحددة."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'❌ إيقاف' if night_enabled else '✅ تشغيل'} الوضع الليلي", callback_data=f"night_toggle_{group_id}")],
        [InlineKeyboardButton(text="⏰ تعديل التوقيت", callback_data=f"night_time_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

# ================== handler الـ callback ==================
@dp.callback_query()
async def handle_callback_query(callback: types.CallbackQuery):
    data = callback.data
    await callback.answer()

    if data == "main_menu":
        # العودة إلى القائمة الرئيسية
        await start_command(callback.message)
        return
        
    if data == "more_info":
        more_info_text = (
            "🛡️ <b>الحارس الأمني – بوت حماية متقدم</b>\n\n"
            "🔥 <b>المميزات الرئيسية:</b>\n"
            "• كشف ذكي للأرقام الهاتفية (حتى المخفية).\n"
            "• منع الروابط المشبوهة (واتساب، تيك توك، مختصرة).\n"
            "• أوضاع حماية مرنة: حظر فوري، كتم، أو كتم أولى ثم حظر (مع تذكر دائم للمخالفات).\n"
            "• <b>جديد: الوضع الليلي</b> – إغلاق المجموعة تلقائيًا في توقيت محدد مع رسالة إعلان جميلة.\n"
            "• لوحة تحكم احترافية للأدمن مع حفظ دائم للإعدادات.\n"
            "• إشعارات أنيقة تُحذف تلقائيًا.\n\n"
            "🏆 بوت سريع، دقيق، ومستمر في التحديث لمواكبة حيل السبام.\n\n"
            "تواصل معنا للتسجيل أو الاستفسار 👇"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")]
        ])
        await callback.message.edit_text(more_info_text, reply_markup=keyboard, disable_web_page_preview=True)
        return

    if data.startswith("manage_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_main_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
        
    if data.startswith("refresh_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_main_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
        
    if data.startswith("back_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_main_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("mode_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_mode_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("night_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_night_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    # تغيير الوضع
    if data.startswith("mode_"):
        parts = data.split("_")
        mode = parts[1]
        if mode == "mtb":
            mode = "mute_then_ban"
        group_id = int(parts[2])
        group_str = str(group_id)
        settings[group_str]['mode'] = mode
        settings[group_str]['violations'] = {}
        await save_settings_to_tg()
        
        # تحديث القائمة
        text, keyboard = get_mode_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    # مدة الكتم
    if data.startswith("dur_"):
        parts = data.split("_")
        action = parts[1]
        
        if len(parts) == 2:
            # فتح محرر المدة
            group_id = int(parts[1])
            group_str = str(group_id)
            current = settings[group_str]['mute_duration']
            value, unit = seconds_to_value_unit(current)
            temp_duration[group_id] = {'value': max(1, value), 'unit': unit}
            text, keyboard = get_duration_editor(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
            return
            
        group_id = int(parts[-1])
        
        if action in ["plus1", "plus10", "minus1", "minus10"]:
            delta = int(action.replace("plus", "").replace("minus", ""))
            if "minus" in action:
                delta = -delta
            temp_duration[group_id]['value'] = max(1, temp_duration[group_id]['value'] + delta)
        elif action.startswith("unit_"):
            unit = action[5:]
            temp_duration[group_id]['unit'] = unit
        elif action == "save":
            seconds = temp_duration[group_id]['value'] * unit_seconds[temp_duration[group_id]['unit']]
            group_str = str(group_id)
            settings[group_str]['mute_duration'] = seconds
            settings[group_str]['violations'] = {}
            await save_settings_to_tg()
            del temp_duration[group_id]
            text, keyboard = get_main_control_panel(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
            return
        elif action == "cancel":
            if group_id in temp_duration:
                del temp_duration[group_id]
            text, keyboard = get_main_control_panel(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
            return

        text, keyboard = get_duration_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    # الوضع الليلي
    if data.startswith("night_toggle_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        settings[group_str]['night_mode_enabled'] = not settings[group_str]['night_mode_enabled']
        await save_settings_to_tg()
        
        text, keyboard = get_night_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("night_time_"):
        parts = data.split("_")
        if len(parts) == 3:
            # فتح محرر الوقت
            group_id = int(parts[2])
            group_str = str(group_id)
            temp_night[group_id] = {'start': settings[group_str]['night_start'], 'end': settings[group_str]['night_end']}
            text, keyboard = get_night_editor(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
            return

    # تعديل وقت البداية والنهاية
    if data.startswith("night_start_") or data.startswith("night_end_"):
        parts = data.split("_")
        action = parts[1]
        
        if parts[2] in ["min30", "min15", "plus15", "plus30"]:
            # تعديل بالدقائق
            group_id = int(parts[3])
            current_time_str = temp_night[group_id][action]
            current_time = datetime.strptime(current_time_str, '%H:%M')
            
            if parts[2] == "min30":
                new_time = current_time - timedelta(minutes=30)
            elif parts[2] == "min15":
                new_time = current_time - timedelta(minutes=15)
            elif parts[2] == "plus15":
                new_time = current_time + timedelta(minutes=15)
            elif parts[2] == "plus30":
                new_time = current_time + timedelta(minutes=30)
                
            temp_night[group_id][action] = new_time.strftime('%H:%M')
        else:
            # تعيين وقت مباشر
            time_val = parts[2]
            group_id = int(parts[3])
            temp_night[group_id][action] = time_val
            
        text, keyboard = get_night_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("night_end_") and data.split("_")[2] in ["min30", "min15", "plus15", "plus30"]:
        parts = data.split("_")
        action = parts[1]
        group_id = int(parts[3])
        current_time_str = temp_night[group_id][action]
        current_time = datetime.strptime(current_time_str, '%H:%M')
        
        if parts[2] == "min30":
            new_time = current_time - timedelta(minutes=30)
        elif parts[2] == "min15":
            new_time = current_time - timedelta(minutes=15)
        elif parts[2] == "plus15":
            new_time = current_time + timedelta(minutes=15)
        elif parts[2] == "plus30":
            new_time = current_time + timedelta(minutes=30)
            
        temp_night[group_id][action] = new_time.strftime('%H:%M')
        text, keyboard = get_night_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("night_save_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        settings[group_str]['night_start'] = temp_night[group_id]['start']
        settings[group_str]['night_end'] = temp_night[group_id]['end']
        await save_settings_to_tg()
        
        if group_id in temp_night:
            del temp_night[group_id]
            
        text, keyboard = get_night_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("night_cancel_"):
        group_id = int(data.split("_")[2])
        if group_id in temp_night:
            del temp_night[group_id]
            
        text, keyboard = get_night_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

# ================== handler الرسائل ==================
@dp.message()
async def check_message(message: types.Message):
    if message.chat.type == 'private':
        await message.answer("🛡️ شكرًا لاهتمامك! تواصل معنا للتسجيل 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")]
        ]))
        return

    chat_id = message.chat.id
    if chat_id not in ALLOWED_GROUP_IDS:
        return

    user_id = message.from_user.id
    group_str = str(chat_id)

    # الوضع الليلي (غير الأدمن)
    if group_str in settings and settings[group_str]['night_mode_enabled']:
        start = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
        end = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
        now = datetime.now().time()
        is_night = (start <= now < end) if start < end else (start <= now or now < end)
        if is_night and not await is_admin(chat_id, user_id):
            await message.delete()
            return

    if await is_admin(chat_id, user_id):
        return

    text = (message.text or message.caption or "").strip()
    if not contains_spam(text):
        return

    await message.delete()

    mode = settings[group_str]['mode']
    mute_duration = settings[group_str]['mute_duration']
    full_name = message.from_user.full_name

    if mode == 'ban':
        if not await is_banned(chat_id, user_id):
            await bot.ban_chat_member(chat_id, user_id)
            notify = f"🚫 <b>تم حظر العضو نهائيًا</b>\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 نشر سبام\n🛡️ المجموعة محمية"
            msg = await bot.send_message(chat_id, notify)
            asyncio.create_task(delete_after_delay(msg, 120))

    elif mode == 'mute':
        until_date = int(time.time()) + mute_duration if mute_duration > 30 else 0
        await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
        duration_text = f"{seconds_to_value_unit(mute_duration)[0]} {unit_to_text_dict.get(seconds_to_value_unit(mute_duration)[1], '')}"
        notify = f"🔇 <b>تم كتم العضو</b> لمدة {duration_text}\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 نشر سبام\n🛡️ المجموعة محمية"
        msg = await bot.send_message(chat_id, notify)
        asyncio.create_task(delete_after_delay(msg, 120))

    elif mode == 'mute_then_ban':
        if 'violations' not in settings[group_str]:
            settings[group_str]['violations'] = {}

        violations_count = settings[group_str]['violations'].get(user_id, 0) + 1
        settings[group_str]['violations'][user_id] = violations_count
        await save_settings_to_tg()

        if violations_count == 1:
            until_date = int(time.time()) + mute_duration if mute_duration > 30 else 0
            await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
            duration_text = f"{seconds_to_value_unit(mute_duration)[0]} {unit_to_text_dict.get(seconds_to_value_unit(mute_duration)[1], '')}"
            notify = f"🔇 <b>تم كتم العضو (مخالفة أولى)</b> لمدة {duration_text}\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 نشر سبام"
            msg = await bot.send_message(chat_id, notify)
            asyncio.create_task(delete_after_delay(msg, 120))
        else:
            if not await is_banned(chat_id, user_id):
                await bot.ban_chat_member(chat_id, user_id)
                notify = f"🚫 <b>تم حظر العضو نهائيًا (مخالفة ثانية)</b>\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 نشر سبام"
                msg = await bot.send_message(chat_id, notify)
                asyncio.create_task(delete_after_delay(msg, 120))

async def delete_after_delay(message: types.Message, delay: int = 120):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass

# ================== FastAPI Webhook ==================
app = FastAPI()

WEBHOOK_PATH = f"/bot/{TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    await load_settings_from_tg()
    asyncio.create_task(night_mode_checker())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook تم تفعيله: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"فشل الـ webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    await save_settings_to_tg()
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