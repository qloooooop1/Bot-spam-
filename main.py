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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================== الإعدادات ==================
TOKEN = os.getenv("TOKEN")

ALLOWED_GROUP_IDS = [-1001224326322, -1002370282238]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

storage = MemoryStorage()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# قاعدة البيانات في قناة تيليجرام
DB_CHAT_ID = -1002370282238
SETTINGS_MESSAGE_ID = None

# حالات FSM لإدخال البيانات
class Form(StatesGroup):
    waiting_for_keyword = State()
    waiting_for_link = State()
    waiting_for_country = State()
    waiting_for_membership_days = State()
    waiting_for_exempt_days = State()
    waiting_for_user_id = State()
    waiting_for_custom_duration = State()
    waiting_for_notification_time = State()
    waiting_for_night_start = State()
    waiting_for_night_end = State()

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
temp_data = {}

# وحدات الوقت
unit_seconds = {
    'second': 1,
    'minute': 60, 
    'hour': 3600, 
    'day': 86400, 
    'week': 604800,
    'month': 2592000, 
    'year': 31536000
}

unit_to_text_dict = {
    'second': 'ثانية',
    'minute': 'دقيقة', 
    'hour': 'ساعة', 
    'day': 'يوم', 
    'week': 'أسبوع',
    'month': 'شهر', 
    'year': 'سنة'
}

def seconds_to_value_unit(seconds: int):
    if seconds == 0:
        return 0, 'second'
    for unit, secs in sorted(unit_seconds.items(), key=lambda x: x[1], reverse=True):
        if seconds >= secs:
            value = seconds // secs
            return value, unit
    return seconds, 'second'

def mode_to_text(mode):
    modes = {
        'mute': '🔇 كتم عند المخالفة الأولى',
        'ban': '🚫 حظر عند المخالفة الأولى',
        'mute_then_ban': '🔇⏱️ كتم الأولى ثم حظر الثانية',
        'delete_only': '🗑️ حذف الرسالة فقط',
        'warn_then_mute': '⚠️🔇 تحذير ثم كتم',
        'warn_then_ban': '⚠️🚫 تحذير ثم حظر'
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
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.joined_date:
            return datetime.fromtimestamp(member.joined_date)
    except:
        pass
    return None

def contains_spam(text: str, group_str: str) -> bool:
    if not text:
        return False

    normalized = normalize_digits(text)
    
    if PHONE_PATTERN.search(normalized) or PHONE_CONTEXT_PATTERN.search(normalized):
        return True

    if any(pattern.search(text) for pattern in [WHATSAPP_INVITE_PATTERN, TELEGRAM_INVITE_PATTERN, TIKTOK_PATTERN, SHORT_LINK_PATTERN]):
        return True

    if group_str in settings and 'banned_keywords' in settings[group_str]:
        keywords = settings[group_str]['banned_keywords']
        text_lower = text.lower()
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return True

    urls = re.findall(r'https?://[^\s]+|www\.[^\s]+|[^\s]+\.[^\s]{2,}', text, re.IGNORECASE)
    for url in urls:
        clean_url = url.replace(' ', '').lower()
        if not any(domain in clean_url for domain in ALLOWED_DOMAINS):
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
            'warnings': {},
            'last_update': time.time(),
            'notification_duration': 120,
            'keep_notification': False
        }

    try:
        messages = []
        try:
            async for message in bot.get_chat_messages(DB_CHAT_ID, limit=50):
                messages.append(message)
        except Exception as e:
            logger.error(f"خطأ في جلب الرسائل: {e}")
            messages = []
        
        json_msg = None
        for msg in messages:
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
                    for key in settings[group_str]:
                        if key in loaded[group_str]:
                            settings[group_str][key] = loaded[group_str][key]
                    settings[group_str]['last_update'] = time.time()
            SETTINGS_MESSAGE_ID = json_msg.message_id
            logger.info("تم تحميل الإعدادات بنجاح")
        else:
            await save_settings_to_tg()
    except Exception as e:
        logger.error(f"خطأ تحميل: {e}")
        await save_settings_to_tg()

async def save_settings_to_tg():
    global SETTINGS_MESSAGE_ID
    for group_str in settings:
        settings[group_str]['last_update'] = time.time()
    
    text = json.dumps(settings, ensure_ascii=False, indent=2)
    try:
        if SETTINGS_MESSAGE_ID is not None:
            try:
                await bot.edit_message_text(
                    chat_id=DB_CHAT_ID, 
                    message_id=SETTINGS_MESSAGE_ID, 
                    text=text
                )
                logger.info("تم تحديث الإعدادات")
            except Exception as e:
                if "message is not modified" not in str(e):
                    logger.warning(f"إعادة إنشاء الرسالة بسبب: {e}")
                    msg = await bot.send_message(DB_CHAT_ID, text=text)
                    SETTINGS_MESSAGE_ID = msg.message_id
        else:
            msg = await bot.send_message(DB_CHAT_ID, text=text)
            SETTINGS_MESSAGE_ID = msg.message_id
            logger.info("تم إنشاء رسالة الإعدادات")
    except Exception as e:
        logger.error(f"خطأ حفظ: {e}")

# ================== الوضع الليلي ==================
async def night_mode_checker():
    while True:
        try:
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
                        finally:
                            settings[group_str]['night_announce_msg_id'] = None
                            await save_settings_to_tg()
        except Exception as e:
            logger.error(f"خطأ في الوضع الليلي: {e}")
        
        await asyncio.sleep(60)

# ================== لوحات التحكم ==================
def get_main_control_panel(group_id):
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    current_duration = settings[group_str]['mute_duration']
    duration_value, duration_unit = seconds_to_value_unit(current_duration)
    
    text = f"🛡️ <b>لوحة تحكم الحارس الأمني</b>\n\n"
    text += f"📊 <b>إحصائيات المجموعة:</b>\n"
    text += f"• {mode_to_text(current_mode)}\n"
    text += f"• مدة العقوبة: {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
    text += f"• الوضع الليلي: {'🌙 مفعل' if settings[group_str]['night_mode_enabled'] else '☀️ معطل'}\n"
    text += f"• الكلمات الممنوعة: {len(settings[group_str]['banned_keywords'])} كلمة\n"
    text += f"• الروابط الممنوعة: {len(settings[group_str]['banned_links'])} رابط\n"
    text += f"• الدول المحظورة: {len(settings[group_str]['banned_countries'])} دولة\n"
    text += f"• أيام استثناء الأعضاء: {settings[group_str]['exempted_days']} يوم\n"
    text += f"• حماية الأعضاء الجدد: {settings[group_str]['membership_days']} يوم\n"
    text += f"• مدة الإشعار: {settings[group_str]['notification_duration']} ثانية\n"
    text += f"• بقاء الإشعار: {'✅ للأبد' if settings[group_str]['keep_notification'] else '⏱️ مؤقت'}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ إعدادات الحماية الأساسية", callback_data=f"protection_{group_id}")],
        [InlineKeyboardButton(text="🔤 إدارة الكلمات الممنوعة", callback_data=f"keywords_{group_id}")],
        [InlineKeyboardButton(text="🔗 إدارة الروابط الممنوعة", callback_data=f"links_{group_id}")],
        [InlineKeyboardButton(text="🌍 إدارة الدول المحظورة", callback_data=f"countries_{group_id}")],
        [InlineKeyboardButton(text="👤 إدارة الأعضاء والاستثناءات", callback_data=f"members_{group_id}")],
        [InlineKeyboardButton(text="⏰ إدارة الإشعارات", callback_data=f"notifications_{group_id}")],
        [InlineKeyboardButton(text="🔄 تحديث اللوحة", callback_data=f"refresh_{group_id}")]
    ])
    
    return text, keyboard

def get_protection_menu(group_id):
    group_str = str(group_id)
    
    text = "🛡️ <b>إعدادات الحماية الأساسية</b>\n\n"
    text += "📌 <i>التحكم في آلية الحماية الأساسية ضد الرسائل المخالفة</i>\n\n"
    text += f"<b>الوضع الحالي:</b> {mode_to_text(settings[group_str]['mode'])}\n"
    
    duration_value, duration_unit = seconds_to_value_unit(settings[group_str]['mute_duration'])
    text += f"<b>مدة العقوبة:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
    
    text += f"<b>الوضع الليلي:</b> {'🌙 مفعل' if settings[group_str]['night_mode_enabled'] else '☀️ معطل'}\n\n"
    text += "اختر الإعداد الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ تغيير وضع الحماية", callback_data=f"mode_{group_id}")],
        [InlineKeyboardButton(text="⏱️ تغيير مدة العقوبة", callback_data=f"duration_{group_id}")],
        [InlineKeyboardButton(text="🌙 إدارة الوضع الليلي", callback_data=f"night_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_mode_menu(group_id):
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    
    text = "⚔️ <b>اختر وضع الحماية:</b>\n\n"
    text += "📖 <i>يحدد كيفية تعامل البوت مع المخالفين</i>\n\n"
    text += f"<b>الوضع الحالي:</b> {mode_to_text(current_mode)}\n\n"
    text += "الخيارات المتاحة:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ 🔇 كتم أولى" if current_mode == 'mute' else "🔇 كتم أولى", callback_data=f"setmode_mute_{group_id}")],
        [InlineKeyboardButton(text=f"✅ 🚫 حظر فوري" if current_mode == 'ban' else "🚫 حظر فوري", callback_data=f"setmode_ban_{group_id}")],
        [InlineKeyboardButton(text=f"✅ 🔇⏱️ كتم ثم حظر" if current_mode == 'mute_then_ban' else "🔇⏱️ كتم ثم حظر", callback_data=f"setmode_mutethenban_{group_id}")],
        [InlineKeyboardButton(text=f"✅ 🗑️ حذف فقط" if current_mode == 'delete_only' else "🗑️ حذف فقط", callback_data=f"setmode_deleteonly_{group_id}")],
        [InlineKeyboardButton(text=f"✅ ⚠️🔇 تحذير ثم كتم" if current_mode == 'warn_then_mute' else "⚠️🔇 تحذير ثم كتم", callback_data=f"setmode_warnthenmute_{group_id}")],
        [InlineKeyboardButton(text=f"✅ ⚠️🚫 تحذير ثم حظر" if current_mode == 'warn_then_ban' else "⚠️🚫 تحذير ثم حظر", callback_data=f"setmode_warnthenban_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_{group_id}")]
    ])
    
    return text, keyboard

def get_duration_menu(group_id):
    group_str = str(group_id)
    current_duration = settings[group_str]['mute_duration']
    duration_value, duration_unit = seconds_to_value_unit(current_duration)
    
    text = "⏱️ <b>تغيير مدة العقوبة</b>\n\n"
    text += "📖 <i>يحدد مدة الكتم عندما تكون العقوبة هي الكتم</i>\n\n"
    text += f"<b>المدة الحالية:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n"
    text += "اختر المدة المناسبة:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 ثانية", callback_data=f"setdur_30_{group_id}")],
        [InlineKeyboardButton(text="1 دقيقة", callback_data=f"setdur_60_{group_id}")],
        [InlineKeyboardButton(text="5 دقائق", callback_data=f"setdur_300_{group_id}")],
        [InlineKeyboardButton(text="1 ساعة", callback_data=f"setdur_3600_{group_id}")],
        [InlineKeyboardButton(text="1 يوم", callback_data=f"setdur_86400_{group_id}")],
        [InlineKeyboardButton(text="1 أسبوع", callback_data=f"setdur_604800_{group_id}")],
        [InlineKeyboardButton(text="1 شهر", callback_data=f"setdur_2592000_{group_id}")],
        [InlineKeyboardButton(text="تخصيص مدة ⚙️", callback_data=f"custom_dur_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_{group_id}")]
    ])
    
    return text, keyboard

def get_night_menu(group_id):
    group_str = str(group_id)
    night_enabled = settings[group_str]['night_mode_enabled']
    
    text = "🌙 <b>إدارة الوضع الليلي</b>\n\n"
    text += "📖 <i>يمنع الأعضاء غير الإداريين من النشر خلال ساعات محددة</i>\n\n"
    text += f"<b>الحالة الحالية:</b> {'🌙 مفعل' if night_enabled else '☀️ معطل'}\n"
    if night_enabled:
        text += f"<b>وقت البدء:</b> {settings[group_str]['night_start']}\n"
        text += f"<b>وقت الانتهاء:</b> {settings[group_str]['night_end']}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'❌ تعطيل' if night_enabled else '✅ تفعيل'} الوضع الليلي", callback_data=f"togglenight_{group_id}")],
        [InlineKeyboardButton(text="⏰ تعديل وقت البدء", callback_data=f"editstart_{group_id}")],
        [InlineKeyboardButton(text="⏰ تعديل وقت الانتهاء", callback_data=f"editend_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_{group_id}")]
    ])
    
    return text, keyboard

def get_notifications_menu(group_id):
    group_str = str(group_id)
    notification_duration = settings[group_str]['notification_duration']
    keep_notification = settings[group_str]['keep_notification']
    
    text = "⏰ <b>إدارة إشعارات البوت</b>\n\n"
    text += "📖 <i>التحكم في مدة بقاء رسائل الإشعار في المجموعة</i>\n\n"
    
    if keep_notification:
        text += f"<b>حالة الإشعارات:</b> ✅ باقية للأبد\n\n"
    else:
        minutes = notification_duration // 60
        seconds = notification_duration % 60
        if minutes > 0:
            duration_text = f"{minutes} دقيقة"
            if seconds > 0:
                duration_text += f" و{seconds} ثانية"
        else:
            duration_text = f"{seconds} ثانية"
        
        text += f"<b>مدة الإشعار:</b> {duration_text}\n\n"
    
    text += "اختر الإعداد الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'❌ تعطيل' if keep_notification else '✅ تفعيل'} البقاء للأبد", callback_data=f"toggle_keep_{group_id}")],
        [InlineKeyboardButton(text="⏱️ تغيير مدة الإشعار", callback_data=f"change_notif_duration_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_keywords_menu(group_id):
    group_str = str(group_id)
    keywords = settings[group_str]['banned_keywords']
    
    text = "🔤 <b>إدارة الكلمات الممنوعة</b>\n\n"
    text += "📖 <i>الكلمات والعبارات المحظورة في المجموعة</i>\n\n"
    text += f"<b>عدد الكلمات:</b> {len(keywords)} كلمة\n\n"
    
    if keywords:
        text += "<b>آخر 5 كلمات:</b>\n"
        for i, word in enumerate(keywords[-5:], 1):
            text += f"{i}. <code>{word[:30]}</code>\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة كلمة جديدة", callback_data=f"addkw_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف كلمة", callback_data=f"removekw_{group_id}")],
        [InlineKeyboardButton(text="📋 عرض جميع الكلمات", callback_data=f"showkw_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_links_menu(group_id):
    group_str = str(group_id)
    links = settings[group_str]['banned_links']
    
    text = "🔗 <b>إدارة الروابط الممنوعة</b>\n\n"
    text += "📖 <i>الروابط والمواقع المحظورة في المجموعة</i>\n\n"
    text += f"<b>عدد الروابط:</b> {len(links)} رابط\n\n"
    
    if links:
        text += "<b>آخر 5 روابط:</b>\n"
        for i, link in enumerate(links[-5:], 1):
            text += f"{i}. <code>{link[:30]}</code>\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة رابط جديد", callback_data=f"addlink_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف رابط", callback_data=f"removelink_{group_id}")],
        [InlineKeyboardButton(text="📋 عرض جميع الروابط", callback_data=f"showlinks_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_countries_menu(group_id):
    group_str = str(group_id)
    countries = settings[group_str]['banned_countries']
    
    text = "🌍 <b>إدارة الدول المحظورة</b>\n\n"
    text += "📖 <i>يمنع الأعضاء من دول محددة من الانضمام</i>\n\n"
    text += f"<b>عدد الدول:</b> {len(countries)} دولة\n"
    text += f"<b>الكشف مفعل:</b> {'✅ نعم' if settings[group_str]['country_detection_enabled'] else '❌ لا'}\n\n"
    
    if countries:
        text += "<b>الدول المحظورة:</b>\n"
        for i, country in enumerate(countries[:10], 1):
            text += f"{i}. {country}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة دولة", callback_data=f"addcountry_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف دولة", callback_data=f"removecountry_{group_id}")],
        [InlineKeyboardButton(text="📋 عرض جميع الدول", callback_data=f"showcountries_{group_id}")],
        [InlineKeyboardButton(text="🔧 تفعيل/تعطيل الكشف", callback_data=f"togglecountry_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_members_menu(group_id):
    group_str = str(group_id)
    
    text = "👤 <b>إدارة الأعضاء والاستثناءات</b>\n\n"
    text += "📖 <i>سياسات المراقبة والاستثناءات للأعضاء</i>\n\n"
    text += f"<b>حماية الأعضاء الجدد:</b> {settings[group_str]['membership_days']} يوم\n"
    text += f"<b>أيام الاستثناء:</b> {settings[group_str]['exempted_days']} يوم\n"
    text += f"<b>أعضاء مستثنون يدويًا:</b> {len(settings[group_str]['exempted_users'])} عضو\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ حماية الأعضاء الجدد", callback_data=f"membership_{group_id}")],
        [InlineKeyboardButton(text="👑 استثناء الأعضاء", callback_data=f"exemption_{group_id}")],
        [InlineKeyboardButton(text="📋 قائمة المستثنين", callback_data=f"listexempt_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
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
        try:
            if await is_admin(gid, user_id):
                chat = await bot.get_chat(gid)
                admin_groups.append((gid, chat.title or f"Group {gid}"))
        except:
            continue

    if admin_groups:
        intro_text = "🛡️ <b>لوحة تحكم الحارس الأمني</b>\n\nاختر المجموعة:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for gid, title in admin_groups:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"⚙️ {title[:20]}", callback_data=f"manage_{gid}")
            ])
        await message.answer(intro_text, reply_markup=keyboard)
    else:
        intro_text = "🛡️ <b>مرحباً بالحارس الأمني!</b>\n\n  البوت يعمل في المجموعات المسجلة فقط لتسجل مجموعتك في النظام قم قم بمراسلتنا 👈@ql_om @ ."
        await message.answer(intro_text)

# ================== handler الـ callback مع إصلاح كامل ==================
@dp.callback_query()
async def handle_callback_query(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    
    try:
        if not data:
            await callback.answer("⚠️ بيانات غير صالحة")
            return
        
        await callback.answer()
        
        # === الأزرار الرئيسية ===
        if data.startswith("manage_"):
            group_id = int(data.split("_")[1])
            await show_main_panel(callback, group_id)
        
        elif data.startswith("back_"):
            group_id = int(data.split("_")[1])
            await show_main_panel(callback, group_id)
        
        elif data.startswith("refresh_"):
            group_id = int(data.split("_")[1])
            await show_main_panel(callback, group_id)
        
        # === إعدادات الحماية ===
        elif data.startswith("protection_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_protection_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("mode_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_mode_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        # === إصلاح كامل لأزرار وضع الحماية ===
        elif data.startswith("setmode_"):
            parts = data.split("_")
            if len(parts) >= 3:
                mode_type = parts[1]  # mute, ban, mutethenban, deleteonly, warnthenmute, warnthenban
                group_id = int(parts[2])
                group_str = str(group_id)
                
                # تعيين الوضع المناسب
                mode_mapping = {
                    'mute': 'mute',
                    'ban': 'ban',
                    'mutethenban': 'mute_then_ban',
                    'deleteonly': 'delete_only',
                    'warnthenmute': 'warn_then_mute',
                    'warnthenban': 'warn_then_ban'
                }
                
                new_mode = mode_mapping.get(mode_type, 'ban')
                settings[group_str]['mode'] = new_mode
                await save_settings_to_tg()
                
                await callback.answer(f"✅ تم تعيين: {mode_to_text(new_mode)}", show_alert=True)
                text, keyboard = get_mode_menu(group_id)
                await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("duration_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_duration_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("setdur_"):
            parts = data.split("_")
            if len(parts) == 3:
                seconds = int(parts[1])
                group_id = int(parts[2])
                group_str = str(group_id)
                
                settings[group_str]['mute_duration'] = seconds
                await save_settings_to_tg()
                
                dur_val, dur_unit = seconds_to_value_unit(seconds)
                await callback.answer(f"✅ تم تعيين المدة: {dur_val} {unit_to_text_dict.get(dur_unit, dur_unit)}")
                text, keyboard = get_duration_menu(group_id)
                await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("custom_dur_"):
            group_id = int(data.split("_")[2])
            await state.set_state(Form.waiting_for_custom_duration)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "⚙️ <b>تخصيص مدة العقوبة</b>\n\n"
                "أرسل المدة بالثواني:\n\n"
                "<b>أمثلة:</b>\n"
                "• 60 = 1 دقيقة\n"
                "• 300 = 5 دقائق\n"
                "• 3600 = 1 ساعة\n"
                "• 86400 = 1 يوم\n"
                "• 604800 = 1 أسبوع\n"
                "• 2592000 = 1 شهر\n"
                "• 31536000 = 1 سنة\n\n"
                "<i>أدخل الرقم المناسب:</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"duration_{group_id}")]
                ])
            )
        
        elif data.startswith("night_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_night_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("togglenight_"):
            group_id = int(data.split("_")[1])
            group_str = str(group_id)
            
            settings[group_str]['night_mode_enabled'] = not settings[group_str]['night_mode_enabled']
            await save_settings_to_tg()
            
            status = "تفعيل" if settings[group_str]['night_mode_enabled'] else "تعطيل"
            await callback.answer(f"✅ تم {status} الوضع الليلي")
            text, keyboard = get_night_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("editstart_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_night_start)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "⏰ <b>تعديل وقت بدء الوضع الليلي</b>\n\n"
                "أرسل الوقت بالتنسيق 24 ساعة (HH:MM):\n\n"
                "<b>أمثلة:</b>\n"
                "• 22:00 = 10 مساءً\n"
                "• 23:30 = 11:30 مساءً\n"
                "• 00:00 = 12 منتصف الليل\n\n"
                "<i>أدخل الوقت الجديد:</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"night_{group_id}")]
                ])
            )
        
        elif data.startswith("editend_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_night_end)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "⏰ <b>تعديل وقت انتهاء الوضع الليلي</b>\n\n"
                "أرسل الوقت بالتنسيق 24 ساعة (HH:MM):\n\n"
                "<b>أمثلة:</b>\n"
                "• 06:00 = 6 صباحاً\n"
                "• 07:30 = 7:30 صباحاً\n"
                "• 08:00 = 8 صباحاً\n\n"
                "<i>أدخل الوقت الجديد:</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"night_{group_id}")]
                ])
            )
        
        # === إدارة الإشعارات ===
        elif data.startswith("notifications_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_notifications_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("toggle_keep_"):
            group_id = int(data.split("_")[2])
            group_str = str(group_id)
            
            settings[group_str]['keep_notification'] = not settings[group_str]['keep_notification']
            await save_settings_to_tg()
            
            status = "تفعيل" if settings[group_str]['keep_notification'] else "تعطيل"
            await callback.answer(f"✅ تم {status} بقاء الإشعار للأبد")
            text, keyboard = get_notifications_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("change_notif_duration_"):
            group_id = int(data.split("_")[3])
            await state.set_state(Form.waiting_for_notification_time)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "⏱️ <b>تغيير مدة بقاء الإشعار</b>\n\n"
                "أرسل المدة بالثواني:\n\n"
                "<b>أمثلة:</b>\n"
                "• 30 = 30 ثانية\n"
                "• 60 = 1 دقيقة\n"
                "• 120 = 2 دقيقة\n"
                "• 300 = 5 دقائق\n"
                "• 600 = 10 دقائق\n"
                "• 3600 = 1 ساعة\n\n"
                "<i>أدخل الرقم المناسب:</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"notifications_{group_id}")]
                ])
            )
        
        # === الكلمات الممنوعة ===
        elif data.startswith("keywords_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_keywords_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("addkw_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_keyword)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "📝 <b>أرسل الكلمة الممنوعة:</b>\n\n"
                "<i>يمكن أن تكون كلمة، عبارة، أو رابط</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"keywords_{group_id}")]
                ])
            )
        
        elif data.startswith("showkw_"):
            group_id = int(data.split("_")[1])
            group_str = str(group_id)
            keywords = settings[group_str]['banned_keywords']
            
            if keywords:
                text = "📋 <b>جميع الكلمات الممنوعة:</b>\n\n"
                for i, keyword in enumerate(keywords, 1):
                    text += f"{i}. <code>{keyword}</code>\n"
            else:
                text = "⚠️ لا توجد كلمات ممنوعة"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"keywords_{group_id}")]
            ])
            await safe_edit_message(callback, text, keyboard)
        
        # === الروابط الممنوعة ===
        elif data.startswith("links_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_links_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("addlink_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_link)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "🔗 <b>أرسل الرابط الممنوع:</b>\n\n"
                "<i>مثال: google.com أو https://facebook.com</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"links_{group_id}")]
                ])
            )
        
        elif data.startswith("showlinks_"):
            group_id = int(data.split("_")[1])
            group_str = str(group_id)
            links = settings[group_str]['banned_links']
            
            if links:
                text = "📋 <b>جميع الروابط الممنوعة:</b>\n\n"
                for i, link in enumerate(links, 1):
                    text += f"{i}. <code>{link}</code>\n"
            else:
                text = "⚠️ لا توجد روابط ممنوعة"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"links_{group_id}")]
            ])
            await safe_edit_message(callback, text, keyboard)
        
        # === الدول المحظورة ===
        elif data.startswith("countries_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_countries_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("addcountry_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_country)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "🌍 <b>أرسل اسم الدولة:</b>\n\n"
                "<i>مثال: السعودية، مصر، الولايات المتحدة</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"countries_{group_id}")]
                ])
            )
        
        elif data.startswith("showcountries_"):
            group_id = int(data.split("_")[1])
            group_str = str(group_id)
            countries = settings[group_str]['banned_countries']
            
            if countries:
                text = "📋 <b>جميع الدول المحظورة:</b>\n\n"
                for i, country in enumerate(countries, 1):
                    text += f"{i}. {country}\n"
            else:
                text = "⚠️ لا توجد دول محظورة"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"countries_{group_id}")]
            ])
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("togglecountry_"):
            group_id = int(data.split("_")[1])
            group_str = str(group_id)
            
            settings[group_str]['country_detection_enabled'] = not settings[group_str]['country_detection_enabled']
            await save_settings_to_tg()
            
            status = "تفعيل" if settings[group_str]['country_detection_enabled'] else "تعطيل"
            await callback.answer(f"✅ تم {status} كشف الدولة")
            text, keyboard = get_countries_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        # === إدارة الأعضاء ===
        elif data.startswith("members_"):
            group_id = int(data.split("_")[1])
            text, keyboard = get_members_menu(group_id)
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("membership_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_membership_days)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "🛡️ <b>تحديد مدة حماية الأعضاء الجدد</b>\n\n"
                "أرسل عدد الأيام (1-365):\n"
                "<i>الأعضاء الجدد خلال هذه الفترة تحت مراقبة صارمة</i>\n\n"
                "<b>مثال:</b>\n"
                "• 7 = أسبوع واحد\n"
                "• 30 = شهر واحد\n"
                "• 90 = ثلاثة أشهر",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"members_{group_id}")]
                ])
            )
        
        elif data.startswith("exemption_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_exempt_days)
            await state.update_data(group_id=group_id)
            
            await callback.message.answer(
                "👑 <b>تحديد أيام استثناء الأعضاء</b>\n\n"
                "أرسل عدد الأيام (0-365):\n"
                "<i>الأعضاء الأقدم من هذه الفترة يستثنون تلقائيًا</i>\n\n"
                "<b>مثال:</b>\n"
                "• 0 = تعطيل الاستثناء\n"
                "• 30 = شهر واحد\n"
                "• 90 = ثلاثة أشهر",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"members_{group_id}")]
                ])
            )
        
        elif data.startswith("listexempt_"):
            group_id = int(data.split("_")[1])
            group_str = str(group_id)
            exempted_users = settings[group_str]['exempted_users']
            
            if exempted_users:
                text = "📋 <b>قائمة الأعضاء المستثنين يدويًا:</b>\n\n"
                for i, user_id in enumerate(exempted_users, 1):
                    text += f"{i}. <code>{user_id}</code>\n"
            else:
                text = "⚠️ لا توجد أعضاء مستثنين يدويًا"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"members_{group_id}")]
            ])
            await safe_edit_message(callback, text, keyboard)
        
        elif data.startswith("removekw_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_keyword)
            await state.update_data(group_id=group_id, action='remove')
            
            await callback.message.answer(
                "🗑️ <b>أرسل الكلمة المراد حذفها:</b>\n\n"
                "<i>اكتب الكلمة التي تريد حذفها من القائمة</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"keywords_{group_id}")]
                ])
            )
        
        elif data.startswith("removelink_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_link)
            await state.update_data(group_id=group_id, action='remove')
            
            await callback.message.answer(
                "🗑️ <b>أرسل الرابط المراد حذفه:</b>\n\n"
                "<i>اكتب الرابط الذي تريد حذفه من القائمة</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"links_{group_id}")]
                ])
            )
        
        elif data.startswith("removecountry_"):
            group_id = int(data.split("_")[1])
            await state.set_state(Form.waiting_for_country)
            await state.update_data(group_id=group_id, action='remove')
            
            await callback.message.answer(
                "🗑️ <b>أرسل الدولة المراد حذفها:</b>\n\n"
                "<i>اكتب اسم الدولة التي تريد حذفها من القائمة</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"countries_{group_id}")]
                ])
            )
        
        else:
            await callback.answer("⚠️ زر غير معروف")
    
    except Exception as e:
        logger.error(f"خطأ في callback: {e}")
        await callback.answer("❌ حدث خطأ")

async def show_main_panel(callback, group_id):
    text, keyboard = get_main_control_panel(group_id)
    await safe_edit_message(callback, text, keyboard)

async def safe_edit_message(callback, text, keyboard):
    try:
        if callback.message.text != text or callback.message.reply_markup != keyboard:
            await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"خطأ في تعديل الرسالة: {e}")

# ================== handler إدخال البيانات ==================
@dp.message()
async def handle_all_messages(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.chat.type == 'private':
        current_state = await state.get_state()
        data = await state.get_data()
        group_id = data.get('group_id')
        action = data.get('action', 'add')
        
        if current_state == Form.waiting_for_keyword.state and group_id:
            keyword = message.text.strip()
            group_str = str(group_id)
            
            if action == 'add':
                if keyword not in settings[group_str]['banned_keywords']:
                    settings[group_str]['banned_keywords'].append(keyword)
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم إضافة الكلمة:</b> <code>{keyword}</code>")
                else:
                    await message.reply("⚠️ هذه الكلمة موجودة بالفعل")
            else:  # remove
                if keyword in settings[group_str]['banned_keywords']:
                    settings[group_str]['banned_keywords'].remove(keyword)
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم حذف الكلمة:</b> <code>{keyword}</code>")
                else:
                    await message.reply("⚠️ هذه الكلمة غير موجودة في القائمة")
            
            await state.clear()
            text, keyboard = get_keywords_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_link.state and group_id:
            link = message.text.strip()
            group_str = str(group_id)
            
            if action == 'add':
                if link not in settings[group_str]['banned_links']:
                    settings[group_str]['banned_links'].append(link)
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم إضافة الرابط:</b> <code>{link}</code>")
                else:
                    await message.reply("⚠️ هذا الرابط موجود بالفعل")
            else:  # remove
                if link in settings[group_str]['banned_links']:
                    settings[group_str]['banned_links'].remove(link)
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم حذف الرابط:</b> <code>{link}</code>")
                else:
                    await message.reply("⚠️ هذا الرابط غير موجود في القائمة")
            
            await state.clear()
            text, keyboard = get_links_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_country.state and group_id:
            country = message.text.strip()
            group_str = str(group_id)
            
            if action == 'add':
                if country not in settings[group_str]['banned_countries']:
                    settings[group_str]['banned_countries'].append(country)
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم إضافة الدولة:</b> {country}")
                else:
                    await message.reply("⚠️ هذه الدولة موجودة بالفعل")
            else:  # remove
                if country in settings[group_str]['banned_countries']:
                    settings[group_str]['banned_countries'].remove(country)
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم حذف الدولة:</b> {country}")
                else:
                    await message.reply("⚠️ هذه الدولة غير موجودة في القائمة")
            
            await state.clear()
            text, keyboard = get_countries_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_membership_days.state and group_id:
            try:
                days = int(message.text.strip())
                if 1 <= days <= 365:
                    group_str = str(group_id)
                    settings[group_str]['membership_days'] = days
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم تعيين حماية الجدد:</b> {days} يوم")
                else:
                    await message.reply("⚠️ الرجاء إدخال رقم بين 1 و 365")
                    return
            except ValueError:
                await message.reply("⚠️ الرجاء إدخال رقم صحيح")
                return
            
            await state.clear()
            text, keyboard = get_members_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_exempt_days.state and group_id:
            try:
                days = int(message.text.strip())
                if 0 <= days <= 365:
                    group_str = str(group_id)
                    settings[group_str]['exempted_days'] = days
                    await save_settings_to_tg()
                    await message.reply(f"✅ <b>تم تعيين أيام الاستثناء:</b> {days} يوم")
                else:
                    await message.reply("⚠️ الرجاء إدخال رقم بين 0 و 365")
                    return
            except ValueError:
                await message.reply("⚠️ الرجاء إدخال رقم صحيح")
                return
            
            await state.clear()
            text, keyboard = get_members_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_custom_duration.state and group_id:
            try:
                seconds = int(message.text.strip())
                if 1 <= seconds <= 31536000:
                    group_str = str(group_id)
                    settings[group_str]['mute_duration'] = seconds
                    await save_settings_to_tg()
                    
                    dur_val, dur_unit = seconds_to_value_unit(seconds)
                    await message.reply(f"✅ <b>تم تعيين المدة:</b> {dur_val} {unit_to_text_dict.get(dur_unit, dur_unit)}")
                else:
                    await message.reply("⚠️ الرجاء إدخال رقم بين 1 و 31536000 (سنة)")
                    return
            except ValueError:
                await message.reply("⚠️ الرجاء إدخال رقم صحيح")
                return
            
            await state.clear()
            text, keyboard = get_duration_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_notification_time.state and group_id:
            try:
                seconds = int(message.text.strip())
                if 1 <= seconds <= 86400:
                    group_str = str(group_id)
                    settings[group_str]['notification_duration'] = seconds
                    await save_settings_to_tg()
                    
                    minutes = seconds // 60
                    remaining_seconds = seconds % 60
                    
                    if minutes > 0:
                        duration_text = f"{minutes} دقيقة"
                        if remaining_seconds > 0:
                            duration_text += f" و{remaining_seconds} ثانية"
                    else:
                        duration_text = f"{seconds} ثانية"
                    
                    await message.reply(f"✅ <b>تم تعيين مدة الإشعار:</b> {duration_text}")
                else:
                    await message.reply("⚠️ الرجاء إدخال رقم بين 1 و 86400 (24 ساعة)")
                    return
            except ValueError:
                await message.reply("⚠️ الرجاء إدخال رقم صحيح")
                return
            
            await state.clear()
            text, keyboard = get_notifications_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_night_start.state and group_id:
            time_str = message.text.strip()
            try:
                # التحقق من تنسيق الوقت
                datetime.strptime(time_str, '%H:%M')
                group_str = str(group_id)
                settings[group_str]['night_start'] = time_str
                await save_settings_to_tg()
                await message.reply(f"✅ <b>تم تعيين وقت البدء:</b> {time_str}")
            except ValueError:
                await message.reply("⚠️ تنسوق الوقت غير صحيح. استخدم HH:MM (مثال: 22:00)")
                return
            
            await state.clear()
            text, keyboard = get_night_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        elif current_state == Form.waiting_for_night_end.state and group_id:
            time_str = message.text.strip()
            try:
                datetime.strptime(time_str, '%H:%M')
                group_str = str(group_id)
                settings[group_str]['night_end'] = time_str
                await save_settings_to_tg()
                await message.reply(f"✅ <b>تم تعيين وقت الانتهاء:</b> {time_str}")
            except ValueError:
                await message.reply("⚠️ تنسوق الوقت غير صحيح. استخدم HH:MM (مثال: 06:00)")
                return
            
            await state.clear()
            text, keyboard = get_night_menu(group_id)
            await message.answer(text, reply_markup=keyboard)
        
        else:
            await check_group_message(message)
    
    else:
        await check_group_message(message)

async def check_group_message(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in ALLOWED_GROUP_IDS:
        return

    user_id = message.from_user.id
    group_str = str(chat_id)
    
    if await is_admin(chat_id, user_id):
        return
    
    if user_id in settings[group_str]['exempted_users']:
        return
    
    if settings[group_str]['exempted_days'] > 0:
        join_date = await get_user_join_date(chat_id, user_id)
        if join_date:
            days_in_group = (datetime.now() - join_date).days
            if days_in_group >= settings[group_str]['exempted_days']:
                return
    
    if settings[group_str]['night_mode_enabled']:
        start = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
        end = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
        now = datetime.now().time()
        is_night = (start <= now < end) if start < end else (start <= now or now < end)
        
        if is_night:
            await message.delete()
            try:
                warn_msg = await message.answer(
                    f"🌙 <b>الوضع الليلي مفعل</b>\n\n"
                    f"⏰ الإغلاق من {start} إلى {end}\n"
                    f"🚫 النشر متوقف حالياً"
                )
                await asyncio.sleep(10)
                await warn_msg.delete()
            except:
                pass
            return
    
    text = (message.text or message.caption or "").strip()
    if not text:
        return
    
    if contains_spam(text, group_str):
        await handle_violation(chat_id, user_id, message, group_str)

async def handle_violation(chat_id: int, user_id: int, message: types.Message, group_str: str):
    full_name = message.from_user.full_name or "مستخدم"
    mode = settings[group_str]['mode']
    
    if 'violations' not in settings[group_str]:
        settings[group_str]['violations'] = {}
    
    violations = settings[group_str]['violations'].get(user_id, 0) + 1
    settings[group_str]['violations'][user_id] = violations
    
    try:
        await message.delete()
    except:
        pass
    
    user_link = f'<a href="tg://user?id={user_id}">{full_name}</a>'
    notification_text = ""
    
    if mode == 'delete_only':
        notification_text = f"🗑️ <b>تم حذف رسالة مخالفة</b>\n👤 {user_link}\n📛 مخالفة #{violations}"
    
    elif mode == 'ban':
        try:
            await bot.ban_chat_member(chat_id, user_id)
            notification_text = f"🚫 <b>تم حظر العضو</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n⚡ حظر فوري"
        except Exception as e:
            logger.error(f"خطأ في الحظر: {e}")
            notification_text = f"⚠️ <b>فشل الحظر</b>\n👤 {user_link}\n📛 مخالفة #{violations}"
    
    elif mode == 'mute':
        duration = settings[group_str]['mute_duration']
        until_date = datetime.now() + timedelta(seconds=duration)
        
        try:
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            
            dur_val, dur_unit = seconds_to_value_unit(duration)
            notification_text = f"🔇 <b>تم كتم العضو</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n⏰ المدة: {dur_val} {unit_to_text_dict.get(dur_unit, dur_unit)}"
        except Exception as e:
            logger.error(f"خطأ في الكتم: {e}")
            notification_text = f"⚠️ <b>فشل الكتم</b>\n👤 {user_link}\n📛 مخالفة #{violations}"
    
    elif mode == 'mute_then_ban':
        if violations == 1:
            duration = settings[group_str]['mute_duration']
            until_date = datetime.now() + timedelta(seconds=duration)
            
            try:
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                
                dur_val, dur_unit = seconds_to_value_unit(duration)
                notification_text = f"🔇 <b>كتم أولى (تحذير)</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n⏰ المدة: {dur_val} {unit_to_text_dict.get(dur_unit, dur_unit)}\n⚠️ المخالفة الثانية = حظر دائم"
            except Exception as e:
                logger.error(f"خطأ في الكتم: {e}")
                notification_text = f"⚠️ <b>فشل الكتم</b>\n👤 {user_link}\n📛 مخالفة #{violations}"
        else:
            try:
                await bot.ban_chat_member(chat_id, user_id)
                notification_text = f"🚫 <b>تم حظر العضو (مخالفة ثانية)</b>\n👤 {user_link}\n📛 مخالفتين\n⚡ حظر دائم"
            except Exception as e:
                logger.error(f"خطأ في الحظر: {e}")
                notification_text = f"⚠️ <b>فشل الحظر</b>\n👤 {user_link}\n📛 مخالفتين"
    
    elif mode == 'warn_then_mute':
        if 'warnings' not in settings[group_str]:
            settings[group_str]['warnings'] = {}
        
        warnings_count = settings[group_str]['warnings'].get(user_id, 0) + 1
        settings[group_str]['warnings'][user_id] = warnings_count
        
        if warnings_count >= 3:
            duration = settings[group_str]['mute_duration']
            until_date = datetime.now() + timedelta(seconds=duration)
            
            try:
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                
                dur_val, dur_unit = seconds_to_value_unit(duration)
                notification_text = f"🔇 <b>تم كتم العضو (3 تحذيرات)</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n⚠️ تحذيرات: {warnings_count}\n⏰ المدة: {dur_val} {unit_to_text_dict.get(dur_unit, dur_unit)}"
            except Exception as e:
                logger.error(f"خطأ في الكتم: {e}")
                notification_text = f"⚠️ <b>فشل الكتم</b>\n👤 {user_link}\n📛 مخالفة #{violations}"
        else:
            notification_text = f"⚠️ <b>تحذير #{warnings_count}</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n🔔 عند 3 تحذيرات = كتم"
    
    elif mode == 'warn_then_ban':
        if 'warnings' not in settings[group_str]:
            settings[group_str]['warnings'] = {}
        
        warnings_count = settings[group_str]['warnings'].get(user_id, 0) + 1
        settings[group_str]['warnings'][user_id] = warnings_count
        
        if warnings_count >= 3:
            try:
                await bot.ban_chat_member(chat_id, user_id)
                notification_text = f"🚫 <b>تم حظر العضو (3 تحذيرات)</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n⚠️ تحذيرات: {warnings_count}\n⚡ حظر دائم"
            except Exception as e:
                logger.error(f"خطأ في الحظر: {e}")
                notification_text = f"⚠️ <b>فشل الحظر</b>\n👤 {user_link}\n📛 مخالفة #{violations}"
        else:
            notification_text = f"⚠️ <b>تحذير #{warnings_count}</b>\n👤 {user_link}\n📛 مخالفة #{violations}\n🔔 عند 3 تحذيرات = حظر"
    
    notification_text += f"\n\n🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
    
    if notification_text:
        try:
            notification_msg = await bot.send_message(chat_id, notification_text)
            
            if not settings[group_str]['keep_notification']:
                asyncio.create_task(delete_notification_later(
                    chat_id, 
                    notification_msg.message_id, 
                    settings[group_str]['notification_duration']
                ))
        except Exception as e:
            logger.error(f"خطأ في إرسال الإشعار: {e}")
    
    await save_settings_to_tg()

async def delete_notification_later(chat_id: int, message_id: int, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id, message_id)
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
        logger.info(f"✅ Webhook: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ فشل webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    try:
        update_dict = await request.json()
        update = types.Update.model_validate(update_dict, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"خطأ تحديث: {e}")
        return Response(status_code=400)

@app.get("/")
async def root():
    return {"status": "الحارس الأمني يعمل 🟢"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)