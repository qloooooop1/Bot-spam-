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
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pycountry
import flag

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

async def get_user_country(user_id: int) -> Optional[str]:
    """الحصول على دولة المستخدم من معلوماته"""
    try:
        user = await bot.get_chat(user_id)
        if user.language_code:
            # محاولة استخراج الدولة من لغة المستخدم
            lang = user.language_code.upper()
            country = pycountry.languages.get(alpha_2=lang)
            if country:
                return country.name
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
            'membership_duration': 0,
            'membership_unit': 'hour',
            'membership_action': 'mute',
            'banned_countries': [],
            'country_detection_enabled': False,
            'country_action': 'ban',
            'banned_links': [],
            'link_action': 'delete',
            'exempted_users': [],
            'warnings': {}
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
                    # تأكد من وجود جميع المفاتيح
                    for key in settings[group_str]:
                        if key not in loaded.get(group_str, {}):
                            settings[group_str][key] = settings[group_str][key]
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

# ================== لوحات التحكم ==================
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
    
    text = f"🛡️ <b>لوحة تحكم الحارس الأمني</b>\n\n"
    text += f"📊 <b>إحصائيات المجموعة:</b>\n"
    text += f"• وضع الحماية: {mode_to_text(current_mode)}\n"
    text += f"• مدة الكتم: {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
    text += f"• الوضع الليلي: {'✅ مفعل' if night_enabled else '❌ معطل'}\n"
    text += f"• الكلمات الممنوعة: {len(settings[group_str]['banned_keywords'])} كلمة\n"
    text += f"• الروابط الممنوعة: {len(settings[group_str]['banned_links'])} رابط\n"
    text += f"• الدول المحظورة: {len(settings[group_str]['banned_countries'])} دولة\n"
    text += f"• الأعضاء المستثنون: {len(settings[group_str]['exempted_users'])} عضو\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ إعدادات الحماية", callback_data=f"protection_menu_{group_id}")],
        [InlineKeyboardButton(text="🔤 الكلمات الممنوعة", callback_data=f"keywords_menu_{group_id}")],
        [InlineKeyboardButton(text="🔗 الروابط الممنوعة", callback_data=f"links_menu_{group_id}")],
        [InlineKeyboardButton(text="🌍 حظر الدول", callback_data=f"countries_menu_{group_id}")],
        [InlineKeyboardButton(text="👤 إدارة الأعضاء", callback_data=f"members_menu_{group_id}")],
        [InlineKeyboardButton(text="📊 الإحصائيات", callback_data=f"stats_{group_id}")],
        [InlineKeyboardButton(text="🔄 تحديث", callback_data=f"refresh_{group_id}")]
    ])
    
    return text, keyboard

def get_protection_menu(group_id):
    group_str = str(group_id)
    
    text = "🛡️ <b>إعدادات الحماية الرئيسية</b>\n\n"
    text += "اختر القسم الذي تريد تعديله:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ وضع الحماية", callback_data=f"mode_menu_{group_id}")],
        [InlineKeyboardButton(text="⏱️ مدة العقوبات", callback_data=f"duration_menu_{group_id}")],
        [InlineKeyboardButton(text="🌙 الوضع الليلي", callback_data=f"night_menu_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_keywords_menu(group_id):
    group_str = str(group_id)
    keywords = settings[group_str]['banned_keywords']
    keyword_action = settings[group_str]['keyword_action']
    keyword_duration = settings[group_str]['keyword_mute_duration']
    dur_value, dur_unit = seconds_to_value_unit(keyword_duration)
    
    text = "🔤 <b>إدارة الكلمات الممنوعة</b>\n\n"
    text += f"• عدد الكلمات: {len(keywords)}\n"
    text += f"• العقوبة: {mode_to_text(keyword_action)}\n"
    if keyword_action in ['mute', 'mute_then_ban']:
        text += f"• مدة الكتم: {dur_value} {unit_to_text_dict.get(dur_unit, dur_unit)}\n\n"
    
    if keywords:
        text += "📝 <b>الكلمات الحالية:</b>\n"
        for i, word in enumerate(keywords[:10], 1):
            text += f"{i}. {word}\n"
        if len(keywords) > 10:
            text += f"... و{len(keywords)-10} كلمة أخرى\n"
    else:
        text += "⚠️ لا توجد كلمات ممنوعة حالياً\n\n"
    
    text += "📌 <i>يمكنك إضافة كلمات أو روابط كاملة للكشف عنها</i>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة كلمة", callback_data=f"add_keyword_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف كلمة", callback_data=f"remove_keyword_{group_id}")],
        [InlineKeyboardButton(text="⚖️ تغيير العقوبة", callback_data=f"keyword_action_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_links_menu(group_id):
    group_str = str(group_id)
    links = settings[group_str]['banned_links']
    link_action = settings[group_str]['link_action']
    
    text = "🔗 <b>إدارة الروابط الممنوعة</b>\n\n"
    text += f"• عدد الروابط: {len(links)}\n"
    text += f"• العقوبة: {'حذف الرسالة فقط' if link_action == 'delete' else mode_to_text(link_action)}\n\n"
    
    if links:
        text += "📝 <b>الروابط الحالية:</b>\n"
        for i, link in enumerate(links[:5], 1):
            text += f"{i}. {link}\n"
        if len(links) > 5:
            text += f"... و{len(links)-5} رابط آخر\n"
    else:
        text += "⚠️ لا توجد روابط ممنوعة حالياً\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ إضافة رابط", callback_data=f"add_link_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف رابط", callback_data=f"remove_link_{group_id}")],
        [InlineKeyboardButton(text="⚖️ تغيير العقوبة", callback_data=f"link_action_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_countries_menu(group_id):
    group_str = str(group_id)
    banned_countries = settings[group_str]['banned_countries']
    country_action = settings[group_str]['country_action']
    detection_enabled = settings[group_str]['country_detection_enabled']
    
    text = "🌍 <b>إدارة حظر الدول</b>\n\n"
    text += f"• كشف الدولة: {'✅ مفعل' if detection_enabled else '❌ معطل'}\n"
    text += f"• العقوبة: {mode_to_text(country_action)}\n"
    text += f"• عدد الدول المحظورة: {len(banned_countries)}\n\n"
    
    if banned_countries:
        text += "🚫 <b>الدول المحظورة:</b>\n"
        for i, country in enumerate(banned_countries[:5], 1):
            try:
                flag_emoji = flag.flag(country[:2])
            except:
                flag_emoji = "🏴"
            text += f"{flag_emoji} {country}\n"
        if len(banned_countries) > 5:
            text += f"... و{len(banned_countries)-5} دولة أخرى\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'❌ تعطيل' if detection_enabled else '✅ تفعيل'} كشف الدولة", 
                              callback_data=f"toggle_country_detect_{group_id}")],
        [InlineKeyboardButton(text="➕ إضافة دولة", callback_data=f"add_country_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف دولة", callback_data=f"remove_country_{group_id}")],
        [InlineKeyboardButton(text="⚖️ تغيير العقوبة", callback_data=f"country_action_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_members_menu(group_id):
    group_str = str(group_id)
    exempted_users = settings[group_str]['exempted_users']
    membership_duration = settings[group_str]['membership_duration']
    membership_unit = settings[group_str]['membership_unit']
    membership_action = settings[group_str]['membership_action']
    
    text = "👤 <b>إدارة الأعضاء</b>\n\n"
    text += f"• الأعضاء المستثنون: {len(exempted_users)} عضو\n"
    if membership_duration > 0:
        text += f"• حماية الأعضاء الجدد: {membership_duration} {unit_to_text_dict.get(membership_unit, membership_unit)}\n"
        text += f"• عقوبة المخالفة: {mode_to_text(membership_action)}\n\n"
    else:
        text += "• حماية الأعضاء الجدد: ❌ معطلة\n\n"
    
    text += "<i>يمكنك استثناء أعضاء من العقوبات أو تفعيل حماية للأعضاء الجدد</i>"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 إضافة مستثنى", callback_data=f"add_exempt_{group_id}")],
        [InlineKeyboardButton(text="🗑️ حذف مستثنى", callback_data=f"remove_exempt_{group_id}")],
        [InlineKeyboardButton(text="🛡️ حماية الأعضاء الجدد", callback_data=f"membership_protection_{group_id}")],
        [InlineKeyboardButton(text="📋 قائمة المستثنين", callback_data=f"list_exempt_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"protection_menu_{group_id}")]
    ])
    
    return text, keyboard

def get_stats_panel(group_id):
    group_str = str(group_id)
    violations = settings[group_str].get('violations', {})
    warnings = settings[group_str].get('warnings', {})
    
    total_violations = sum(violations.values())
    total_warnings = sum(warnings.values())
    
    text = "📊 <b>إحصائيات الحماية</b>\n\n"
    text += f"• إجمالي المخالفات: {total_violations}\n"
    text += f"• إجمالي التحذيرات: {total_warnings}\n"
    text += f"• الأعضاء المخالفون: {len(violations)}\n"
    text += f"• الأعضاء المحذرون: {len(warnings)}\n\n"
    
    if violations:
        text += "🔴 <b>أكثر الأعضاء مخالفة:</b>\n"
        sorted_violations = sorted(violations.items(), key=lambda x: x[1], reverse=True)[:5]
        for user_id, count in sorted_violations:
            text += f"• العضو {user_id}: {count} مخالفة\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ مسح الإحصائيات", callback_data=f"clear_stats_{group_id}")],
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

    if data == "main_menu":
        await start_command(callback.message)
        return
        
    if data == "more_info":
        more_info_text = (
            "🛡️ <b>الحارس الأمني المتقدم – مميزات إضافية</b>\n\n"
            "🔥 <b>المميزات الجديدة:</b>\n"
            "✅ نظام كلمات مفتاحية ممنوعة مع عقوبات قابلة للتخصيص\n"
            "✅ كشف الروابط الممنوعة (Google, X, Facebook, إلخ)\n"
            "✅ حظر دول معينة من الانضمام مع كشف تلقائي\n"
            "✅ حماية الأعضاء الجدد (دقيقة، ساعة، يوم، أسبوع)\n"
            "✅ استثناء أعضاء محددين من العقوبات\n"
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

    # الأقسام الرئيسية
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
    
    if data.startswith("protection_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_protection_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("keywords_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_keywords_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("links_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_links_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("countries_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_countries_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("members_menu_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_members_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("stats_"):
        group_id = int(data.split("_")[1])
        text, keyboard = get_stats_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إدارة الكلمات الممنوعة
    if data.startswith("add_keyword_"):
        group_id = int(data.split("_")[2])
        await callback.message.answer(
            "📝 <b>أرسل الكلمة أو العبارة الممنوعة:</b>\n\n"
            "<i>يمكن أن تكون كلمة، عبارة، أو حتى رابط كامل</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"keywords_menu_{group_id}")]
            ])
        )
        # هنا يمكن إضافة حالة انتظار للإدخال
        return
    
    if data.startswith("keyword_action_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        
        text = "⚖️ <b>اختر عقوبة الكلمات الممنوعة:</b>\n\n"
        text += f"العقوبة الحالية: {mode_to_text(settings[group_str]['keyword_action'])}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ حذف الرسالة فقط", callback_data=f"set_keyword_action_delete_{group_id}")],
            [InlineKeyboardButton(text="🔇 كتم", callback_data=f"set_keyword_action_mute_{group_id}")],
            [InlineKeyboardButton(text="🚫 حظر", callback_data=f"set_keyword_action_ban_{group_id}")],
            [InlineKeyboardButton(text="⚠️ تحذير", callback_data=f"set_keyword_action_warn_{group_id}")],
            [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"keywords_menu_{group_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إدارة الروابط
    if data.startswith("link_action_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        
        text = "⚖️ <b>اختر عقوبة الروابط الممنوعة:</b>\n\n"
        text += f"العقوبة الحالية: {'حذف الرسالة فقط' if settings[group_str]['link_action'] == 'delete' else mode_to_text(settings[group_str]['link_action'])}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ حذف الرسالة فقط", callback_data=f"set_link_action_delete_{group_id}")],
            [InlineKeyboardButton(text="🔇 كتم", callback_data=f"set_link_action_mute_{group_id}")],
            [InlineKeyboardButton(text="🚫 حظر", callback_data=f"set_link_action_ban_{group_id}")],
            [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"links_menu_{group_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إدارة الدول
    if data.startswith("toggle_country_detect_"):
        group_id = int(data.split("_")[3])
        group_str = str(group_id)
        settings[group_str]['country_detection_enabled'] = not settings[group_str]['country_detection_enabled']
        await save_settings_to_tg()
        
        text, keyboard = get_countries_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    if data.startswith("country_action_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        
        text = "⚖️ <b>اختر عقوبة الدول المحظورة:</b>\n\n"
        text += f"العقوبة الحالية: {mode_to_text(settings[group_str]['country_action'])}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔇 كتم", callback_data=f"set_country_action_mute_{group_id}")],
            [InlineKeyboardButton(text="🚫 حظر", callback_data=f"set_country_action_ban_{group_id}")],
            [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"countries_menu_{group_id}")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # إدارة الأعضاء
    if data.startswith("membership_protection_"):
        group_id = int(data.split("_")[2])
        await callback.message.answer(
            "🛡️ <b>إعداد حماية الأعضاء الجدد</b>\n\n"
            "أرسل مدة الحماية بالتنسيق التالي:\n"
            "<code>عدد الوحدة</code>\n\n"
            "<b>مثال:</b>\n"
            "<code>1 ساعة</code> - لحماية ساعة واحدة\n"
            "<code>7 أيام</code> - لحماية أسبوع\n"
            "<code>30 دقيقة</code> - لحماية نصف ساعة\n\n"
            "الوحدات المتاحة: دقيقة، ساعة، يوم، أسبوع، شهر، سنة",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"members_menu_{group_id}")]
            ])
        )
        return
    
    if data.startswith("clear_stats_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        settings[group_str]['violations'] = {}
        settings[group_str]['warnings'] = {}
        await save_settings_to_tg()
        
        await callback.answer("✅ تم مسح الإحصائيات", show_alert=True)
        text, keyboard = get_stats_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return
    
    # تعيين الإجراءات
    if data.startswith("set_"):
        parts = data.split("_")
        action_type = parts[1]  # keyword, link, country
        action = parts[3]
        group_id = int(parts[4])
        group_str = str(group_id)
        
        if action_type == "keyword":
            settings[group_str]['keyword_action'] = action
        elif action_type == "link":
            settings[group_str]['link_action'] = action
        elif action_type == "country":
            settings[group_str]['country_action'] = action
        
        await save_settings_to_tg()
        await callback.answer(f"✅ تم تعيين العقوبة: {action}", show_alert=True)
        
        # العودة للقائمة المناسبة
        if action_type == "keyword":
            text, keyboard = get_keywords_menu(group_id)
        elif action_type == "link":
            text, keyboard = get_links_menu(group_id)
        elif action_type == "country":
            text, keyboard = get_countries_menu(group_id)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

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

    # التحقق من الأعضاء المستثنين
    if user_id in settings[group_str]['exempted_users']:
        return

    # التحقق من الوضع الليلي
    if settings[group_str]['night_mode_enabled']:
        start = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
        end = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
        now = datetime.now().time()
        is_night = (start <= now < end) if start < end else (start <= now or now < end)
        if is_night and not await is_admin(chat_id, user_id):
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
        country = await get_user_country(user_id)
        if country and country in settings[group_str]['banned_countries']:
            action = settings[group_str]['country_action']
            await handle_violation(chat_id, user_id, f"الدولة المحظورة: {country}", action, group_str, full_name)
            await message.delete()
            return

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

async def handle_violation(chat_id: int, user_id: int, reason: str, action: str, group_str: str, full_name: str):
    """معالجة المخالفات بأنواعها المختلفة"""
    
    # تسجيل المخالفة
    if 'violations' not in settings[group_str]:
        settings[group_str]['violations'] = {}
    
    violations_count = settings[group_str]['violations'].get(user_id, 0) + 1
    settings[group_str]['violations'][user_id] = violations_count
    
    # تحديد العقوبة بناءً على الإعدادات
    if action == 'delete_only':
        notify = (
            f"🗑️ <b>تم حذف رسالة مخالفة</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 <b>السبب:</b> {reason}\n"
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
                f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
                f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
            )
            msg = await bot.send_message(chat_id, notify)
            asyncio.create_task(delete_after_delay(msg, 120))
    
    elif action == 'mute':
        mute_duration = settings[group_str]['mute_duration']
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
            f"⏰ <b>المدة:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
            f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
            f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
        )
        msg = await bot.send_message(chat_id, notify)
        asyncio.create_task(delete_after_delay(msg, 120))
    
    elif action == 'mute_then_ban':
        mute_duration = settings[group_str]['mute_duration']
        
        if violations_count == 1:
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
                    f"🔢 <b>عدد المخالفات:</b> {violations_count}\n\n"
                    f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
                )
                msg = await bot.send_message(chat_id, notify)
                asyncio.create_task(delete_after_delay(msg, 120))
    
    elif action == 'warn':
        if 'warnings' not in settings[group_str]:
            settings[group_str]['warnings'] = {}
        
        warnings_count = settings[group_str]['warnings'].get(user_id, 0) + 1
        settings[group_str]['warnings'][user_id] = warnings_count
        
        if warnings_count >= 3:
            if not await is_banned(chat_id, user_id):
                await bot.ban_chat_member(chat_id, user_id)
                notify = (
                    f"🚫 <b>تم حظر العضو بعد 3 تحذيرات</b>\n\n"
                    f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                    f"📛 <b>السبب:</b> {reason}\n"
                    f"⚠️ <b>عدد التحذيرات:</b> {warnings_count}\n\n"
                    f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
                )
            else:
                notify = (
                    f"⚠️ <b>تحذير #{warnings_count}</b>\n\n"
                    f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                    f"📛 <b>السبب:</b> {reason}\n"
                    f"⚠️ <b>تحذير:</b> عند الوصول لـ 3 تحذيرات = حظر دائم\n\n"
                    f"🛡️ <i>المجموعة محمية بواسطة الحارس الأمني</i>"
                )
        else:
            notify = (
                f"⚠️ <b>تحذير #{warnings_count}</b>\n\n"
                f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                f"📛 <b>السبب:</b> {reason}\n"
                f"⚠️ <b>تحذير:</b> عند الوصول لـ 3 تحذيرات = حظر دائم\n\n"
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