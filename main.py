import asyncio
import logging
import os
import re
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional

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

# ================== الأنماط الأساسية ==================
def normalize_digits(text: str) -> str:
    trans = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣۴۵۶۷۸۹',
        '012345678901234567890123456789'
    )
    return text.translate(trans)

PHONE_PATTERN = re.compile(r'(?:\+?966|00966|966|05|5|0)?(\d[\s\W_*/.-]*){8,12}', re.IGNORECASE)
PHONE_CONTEXT_PATTERN = re.compile(r'(?:اتصل|رقمي|واتس|هاتف|موبايل|mobile|phone|call|contact|whatsapp|واتساب|📞|☎️)[\s\W_*/]{0,10}(?:\+\d{1,4}[\s\W_*/.-]*\d{5,15}|\d{9,15})', re.IGNORECASE | re.UNICODE)
WHATSAPP_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:chat\.whatsapp\.com|wa\.me)/[^\s]*|\+\w{8,}', re.IGNORECASE)
TELEGRAM_INVITE_PATTERN = re.compile(r'(?:https?://)?t\.me/(?:joinchat/|[+])[\w-]{10,}|(?:https?://)?t\.me/[^\s/]+', re.IGNORECASE)
TIKTOK_PATTERN = re.compile(r'(?:https?://)?(?:vm\.|www\.)?tiktok\.com/[^\s]*', re.IGNORECASE)
SHORT_LINK_PATTERN = re.compile(r'(?:https?://)?(bit\.ly|tinyurl\.com|goo\.gl|t\.co)/[^\s]*', re.IGNORECASE)

ALLOWED_DOMAINS = ["youtube.com", "youtu.be", "instagram.com", "instagr.am", "x.com", "twitter.com"]

# ================== إعدادات البوت الموسعة ==================
settings = {}
temp_duration = {}
temp_night = {}
temp_keywords = {}
temp_membership = {}
temp_countries = {}
temp_exceptions = {}
temp_links = {}

# وحدات الوقت
unit_seconds = {
    'minute': 60, 
    'hour': 3600, 
    'day': 86400, 
    'week': 604800,
    'month': 2592000, 
    'year': 31536000
}

unit_to_text_dict = {
    'minute': 'دقيقة', 
    'hour': 'ساعة', 
    'day': 'يوم', 
    'week': 'أسبوع',
    'month': 'شهر', 
    'year': 'سنة'
}

def seconds_to_value_unit(seconds: int):
    if seconds == 0:
        return 0, 'minute'
    for unit, secs in sorted(unit_seconds.items(), key=lambda x: x[1], reverse=True):
        if seconds >= secs:
            value = seconds // secs
            return value, unit
    return seconds // 60, 'minute'

def mode_to_text(mode):
    modes = {
        'mute': 'كتم عند المخالفة الأولى',
        'ban': 'حظر عند المخالفة الأولى',
        'mute_then_ban': 'كتم الأولى + حظر الثانية',
        'delete_only': 'حذف الرسالة فقط',
        'warn_then_mute': 'تحذير ثم كتم',
        'warn_then_ban': 'تحذير ثم حظر'
    }
    return modes.get(mode, mode)

# ================== وظائف المساعدة ==================
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

async def get_user_join_date(chat_id: int, user_id: int):
    """الحصول على تاريخ انضمام العضو"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.joined_date:
            return datetime.fromtimestamp(member.joined_date)
    except:
        pass
    return None

def contains_spam(text: str, group_str: str) -> bool:
    """الكشف عن السبام مع مراعاة الكلمات المفتاحية"""
    if not text:
        return False

    normalized = normalize_digits(text)
    
    # الكشف عن الأنماط الأساسية
    if PHONE_PATTERN.search(normalized) or PHONE_CONTEXT_PATTERN.search(normalized):
        return True

    if any(pattern.search(text) for pattern in [WHATSAPP_INVITE_PATTERN, TELEGRAM_INVITE_PATTERN, TIKTOK_PATTERN, SHORT_LINK_PATTERN]):
        return True

    # الكشف عن الكلمات المفتاحية الممنوعة
    if group_str in settings and 'banned_keywords' in settings[group_str]:
        keywords = settings[group_str]['banned_keywords']
        for keyword in keywords:
            if keyword.lower() in text.lower():
                return True

    # الكشف عن الروابط الممنوعة
    urls = re.findall(r'https?://[^\s]+|www\.[^\s]+|[^\s]+\.[^\s]{2,}', text, re.IGNORECASE)
    for url in urls:
        clean_url = url.replace(' ', '').lower()
        if not any(domain in clean_url for domain in ALLOWED_DOMAINS):
            # التحقق من الروابط الممنوعة في الإعدادات
            if group_str in settings and 'banned_links' in settings[group_str]:
                banned_links = settings[group_str]['banned_links']
                for banned_link in banned_links:
                    if banned_link.lower() in clean_url:
                        return True
            return True

    has_phone = bool(PHONE_PATTERN.search(normalized))
    has_link = bool(re.search(r'https?://|www\.|[^\s]+\.[^\s/]+', text, re.IGNORECASE))
    if has_phone and has_link:
        return True

    return False

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
            'night_announce_msg_id': None,
            'banned_keywords': [],
            'keyword_action': 'mute',
            'keyword_mute_duration': 3600,
            'membership_days': 7,
            'membership_action': 'strict',
            'banned_countries': [],
            'country_detection_enabled': False,
            'country_action': 'ban',
            'banned_links': [],
            'link_action': 'delete',
            'exempted_days': 0,
            'exempted_users': [],
            'warnings': {}
        }

    try:
        # محاولة تحميل الإعدادات من الرسائل
        history = await bot.get_chat_messages(DB_CHAT_ID, limit=50)
        
        json_msg = None
        for msg in history:
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

# ================== لوحات التحكم مع شرح مفصل ==================
def get_main_control_panel(group_id):
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    current_duration = settings[group_str]['mute_duration']
    duration_value, duration_unit = seconds_to_value_unit(current_duration)
    night_enabled = settings[group_str]['night_mode_enabled']
    night_start = settings[group_str]['night_start']
    night_end = settings[group_str]['night_end']
    
    text = f"🛡️ <b>لوحة تحكم الحارس الأمني</b>\n\n"
    text += f"📊 <b>إحصائيات المجموعة:</b>\n"
    text += f"• وضع الحماية: {mode_to_text(current_mode)}\n"
    text += f"• مدة العقوبة: {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
    text += f"• الوضع الليلي: {'✅ مفعل' if night_enabled else '❌ معطل'}\n"
    text += f"• الكلمات الممنوعة: {len(settings[group_str]['banned_keywords'])} كلمة\n"
    text += f"• الروابط الممنوعة: {len(settings[group_str]['banned_links'])} رابط\n"
    text += f"• الدول المحظورة: {len(settings[group_str]['banned_countries'])} دولة\n"
    text += f"• أيام استثناء الأعضاء: {settings[group_str]['exempted_days']} يوم\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ إعدادات الحماية الأساسية", callback_data=f"protection_menu_{group_id}")],
        [InlineKeyboardButton(text="🔤 إدارة الكلمات الممنوعة", callback_data=f"keywords_menu_{group_id}")],
        [InlineKeyboardButton(text="🔗 إدارة الروابط الممنوعة", callback_data=f"links_menu_{group_id}")],
        [InlineKeyboardButton(text="🌍 إدارة الدول المحظورة", callback_data=f"countries_menu_{group_id}")],
        [InlineKeyboardButton(text="👤 إدارة الأعضاء والاستثناءات", callback_data=f"members_menu_{group_id}")],
        [InlineKeyboardButton(text="🔄 تحديث اللوحة", callback_data=f"refresh_{group_id}")]
    ])
    
    return text, keyboard

def get_protection_menu(group_id):
    group_str = str(group_id)
    
    text = "🛡️ <b>إعدادات الحماية الأساسية</b>\n\n"
    text += "📌 <i>هذا القسم يتحكم في آلية الحماية الأساسية للبوت ضد الرسائل المخالفة</i>\n\n"
    text += "🔹 <b>وضع الحماية:</b> يحدد نوع العقوبة التلقائية للمخالفين\n"
    text += "🔹 <b>مدة العقوبة:</b> يحدد فترة الكتم إذا كانت العقوبة كتم\n"
    text += "🔹 <b>الوضع الليلي:</b> يوقف النشر لغير الإداريين في أوقات محددة\n\n"
    text += "اختر الإعداد الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ وضع الحماية", callback_data=f"mode_menu_{group_id}")],
        [InlineKeyboardButton(text="⏱️ مدة العقوبة", callback_data=f"duration_menu_{group_id}")],
        [InlineKeyboardButton(text="🌙 الوضع الليلي", callback_data=f"night_menu_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع للوحة الرئيسية", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_mode_menu(group_id):
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    
    text = "⚔️ <b>إعدادات وضع الحماية</b>\n\n"
    text += "📖 <i>هذا الإعداد يحدد كيفية تعامل البوت مع الأعضاء الذين ينشرون محتوى مخالف:</i>\n\n"
    text += "🔸 <b>كتم عند المخالفة الأولى:</b> يكتم العضو مباشرة عند أول مخالفة\n"
    text += "🔸 <b>حظر عند المخالفة الأولى:</b> يحظر العضو نهائيًا عند أول مخالفة\n"
    text += "🔸 <b>كتم الأولى + حظر الثانية:</b> يعطي فرصة ثم يحظر عند التكرار\n"
    text += "🔸 <b>حذف الرسالة فقط:</b> يحذف المخالفة بدون عقاب العضو\n"
    text += "🔸 <b>تحذير ثم كتم:</b> يعطي تحذيرًا أولاً ثم يكتم\n"
    text += "🔸 <b>تحذير ثم حظر:</b> يعطي تحذيرًا أولاً ثم يحظر\n\n"
    text += f"<b>الوضع الحالي:</b> {mode_to_text(current_mode)}\n\n"
    text += "اختر الوضع المناسب:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ كتم أولى" if current_mode == 'mute' else "كتم أولى", callback_data=f"mode_mute_{group_id}")],
        [InlineKeyboardButton(text=f"✅ حظر فوري" if current_mode == 'ban' else "حظر فوري", callback_data=f"mode_ban_{group_id}")],
        [InlineKeyboardButton(text=f"✅ كتم ثم حظر" if current_mode == 'mute_then_ban' else "كتم ثم حظر", callback_data=f"mode_mute_then_ban_{group_id}")],
        [InlineKeyboardButton(text=f"✅ حذف فقط" if current_mode == 'delete_only' else "حذف فقط", callback_data=f"mode_delete_only_{group_id}")],
        [InlineKeyboardButton(text=f"✅ تحذير ثم كتم" if current_mode == 'warn_then_mute' else "تحذير ثم كتم", callback_data=f"mode_warn_then_mute_{group_id}")],
        [InlineKeyboardButton(text=f"✅ تحذير ثم حظر" if current_mode == 'warn_then_ban' else "تحذير ثم حظر", callback_data=f"mode_warn_then_ban_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_duration_menu(group_id):
    group_str = str(group_id)
    current_duration = settings[group_str]['mute_duration']
    duration_value, duration_unit = seconds_to_value_unit(current_duration)
    
    text = "⏱️ <b>إعدادات مدة العقوبة</b>\n\n"
    text += "📖 <i>هذا الإعداد يحدد مدة الكتم عندما تكون العقوبة هي الكتم:</i>\n\n"
    text += "🔸 يمكنك ضبط المدة من دقيقة واحدة إلى سنة كاملة\n"
    text += "🔸 المدة تؤثر فقط على عقوبات الكتم\n"
    text += "🔸 العقوبات الأخرى (كالحظر) لا تتأثر بهذا الإعداد\n\n"
    text += f"<b>المدة الحالية:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n"
    text += "اختر المدة المناسبة:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 دقيقة", callback_data=f"set_duration_60_{group_id}")],
        [InlineKeyboardButton(text="1 ساعة", callback_data=f"set_duration_3600_{group_id}")],
        [InlineKeyboardButton(text="1 يوم", callback_data=f"set_duration_86400_{group_id}")],
        [InlineKeyboardButton(text="1 أسبوع", callback_data=f"set_duration_604800_{group_id}")],
        [InlineKeyboardButton(text="1 شهر", callback_data=f"set_duration_2592000_{group_id}")],
        [InlineKeyboardButton(text="تخصيص مدة", callback_data=f"custom_duration_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

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
    text += "📖 <i>هذا الإعداد يوقف نشاط الأعضاء العاديين خلال ساعات محددة:</i>\n\n"
    text += "🔸 يمنع الأعضاء غير الإداريين من النشر خلال الفترة المحددة\n"
    text += "🔸 يعرض رسالة تلقائية عند التفعيل والإلغاء\n"
    text += "🔸 مفيد للحفاظ على هدوء المجموعة ليلاً\n"
    text += "🔸 الإداريون يستطيعون النشر في أي وقت\n\n"
    text += f"<b>الحالة الحالية:</b> {'✅ مفعل' if night_enabled else '❌ معطل'}\n"
    text += f"<b>وقت البدء:</b> {night_start} ({format_12h(night_start)})\n"
    text += f"<b>وقت الانتهاء:</b> {night_end} ({format_12h(night_end)})\n\n"
    text += "اختر الإعداد الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'❌ تعطيل' if night_enabled else '✅ تفعيل'} الوضع الليلي", callback_data=f"night_toggle_{group_id}")],
        [InlineKeyboardButton(text="⏰ تعديل وقت البدء", callback_data=f"edit_night_start_{group_id}")],
        [InlineKeyboardButton(text="⏰ تعديل وقت الانتهاء", callback_data=f"edit_night_end_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_keywords_menu(group_id):
    group_str = str(group_id)
    keywords = settings[group_str]['banned_keywords']
    keyword_action = settings[group_str]['keyword_action']
    keyword_duration = settings[group_str]['keyword_mute_duration']
    dur_value, dur_unit = seconds_to_value_unit(keyword_duration)
    
    text = "🔤 <b>إدارة الكلمات الممنوعة</b>\n\n"
    text += "📖 <i>هذا القسم لإدارة الكلمات والعبارات المحظورة في المجموعة:</i>\n\n"
    text += "🔸 يمكنك إضافة أي كلمة أو عبارة تريد منعها\n"
    text += "🔸 البوت يكشف الكلمات حتى لو كانت مختلطة بحروف أخرى\n"
    text += "🔸 يمكنك تحديد عقوبة خاصة للكلمات الممنوعة\n\n"
    text += f"<b>عدد الكلمات:</b> {len(keywords)} كلمة\n"
    text += f"<b>العقوبة المحددة:</b> {mode_to_text(keyword_action)}\n"
    if keyword_action in ['mute', 'mute_then_ban', 'warn_then_mute']:
        text += f"<b>مدة الكتم:</b> {dur_value} {unit_to_text_dict.get(dur_unit, dur_unit)}\n\n"
    else:
        text += "\n"
    
    if keywords:
        text += "📝 <b>آخر 5 كلمات ممنوعة:</b>\n"
        for i, word in enumerate(keywords[-5:], 1):
            text += f"{i}. {word[:30]}{'...' if len(word) > 30 else ''}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة كلمة جديدة", callback_data=f"add_keyword_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف كلمة", callback_data=f"remove_keyword_{group_id}")],
        [InlineKeyboardButton(text="⚖️ تغيير العقوبة", callback_data=f"keyword_action_{group_id}")],
        [InlineKeyboardButton(text="📋 عرض جميع الكلمات", callback_data=f"show_keywords_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_links_menu(group_id):
    group_str = str(group_id)
    links = settings[group_str]['banned_links']
    link_action = settings[group_str]['link_action']
    
    text = "🔗 <b>إدارة الروابط الممنوعة</b>\n\n"
    text += "📖 <i>هذا القسم لإدارة الروابط والمواقع المحظورة في المجموعة:</i>\n\n"
    text += "🔸 يمكنك إضافة أي رابط تريد منعه (مثال: google.com, facebook.com)\n"
    text += "🔸 البوت يكشف الروابط حتى لو كانت مختصرة أو مخفية\n"
    text += "🔸 الروابط المسموح افتراضيًا: YouTube, Instagram, X/Twitter\n\n"
    text += f"<b>عدد الروابط:</b> {len(links)} رابط\n"
    text += f"<b>العقوبة المحددة:</b> {'حذف الرسالة فقط' if link_action == 'delete' else mode_to_text(link_action)}\n\n"
    
    if links:
        text += "📝 <b>آخر 5 روابط ممنوعة:</b>\n"
        for i, link in enumerate(links[-5:], 1):
            text += f"{i}. {link[:30]}{'...' if len(link) > 30 else ''}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة رابط جديد", callback_data=f"add_link_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف رابط", callback_data=f"remove_link_{group_id}")],
        [InlineKeyboardButton(text="⚖️ تغيير العقوبة", callback_data=f"link_action_{group_id}")],
        [InlineKeyboardButton(text="📋 عرض جميع الروابط", callback_data=f"show_links_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_countries_menu(group_id):
    group_str = str(group_id)
    banned_countries = settings[group_str]['banned_countries']
    country_action = settings[group_str]['country_action']
    detection_enabled = settings[group_str]['country_detection_enabled']
    
    text = "🌍 <b>إدارة الدول المحظورة</b>\n\n"
    text += "📖 <i>هذا القسم لمنع الأعضاء من دول محددة من الانضمام للمجموعة:</i>\n\n"
    text += "🔸 يمكنك حظر دول كاملة من الانضمام للمجموعة\n"
    text += "🔸 البوت يحاول كشف دولة العضو من إعدادات جهازه\n"
    text += "🔸 هذه الميزة تعمل عند محاولة الانضمام أو عند أول رسالة\n\n"
    text += f"<b>كشف الدولة:</b> {'✅ مفعل' if detection_enabled else '❌ معطل'}\n"
    text += f"<b>العقوبة المحددة:</b> {mode_to_text(country_action)}\n"
    text += f"<b>عدد الدول المحظورة:</b> {len(banned_countries)} دولة\n\n"
    
    if banned_countries:
        text += "📝 <b>آخر 5 دول محظورة:</b>\n"
        for i, country in enumerate(banned_countries[-5:], 1):
            text += f"{i}. {country}\n"
    
    # قائمة الدول الشائعة
    common_countries = [
        ("🇸🇦", "السعودية", "SA"),
        ("🇦🇪", "الإمارات", "AE"),
        ("🇶🇦", "قطر", "QA"),
        ("🇰🇼", "الكويت", "KW"),
        ("🇧🇭", "البحرين", "BH"),
        ("🇴🇲", "عمان", "OM"),
        ("🇺🇸", "الولايات المتحدة", "US"),
        ("🇬🇧", "المملكة المتحدة", "GB"),
        ("🇮🇳", "الهند", "IN"),
        ("🇵🇰", "بااكستان", "PK"),
        ("🇪🇬", "مصر", "EG"),
        ("🇯🇴", "الأردن", "JO"),
        ("🇱🇧", "لبنان", "LB"),
        ("🇸🇾", "سوريا", "SY"),
        ("🇮🇶", "العراق", "IQ"),
        ("🇾🇪", "اليمن", "YE"),
        ("🇩🇿", "الجزائر", "DZ"),
        ("🇲🇦", "المغرب", "MA"),
        ("🇹🇳", "تونس", "TN"),
        ("🇱🇾", "ليبيا", "LY"),
        ("🇸🇩", "السودان", "SD"),
        ("🇸🇴", "الصومال", "SO"),
        ("🇮🇷", "إيران", "IR"),
        ("🇹🇷", "تركيا", "TR"),
        ("🇷🇺", "روسيا", "RU"),
        ("🇨🇳", "الصين", "CN"),
        ("🇯🇵", "اليابان", "JP"),
        ("🇰🇷", "كوريا الجنوبية", "KR"),
        ("🇧🇷", "البرازيل", "BR"),
        ("🇫🇷", "فرنسا", "FR"),
        ("🇩🇪", "ألمانيا", "DE"),
        ("🇮🇹", "إيطاليا", "IT"),
        ("🇪🇸", "إسبانيا", "ES")
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # أزرار التحكم
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text=f"{'❌ تعطيل' if detection_enabled else '✅ تفعيل'} الكشف", callback_data=f"toggle_country_detect_{group_id}"),
        InlineKeyboardButton(text="⚖️ تغيير العقوبة", callback_data=f"country_action_{group_id}")
    ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="➕ إضافة دولة يدويًا", callback_data=f"add_country_manual_{group_id}"),
        InlineKeyboardButton(text="🗑️ حذف دولة", callback_data=f"remove_country_{group_id}")
    ])
    
    # أزرار الدول الشائعة (4 صفوف)
    row = []
    for i, (flag, name, code) in enumerate(common_countries[:8]):
        if code not in banned_countries:
            row.append(InlineKeyboardButton(text=f"{flag} {name}", callback_data=f"add_country_{code}_{group_id}"))
        else:
            row.append(InlineKeyboardButton(text=f"✅ {name}", callback_data=f"remove_country_{code}_{group_id}"))
        if len(row) == 2:
            keyboard.inline_keyboard.append(row)
            row = []
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="📋 عرض جميع الدول", callback_data=f"show_countries_{group_id}"),
        InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")
    ])
    
    return text, keyboard

def get_members_menu(group_id):
    group_str = str(group_id)
    exempted_days = settings[group_str]['exempted_days']
    exempted_users = settings[group_str]['exempted_users']
    membership_days = settings[group_str]['membership_days']
    membership_action = settings[group_str]['membership_action']
    
    text = "👤 <b>إدارة الأعضاء والاستثناءات</b>\n\n"
    text += "📖 <i>هذا القسم لإدارة سياسات المراقبة والاستثناءات للأعضاء:</i>\n\n"
    
    text += "🔸 <b>حماية الأعضاء الجدد:</b>\n"
    text += "   • يضع الأعضاء الجدد تحت رقابة صارمة لمدة محددة\n"
    text += "   • يتم مراقبة جميع رسائل العضو الجديد، سواء أرسل روابط أم لا\n"
    text += "   • إذا ارتكب مخالفة خلال فترة المراقبة، يتم تطبيق عقوبة أشد\n"
    text += "   • يمكنك ضبط مدة المراقبة (من 1 يوم إلى 365 يومًا) وسياسة العقاب\n\n"
    
    text += "🔸 <b>استثناء الأعضاء:</b>\n"
    text += "   • يمكنك استثناء أعضاء من العقوبات بناءً على مدة انضمامهم\n"
    text += "   • مثال: استثناء جميع الأعضاء الذين انضموا قبل 30 يومًا\n"
    text += "   • أو استثناء عضو محدد يدويًا\n\n"
    
    text += f"<b>مدة حماية الجدد:</b> {membership_days} يوم\n"
    text += f"<b>سياسة حماية الجدد:</b> {'مراقبة صارمة' if membership_action == 'strict' else 'مراقبة عادية'}\n"
    text += f"<b>أيام الاستثناء:</b> {exempted_days} يوم (الأعضاء الأقدم من هذا معفيون)\n"
    text += f"<b>أعضاء مستثنون يدويًا:</b> {len(exempted_users)} عضو\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ إعدادات حماية الأعضاء الجدد", callback_data=f"membership_settings_{group_id}")],
        [InlineKeyboardButton(text="👑 إعدادات استثناء الأعضاء", callback_data=f"exemption_settings_{group_id}")],
        [InlineKeyboardButton(text="📋 قائمة المستثنين يدويًا", callback_data=f"list_exempted_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_membership_settings_menu(group_id):
    group_str = str(group_id)
    membership_days = settings[group_str]['membership_days']
    membership_action = settings[group_str]['membership_action']
    
    text = "🛡️ <b>إعدادات حماية الأعضاء الجدد</b>\n\n"
    text += "📖 <i>هذه الميزة تضع الأعضاء الجدد تحت رقابة مشددة:</i>\n\n"
    text += "🔸 <b>كيف تعمل:</b>\n"
    text += "   1. أي عضو انضم منذ فترة أقل من المحددة يعتبر 'جديد'\n"
    text += "   2. يتم مراقبة جميع رسائله بشكل مكثف\n"
    text += "   3. عند المخالفة، تطبق عقوبة أشد من المعتاد\n\n"
    text += "🔸 <b>فوائد الميزة:</b>\n"
    text += "   • تقليل السبام من الحسابات المزيفة الجديدة\n"
    text += "   • إعطاء فرصة للأعضاء الجدد الحقيقيين للتعرف على القوانين\n"
    text += "   • حماية المجموعة من هجمات البوتات الجماعية\n\n"
    text += f"<b>المدة الحالية:</b> {membership_days} يوم\n"
    text += f"<b>السياسة الحالية:</b> {'مراقبة صارمة (عقوبة مضاعفة)' if membership_action == 'strict' else 'مراقبة عادية'}\n\n"
    text += "اختر الإعداد الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱️ تغيير مدة الحماية", callback_data=f"change_membership_days_{group_id}")],
        [InlineKeyboardButton(text=f"{'🔄 تخفيف' if membership_action == 'strict' else '🔒 تشديد'} السياسة", callback_data=f"toggle_membership_action_{group_id}")],
        [InlineKeyboardButton(text="ℹ️ شرح تفصيلي", callback_data=f"membership_explain_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"members_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_exemption_settings_menu(group_id):
    group_str = str(group_id)
    exempted_days = settings[group_str]['exempted_days']
    
    text = "👑 <b>إعدادات استثناء الأعضاء</b>\n\n"
    text += "📖 <i>هذه الميزة تستثني الأعضاء القدامى من بعض العقوبات:</i>\n\n"
    text += "🔸 <b>كيف تعمل:</b>\n"
    text += "   1. تحدد عدد الأيام (مثال: 30 يومًا)\n"
    text += "   2. أي عضو انضم قبل هذه الفترة يعتبر 'عضوًا قديمًا'\n"
    text += "   3. الأعضاء القدامى قد يحصلون على معاملة خاصة\n"
    text += "   4. يمكن أيضًا إضافة أعضاء محددين يدويًا للاستثناء\n\n"
    text += "🔸 <b>فوائد الميزة:</b>\n"
    text += "   • مكافأة الأعضاء المخلصين القدامى\n"
    text += "   • تقليل المراقبة على الأعضاء الموثوق بهم\n"
    text += "   • التركيز على مراقبة الحسابات المشبوهة الجديدة\n\n"
    text += f"<b>الأيام الحالية:</b> {exempted_days} يوم\n"
    text += "<i>ملاحظة: 0 يوم يعني تعطيل خاصية الاستثناء التلقائي</i>\n\n"
    text += "اختر الإعداد الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱️ تغيير أيام الاستثناء", callback_data=f"change_exempted_days_{group_id}")],
        [InlineKeyboardButton(text="👤 إضافة مستثنى يدويًا", callback_data=f"add_exempted_user_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف مستثنى يدوي", callback_data=f"remove_exempted_user_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"members_menu_{group_id}")]
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
        intro_text = "🛡️ <b>مرحباً بك في لوحة تحكم بوت الحارس الأمني المتقدم!</b>\n\nاختر المجموعة التي تريد إدارتها:"
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
            [InlineKeyboardButton(text="🌟 المميزات المتقدمة", callback_data="more_info")]
        ])
        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)

# ================== handler الـ callback ==================
@dp.callback_query()
async def handle_callback_query(callback: types.CallbackQuery):
    data = callback.data
    await callback.answer()

    # الأزرار العامة
    if data == "more_info":
        more_info_text = (
            "🛡️ <b>الحارس الأمني المتقدم – مميزات إضافية</b>\n\n"
            "🔥 <b>المميزات الجديدة:</b>\n"
            "✅ نظام كلمات مفتاحية ممنوعة مع عقوبات قابلة للتخصيص\n"
            "✅ كشف الروابط الممنوعة (Google, X, Facebook, إلخ)\n"
            "✅ حظر دول معينة من الانضمام مع كشف تلقائي\n"
            "✅ حماية الأعضاء الجدد (1-365 يوم) مع مراقبة صارمة\n"
            "✅ استثناء أعضاء محددين أو بناءً على مدة الانضمام\n"
            "✅ إحصائيات تفصيلية عن المخالفات\n"
            "✅ رسائل إشعار احترافية مع أزرار تفاعلية\n"
            "✅ واجهة تحكم متكاملة وسهلة الاستخدام\n\n"
            "🏆 بوت سريع، دقيق، ومستمر في التحديث لمواكبة حيل السبام.\n\n"
            "تواصل معنا للتسجيل أو الاستفسار 👇"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")]
        ])
        await callback.message.edit_text(more_info_text, reply_markup=keyboard, disable_web_page_preview=True)
        return

    # الأزرار الرئيسية
    if data.startswith("manage_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_main_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("back_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_main_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("refresh_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_main_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إعدادات الحماية
    if data.startswith("protection_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_protection_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("mode_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_mode_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("duration_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_duration_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("night_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_night_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # الكلمات الممنوعة
    if data.startswith("keywords_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_keywords_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # الروابط الممنوعة
    if data.startswith("links_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_links_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # الدول المحظورة
    if data.startswith("countries_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_countries_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إدارة الأعضاء
    if data.startswith("members_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_members_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("membership_settings_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_membership_settings_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("exemption_settings_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_exemption_settings_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # تغيير وضع الحماية
    if data.startswith("mode_"):
        parts = data.split("_")
        if len(parts) >= 3:
            mode_name = parts[1]
            if mode_name == "mute":
                mode = "mute"
            elif mode_name == "ban":
                mode = "ban"
            elif mode_name == "mute_then_ban":
                mode = "mute_then_ban"
            elif mode_name == "delete_only":
                mode = "delete_only"
            elif mode_name == "warn_then_mute":
                mode = "warn_then_mute"
            elif mode_name == "warn_then_ban":
                mode = "warn_then_ban"
            else:
                mode = "ban"
            
            group_id = int(parts[-1])
            group_str = str(group_id)
            
            settings[group_str]['mode'] = mode
            await save_settings_to_tg()
            
            await callback.answer(f"✅ تم تعيين وضع الحماية إلى: {mode_to_text(mode)}", show_alert=True)
            text, keyboard = get_mode_menu(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # تغيير مدة العقوبة
    if data.startswith("set_duration_"):
        parts = data.split("_")
        if len(parts) >= 4:
            seconds = int(parts[2])
            group_id = int(parts[3])
            group_str = str(group_id)
            
            settings[group_str]['mute_duration'] = seconds
            await save_settings_to_tg()
            
            dur_value, dur_unit = seconds_to_value_unit(seconds)
            await callback.answer(f"✅ تم تعيين مدة العقوبة إلى: {dur_value} {unit_to_text_dict.get(dur_unit, dur_unit)}", show_alert=True)
            text, keyboard = get_duration_menu(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # الوضع الليلي
    if data.startswith("night_toggle_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        settings[group_str]['night_mode_enabled'] = not settings[group_str]['night_mode_enabled']
        await save_settings_to_tg()
        
        status = "مفعل" if settings[group_str]['night_mode_enabled'] else "معطل"
        await callback.answer(f"✅ تم {status} الوضع الليلي", show_alert=True)
        text, keyboard = get_night_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # الدول المحظورة
    if data.startswith("toggle_country_detect_"):
        group_id = int(data.split("_")[3])
        group_str = str(group_id)
        settings[group_str]['country_detection_enabled'] = not settings[group_str]['country_detection_enabled']
        await save_settings_to_tg()
        
        status = "تفعيل" if settings[group_str]['country_detection_enabled'] else "تعطيل"
        await callback.answer(f"✅ تم {status} كشف الدولة", show_alert=True)
        text, keyboard = get_countries_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("add_country_"):
        parts = data.split("_")
        if len(parts) >= 4:
            country_code = parts[2]
            group_id = int(parts[3])
            group_str = str(group_id)
            
            # تحويل رمز الدولة إلى اسم
            country_names = {
                "SA": "السعودية", "AE": "الإمارات", "QA": "قطر", "KW": "الكويت", "BH": "البحرين",
                "OM": "عمان", "US": "الولايات المتحدة", "GB": "المملكة المتحدة", "IN": "الهند",
                "PK": "بااكستان", "EG": "مصر", "JO": "الأردن", "LB": "لبنان", "SY": "سوريا",
                "IQ": "العراق", "YE": "اليمن", "DZ": "الجزائر", "MA": "المغرب", "TN": "تونس",
                "LY": "ليبيا", "SD": "السودان", "SO": "الصومال", "IR": "إيران", "TR": "تركيا",
                "RU": "روسيا", "CN": "الصين", "JP": "اليابان", "KR": "كوريا الجنوبية",
                "BR": "البرازيل", "FR": "فرنسا", "DE": "ألمانيا", "IT": "إيطاليا", "ES": "إسبانيا"
            }
            
            country_name = country_names.get(country_code, country_code)
            
            if country_name not in settings[group_str]['banned_countries']:
                settings[group_str]['banned_countries'].append(country_name)
                await save_settings_to_tg()
                await callback.answer(f"✅ تم حظر: {country_name}", show_alert=True)
            else:
                await callback.answer(f"⚠️ {country_name} محظورة بالفعل", show_alert=True)
            
            text, keyboard = get_countries_menu(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("remove_country_"):
        parts = data.split("_")
        if len(parts) >= 4:
            country_code = parts[2]
            group_id = int(parts[3])
            group_str = str(group_id)
            
            # تحويل رمز الدولة إلى اسم
            country_names = {
                "SA": "السعودية", "AE": "الإمارات", "QA": "قطر", "KW": "الكويت", "BH": "البحرين",
                "OM": "عمان", "US": "الولايات المتحدة", "GB": "المملكة المتحدة", "IN": "الهند",
                "PK": "بااكستان", "EG": "مصر", "JO": "الأردن", "LB": "لبنان", "SY": "سوريا",
                "IQ": "العراق", "YE": "اليمن", "DZ": "الجزائر", "MA": "المغرب", "TN": "تونس",
                "LY": "ليبيا", "SD": "السودان", "SO": "الصومال", "IR": "إيران", "TR": "تركيا",
                "RU": "روسيا", "CN": "الصين", "JP": "اليابان", "KR": "كوريا الجنوبية",
                "BR": "البرازيل", "FR": "فرنسا", "DE": "ألمانيا", "IT": "إيطاليا", "ES": "إسبانيا"
            }
            
            country_name = country_names.get(country_code, country_code)
            
            if country_name in settings[group_str]['banned_countries']:
                settings[group_str]['banned_countries'].remove(country_name)
                await save_settings_to_tg()
                await callback.answer(f"✅ تم إلغاء حظر: {country_name}", show_alert=True)
            else:
                await callback.answer(f"⚠️ {country_name} غير محظورة", show_alert=True)
            
            text, keyboard = get_countries_menu(group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إدارة الأعضاء الجدد
    if data.startswith("change_membership_days_"):
        group_id = int(data.split("_")[3])
        await callback.message.answer(
            f"🛡️ <b>تغيير مدة حماية الأعضاء الجدد</b>\n\n"
            f"أرسل عدد الأيام (من 1 إلى 365):\n"
            f"<i>الأعضاء الذين انضموا خلال هذه الفترة يعتبرون 'جدد'</i>\n\n"
            f"<b>مثال:</b>\n"
            f"• 7 = أسبوع واحد\n"
            f"• 30 = شهر واحد\n"
            f"• 90 = ثلاثة أشهر\n"
            f"• 365 = سنة كاملة",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"membership_settings_{group_id}")]
            ])
        )
        # هنا يمكنك إضافة حالة انتظار للإدخال
        return
    
    if data.startswith("toggle_membership_action_"):
        group_id = int(data.split("_")[3])
        group_str = str(group_id)
        
        # تبديل بين وضعين: strict و normal
        current = settings[group_str]['membership_action']
        new_action = 'normal' if current == 'strict' else 'strict'
        settings[group_str]['membership_action'] = new_action
        await save_settings_to_tg()
        
        action_text = "مراقبة صارمة (عقوبة مضاعفة)" if new_action == 'strict' else "مراقبة عادية"
        await callback.answer(f"✅ تم تعيين سياسة حماية الجدد إلى: {action_text}", show_alert=True)
        
        text, keyboard = get_membership_settings_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # استثناء الأعضاء
    if data.startswith("change_exempted_days_"):
        group_id = int(data.split("_")[3])
        await callback.message.answer(
            f"👑 <b>تغيير أيام استثناء الأعضاء</b>\n\n"
            f"أرسل عدد الأيام (من 0 إلى 365):\n"
            f"<i>الأعضاء الذين انضموا قبل هذه الفترة يعتبرون 'قدامى' ويتم استثناؤهم</i>\n\n"
            f"<b>مثال:</b>\n"
            f"• 0 = تعطيل خاصية الاستثناء التلقائي\n"
            f"• 30 = شهر واحد\n"
            f"• 90 = ثلاثة أشهر\n"
            f"• 180 = ستة أشهر\n"
            f"• 365 = سنة كاملة",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"exemption_settings_{group_id}")]
            ])
        )
        return
    
    # إذا لم يتطابق أي زر، نعرض رسالة
    await callback.answer("⚠️ هذا الزر قيد التطوير", show_alert=True)

# ================== handler الرسائل للتحكم ==================
@dp.message(Command(commands=["addkeyword"]))
async def add_keyword_command(message: types.Message):
    if message.chat.type == 'private':
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if not await is_admin(chat_id, user_id):
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>الاستخدام:</b> <code>/addkeyword الكلمة</code>")
        return
    
    keyword = parts[1].strip()
    group_str = str(chat_id)
    
    if keyword not in settings[group_str]['banned_keywords']:
        settings[group_str]['banned_keywords'].append(keyword)
        await save_settings_to_tg()
        
        await message.reply(f"✅ <b>تم إضافة الكلمة الممنوعة:</b> <code>{keyword}</code>")
    else:
        await message.reply("⚠️ هذه الكلمة موجودة بالفعل في القائمة")

@dp.message(Command(commands=["addlink"]))
async def add_link_command(message: types.Message):
    if message.chat.type == 'private':
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if not await is_admin(chat_id, user_id):
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("⚠️ <b>الاستخدام:</b> <code>/addlink الرابط</code>")
        return
    
    link = parts[1].strip()
    group_str = str(chat_id)
    
    if link not in settings[group_str]['banned_links']:
        settings[group_str]['banned_links'].append(link)
        await save_settings_to_tg()
        
        await message.reply(f"✅ <b>تم إضافة الرابط الممنوع:</b> <code>{link}</code>")
    else:
        await message.reply("⚠️ هذا الرابط موجود بالفعل في القائمة")

@dp.message(Command(commands=["exempt"]))
async def exempt_user_command(message: types.Message):
    if message.chat.type == 'private':
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if not await is_admin(chat_id, user_id):
        return
    
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split()
        if len(parts) < 2:
            await message.reply("⚠️ <b>الاستخدام:</b> <code>/exempt @username</code> أو رد على رسالة العضو")
            return
        
        username = parts[1].replace("@", "")
        try:
            target_user = await bot.get_chat(username)
            target_user_id = target_user.id
        except:
            await message.reply("⚠️ لم أستطع العثور على هذا المستخدم")
            return
    
    group_str = str(chat_id)
    
    if target_user_id not in settings[group_str]['exempted_users']:
        settings[group_str]['exempted_users'].append(target_user_id)
        await save_settings_to_tg()
        
        await message.reply(f"✅ <b>تم استثناء العضو من العقوبات</b>\n👤 ID: <code>{target_user_id}</code>")
    else:
        await message.reply("⚠️ هذا العضو مستثنى بالفعل")

# ================== handler الرسائل الرئيسي ==================
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
    full_name = message.from_user.full_name

    # التحقق إذا كان العضو إداريًا
    if await is_admin(chat_id, user_id):
        return

    # التحقق من الاستثناء بالأيام
    if settings[group_str]['exempted_days'] > 0:
        join_date = await get_user_join_date(chat_id, user_id)
        if join_date:
            days_in_group = (datetime.now() - join_date).days
            if days_in_group >= settings[group_str]['exempted_days']:
                return  # العضو قديم ويتم استثناؤه

    # التحقق من الاستثناء اليدوي
    if user_id in settings[group_str]['exempted_users']:
        return

    # التحقق من حماية الأعضاء الجدد
    if settings[group_str]['membership_days'] > 0:
        join_date = await get_user_join_date(chat_id, user_id)
        if join_date:
            days_in_group = (datetime.now() - join_date).days
            if days_in_group < settings[group_str]['membership_days']:
                # العضو جديد، تطبيق سياسة المراقبة المشددة
                await handle_new_member_violation(chat_id, user_id, "عضو جديد تحت المراقبة", group_str, full_name)
    
    # التحقق من الوضع الليلي
    if settings[group_str]['night_mode_enabled']:
        start = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
        end = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
        now = datetime.now().time()
        is_night = (start <= now < end) if start < end else (start <= now or now < end)
        if is_night:
            await message.delete()
            notify = (
                f"🌙 <b>الوضع الليلي مفعل</b>\n\n"
                f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                f"📛 حاول النشر خلال فترة الإغلاق\n\n"
                f"⏰ <i>الإغلاق من {settings[group_str]['night_start']} إلى {settings[group_str]['night_end']}</i>"
            )
            msg = await bot.send_message(chat_id, notify)
            asyncio.create_task(delete_after_delay(msg, 60))
            return

    # التحقق من حظر الدول
    if settings[group_str]['country_detection_enabled'] and settings[group_str]['banned_countries']:
        # هنا يمكن إضافة كود لكشف الدولة
        # حالياً نستخدم طريقة مبسطة
        pass

    # التحقق من الرسالة
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    # التحقق من المخالفات
    is_spam = contains_spam(text, group_str)
    
    if is_spam:
        mode = settings[group_str]['mode']
        await handle_violation(chat_id, user_id, "نشر محتوى ممنوع", mode, group_str, full_name)
        await message.delete()

async def handle_new_member_violation(chat_id: int, user_id: int, reason: str, group_str: str, full_name: str):
    """معالجة مخالفات الأعضاء الجدد"""
    membership_action = settings[group_str]['membership_action']
    
    if membership_action == 'strict':
        # عقوبة مضاعفة للأعضاء الجدد
        notify = (
            f"🔴 <b>عضو جديد تحت المراقبة</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 <b>السبب:</b> {reason}\n"
            f"🆕 <b>الحالة:</b> عضو جديد تحت المراقبة الصارمة\n"
            f"⚠️ <b>تحذير:</b> أي مخالفة قد تؤدي لعقوبة مضاعفة\n\n"
            f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
        )
        msg = await bot.send_message(chat_id, notify)
        asyncio.create_task(delete_after_delay(msg, 120))
    
    # يمكن إضافة المزيد من الإجراءات حسب السياسة المحددة

async def handle_violation(chat_id: int, user_id: int, reason: str, action: str, group_str: str, full_name: str):
    """معالجة المخالفات بأنواعها المختلفة"""
    
    # تسجيل المخالفة
    if 'violations' not in settings[group_str]:
        settings[group_str]['violations'] = {}
    
    violations_count = settings[group_str]['violations'].get(user_id, 0) + 1
    settings[group_str]['violations'][user_id] = violations_count
    
    # تحديد إذا كان العضو جديدًا
    is_new_member = False
    join_date = await get_user_join_date(chat_id, user_id)
    if join_date and settings[group_str]['membership_days'] > 0:
        days_in_group = (datetime.now() - join_date).days
        if days_in_group < settings[group_str]['membership_days']:
            is_new_member = True
    
    # تطبيق العقوبة مع مراعاة إذا كان العضو جديدًا
    if action == 'delete_only':
        notify = (
            f"🗑️ <b>تم حذف رسالة مخالفة</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 <b>السبب:</b> {reason}\n"
            f"{'🆕 <b>الحالة:</b> عضو جديد تحت المراقبة\n' if is_new_member else ''}"
            f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
            f"<i>العقوبة: حذف الرسالة فقط</i>"
        )
        msg = await bot.send_message(chat_id, notify)
        asyncio.create_task(delete_after_delay(msg, 60))
    
    elif action == 'ban':
        if not await is_banned(chat_id, user_id):
            await bot.ban_chat_member(chat_id, user_id)
            notify = (
                f"🚫 <b>تم حظر العضو نهائيًا</b>\n\n"
                f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                f"📛 <b>السبب:</b> {reason}\n"
                f"{'🆕 <b>الحالة:</b> كان عضوًا جديدًا تحت المراقبة\n' if is_new_member else ''}"
                f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
                f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
            )
            msg = await bot.send_message(chat_id, notify)
            asyncio.create_task(delete_after_delay(msg, 120))
    
    elif action == 'mute':
        mute_duration = settings[group_str]['mute_duration']
        # مضاعفة المدة إذا كان العضو جديدًا
        if is_new_member and settings[group_str]['membership_action'] == 'strict':
            mute_duration *= 2
        
        until_date = int(time.time()) + mute_duration
        await bot.restrict_chat_member(
            chat_id, user_id, 
            permissions=types.ChatPermissions(can_send_messages=False), 
            until_date=until_date
        )
        duration_value, duration_unit = seconds_to_value_unit(mute_duration)
        notify = (
            f"🔇 <b>تم كتم العضو</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 <b>السبب:</b> {reason}\n"
            f"{'🆕 <b>الحالة:</b> عضو جديد - عقوبة مضاعفة\n' if is_new_member and settings[group_str]['membership_action'] == 'strict' else ''}"
            f"⏰ <b>المدة:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
            f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
            f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
        )
        msg = await bot.send_message(chat_id, notify)
        asyncio.create_task(delete_after_delay(msg, 120))
    
    elif action == 'mute_then_ban':
        mute_duration = settings[group_str]['mute_duration']
        
        if violations_count == 1:
            # مضاعفة المدة إذا كان العضو جديدًا
            if is_new_member and settings[group_str]['membership_action'] == 'strict':
                mute_duration *= 2
            
            until_date = int(time.time()) + mute_duration
            await bot.restrict_chat_member(
                chat_id, user_id, 
                permissions=types.ChatPermissions(can_send_messages=False), 
                until_date=until_date
            )
            duration_value, duration_unit = seconds_to_value_unit(mute_duration)
            notify = (
                f"🔇 <b>تم كتم العضو (مخالفة أولى)</b>\n\n"
                f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                f"📛 <b>السبب:</b> {reason}\n"
                f"{'🆕 <b>الحالة:</b> عضو جديد - عقوبة مضاعفة\n' if is_new_member and settings[group_str]['membership_action'] == 'strict' else ''}"
                f"⏰ <b>المدة:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
                f"⚠️ <b>تحذير:</b> المخالفة الثانية = حظر دائم\n\n"
                f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
            )
            msg = await bot.send_message(chat_id, notify)
            asyncio.create_task(delete_after_delay(msg, 120))
        else:
            if not await is_banned(chat_id, user_id):
                await bot.ban_chat_member(chat_id, user_id)
                notify = (
                    f"🚫 <b>تم حظر العضو نهائيًا (مخالفة ثانية)</b>\n\n"
                    f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                    f"📛 <b>السبب:</b> {reason}\n"
                    f"{'🆕 <b>الحالة:</b> كان عضوًا جديدًا تحت المراقبة\n' if is_new_member else ''}"
                    f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
                    f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
                )
                msg = await bot.send_message(chat_id, notify)
                asyncio.create_task(delete_after_delay(msg, 120))
    
    elif action == 'warn_then_mute' or action == 'warn_then_ban':
        if 'warnings' not in settings[group_str]:
            settings[group_str]['warnings'] = {}
        
        warnings_count = settings[group_str]['warnings'].get(user_id, 0) + 1
        settings[group_str]['warnings'][user_id] = warnings_count
        
        if warnings_count >= 3:
            if action == 'warn_then_mute':
                mute_duration = settings[group_str]['mute_duration']
                # مضاعفة المدة إذا كان العضو جديدًا
                if is_new_member and settings[group_str]['membership_action'] == 'strict':
                    mute_duration *= 2
                
                until_date = int(time.time()) + mute_duration
                await bot.restrict_chat_member(
                    chat_id, user_id, 
                    permissions=types.ChatPermissions(can_send_messages=False), 
                    until_date=until_date
                )
                duration_value, duration_unit = seconds_to_value_unit(mute_duration)
                notify = (
                    f"🔇 <b>تم كتم العضو بعد 3 تحذيرات</b>\n\n"
                    f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                    f"📛 <b>السبب:</b> {reason}\n"
                    f"{'🆕 <b>الحالة:</b> عضو جديد - عقوبة مضاعفة\n' if is_new_member and settings[group_str]['membership_action'] == 'strict' else ''}"
                    f"⏰ <b>المدة:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
                    f"⚠️ <b>عدد التحذيرات:</b> {warnings_count}\n\n"
                    f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
                )
            else:  # warn_then_ban
                if not await is_banned(chat_id, user_id):
                    await bot.ban_chat_member(chat_id, user_id)
                    notify = (
                        f"🚫 <b>تم حظر العضو بعد 3 تحذيرات</b>\n\n"
                        f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                        f"📛 <b>السبب:</b> {reason}\n"
                        f"{'🆕 <b>الحالة:</b> كان عضوًا جديدًا تحت المراقبة\n' if is_new_member else ''}"
                        f"⚠️ <b>عدد التحذيرات:</b> {warnings_count}\n\n"
                        f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
                    )
        else:
            notify = (
                f"⚠️ <b>تحذير #{warnings_count}</b>\n\n"
                f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                f"📛 <b>السبب:</b> {reason}\n"
                f"{'🆕 <b>الحالة:</b> عضو جديد تحت المراقبة\n' if is_new_member else ''}"
                f"⚠️ <b>تحذير:</b> عند الوصول لـ 3 تحذيرات = {'كتم' if action == 'warn_then_mute' else 'حظر'} دائم\n\n"
                f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
            )
        
        msg = await bot.send_message(chat_id, notify)
        asyncio.create_task(delete_after_delay(msg, 120))
    
    await save_settings_to_tg()

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