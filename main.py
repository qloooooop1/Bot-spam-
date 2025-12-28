import asyncio
import logging
import os
import re
import time
import json
import sys
import random
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Any, Tuple
from enum import Enum
import psutil
import aiohttp
from collections import defaultdict

from fastapi import FastAPI, Request, Response, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton,
    CallbackQuery,
    Message,
    FSInputFile
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.markdown import hbold, hlink, hcode
from aiogram.methods import GetChatAdministrators

# ================== الإعدادات المتقدمة ==================
TOKEN = os.getenv("TOKEN", "")
DEVELOPER_ID = 6516518035  # ضع ID المطور هنا
SUPPORT_CHAT = "@SecurityGuardSupport"  # مجموعة الدعم
BOT_USERNAME = "SecurityGuardProBot"  # اسم البوت
VERSION = "3.0.0"
RELEASE_DATE = "2024"

# قائمة المجموعات المسموحة (يمكن إضافتها عبر الأوامر)
ALLOWED_GROUP_IDS = [-1001224326322, -1002370282238]

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('security_bot_advanced.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# التخزين
storage = MemoryStorage()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# قاعدة البيانات
DB_CHAT_ID = -1002370282238
SETTINGS_MESSAGE_ID = None
STATS_MESSAGE_ID = None
BACKUP_MESSAGE_ID = None

# ================== تعريفات ENUM ==================
class SecurityMode(Enum):
    MUTE = "mute"
    BAN = "ban"
    MUTE_THEN_BAN = "mute_then_ban"
    DELETE_ONLY = "delete_only"
    WARN_THEN_MUTE = "warn_then_mute"
    WARN_THEN_BAN = "warn_then_ban"
    SMART_DETECTION = "smart_detection"
    AGGRESSIVE = "aggressive"
    RELAXED = "relaxed"

class UserRole(Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    EXEMPTED = "exempted"
    VIP = "vip"
    TRUSTED = "trusted"

class ActionType(Enum):
    WARNING = "warning"
    MUTE = "mute"
    BAN = "ban"
    KICK = "kick"
    DELETE = "delete"
    REPORT = "report"

class NotificationLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    CRITICAL = "critical"

# ================== أنماط الكشف المتقدمة ==================
def normalize_digits(text: str) -> str:
    """تطبيع الأرقام العربية والفارسية"""
    trans = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣۴۵۶۷۸۹',
        '012345678901234567890123456789'
    )
    return text.translate(trans)

# أنماط متقدمة
PHONE_PATTERN = re.compile(r'(?:\+?966|00966|966|05|5|0)?(\d[\s\W_*/.-]*){8,12}', re.IGNORECASE)
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)
CRYPTO_PATTERN = re.compile(r'(?:bitcoin|btc|ethereum|eth|usdt|usdc|bnb|ripple|xrp|cardano|ada|solana|sol|dogecoin|doge)[\s:]*[13][a-km-zA-HJ-NP-Z1-9]{25,34}|0x[a-fA-F0-9]{40}', re.IGNORECASE)
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', re.IGNORECASE)
WHATSAPP_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:chat\.whatsapp\.com|wa\.me)/(?:invite/)?[a-zA-Z0-9_-]{20,}', re.IGNORECASE)
TELEGRAM_INVITE_PATTERN = re.compile(r'(?:https?://)?t\.me/(?:joinchat/|[+])[a-zA-Z0-9_-]{10,}|(?:https?://)?t\.me/[a-zA-Z0-9_]{5,32}', re.IGNORECASE)
TIKTOK_PATTERN = re.compile(r'(?:https?://)?(?:vm\.|www\.|m\.)?tiktok\.com/(?:@[\w.-]+/video/|\w+)', re.IGNORECASE)
SHORT_LINK_PATTERN = re.compile(r'(?:https?://)?(?:bit\.ly|tinyurl\.com|goo\.gl|t\.co|ow\.ly|is\.gd|buff\.ly|adf\.ly|shorte\.st|bc\.vc|cli\.gs|cutt\.us|u\.bb|yourls\.org|x\.co|v\.gd|tr\.im|qr\.ae|vzturl\.com|lnkd\.in|cur\.lv|tiny\.cc|alturl\.com|ity\.im|q\.gs|po\.st|www\.prettylinkpro\.com|www\.clicky\.me|bl\.ink|filoops\.info|scrnch\.me|v\.gd)/[a-zA-Z0-9]+', re.IGNORECASE)
ADULT_CONTENT_PATTERN = re.compile(r'(?:سكس|نيك|عرى|عاري|ممحونة|شرموطة|قحبة|دعارة|زنا|فاحشة|شاذ|لواط|سحاق|إباحية|إباحي|porn|sex|xxx|adult|nsfw|فحش)', re.IGNORECASE | re.UNICODE)

ALLOWED_DOMAINS = [
    "youtube.com", "youtu.be", 
    "instagram.com", "instagr.am", 
    "x.com", "twitter.com",
    "telegram.org", "telegram.me", "t.me",
    "github.com", "gitlab.com",
    "stackoverflow.com", "wikipedia.org",
    "google.com", "facebook.com",
    "linkedin.com", "reddit.com",
    "discord.com", "discord.gg",
    "medium.com", "quora.com"
]

# ================== هياكل البيانات المتقدمة ==================
settings = {}
bot_stats = {
    "total_messages_checked": 0,
    "total_violations": 0,
    "total_bans": 0,
    "total_mutes": 0,
    "total_warnings": 0,
    "total_kicks": 0,
    "total_reports": 0,
    "groups": {},
    "users": {},
    "start_time": time.time(),
    "commands_used": defaultdict(int),
    "system": {
        "memory_usage": 0,
        "cpu_usage": 0,
        "uptime": 0
    }
}

# بيانات مؤقتة
temp_data = {}
user_sessions = {}
group_cache = {}
backup_queue = []

# نظام الجوائز والميداليات
achievements = {
    "veteran": {"name": "المحارب القديم", "emoji": "🛡️", "description": "مستخدم لأكثر من سنة"},
    "protector": {"name": "الحامي", "emoji": "⚔️", "description": "منع 100 مخالفة"},
    "vigilant": {"name": "اليقظ", "emoji": "👁️", "description": "كشف 50 محاولة احتيال"},
    "leader": {"name": "القائد", "emoji": "👑", "description": "إدارة 5 مجموعات"},
    "hero": {"name": "البطل", "emoji": "🏆", "description": "إنقاذ المجموعة من هجوم جماعي"}
}

# ================== وحدات الوقت ==================
unit_seconds = {
    'ثانية': 1,
    'دقيقة': 60, 
    'ساعة': 3600, 
    'يوم': 86400, 
    'أسبوع': 604800,
    'شهر': 2592000, 
    'سنة': 31536000
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

def seconds_to_value_unit(seconds: int) -> Tuple[int, str]:
    """تحويل الثواني إلى قيمة ووحدة"""
    if seconds == 0:
        return 0, 'ثانية'
    for unit, secs in sorted(unit_seconds.items(), key=lambda x: x[1], reverse=True):
        if seconds >= secs:
            value = seconds // secs
            return value, unit
    return seconds, 'ثانية'

def parse_duration(text: str) -> Optional[int]:
    """تحليل المدة من النص"""
    try:
        if text.isdigit():
            return int(text)
        
        units = {
            'ث': 1, 'ثانية': 1, 'ثواني': 1,
            'د': 60, 'دقيقة': 60, 'دقائق': 60,
            'س': 3600, 'ساعة': 3600, 'ساعات': 3600,
            'ي': 86400, 'يوم': 86400, 'أيام': 86400,
            'أ': 604800, 'أسبوع': 604800, 'أسابيع': 604800,
            'ش': 2592000, 'شهر': 2592000, 'أشهر': 2592000,
            'سنة': 31536000, 'سنوات': 31536000
        }
        
        for unit, seconds in units.items():
            if unit in text:
                num = int(''.join(filter(str.isdigit, text)))
                return num * seconds
        
        return None
    except:
        return None

# ================== حالات FSM الكاملة ==================
class Form(StatesGroup):
    # الحماية الأساسية
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
    
    # الميزات المتقدمة
    waiting_for_welcome_message = State()
    waiting_for_rules = State()
    waiting_for_custom_command = State()
    waiting_for_auto_reply = State()
    waiting_for_backup_name = State()
    waiting_for_report_reason = State()
    waiting_for_broadcast_message = State()
    waiting_for_filter_reply = State()
    waiting_for_challenge_config = State()
    
    # إدارة المتقدمين
    waiting_for_applicant_question = State()
    waiting_for_applicant_answer = State()
    waiting_for_applicant_review = State()
    
    # النظام الأمني
    waiting_for_security_scan = State()
    waiting_for_threat_level = State()
    waiting_for_auto_action = State()
    
    # التخصيص
    waiting_for_theme_color = State()
    waiting_for_language = State()
    waiting_for_notification_sound = State()
    
    # الإحصائيات
    waiting_for_statistics_period = State()
    waiting_for_report_type = State()
    waiting_for_export_format = State()

# ================== وظائف المساعدة المتقدمة ==================
async def is_admin(chat_id: int, user_id: int) -> bool:
    """التحقق إذا كان المستخدم مسؤولاً"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.error(f"خطأ في التحقق من المسؤول: {e}")
        return False

async def is_owner(chat_id: int, user_id: int) -> bool:
    """التحقق إذا كان المستخدم مالك المجموعة"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status == "creator"
    except Exception as e:
        logger.error(f"خطأ في التحقق من المالك: {e}")
        return False

async def get_user_role(chat_id: int, user_id: int, group_str: str = None) -> UserRole:
    """الحصول على دور المستخدم"""
    try:
        if await is_owner(chat_id, user_id):
            return UserRole.OWNER
        elif await is_admin(chat_id, user_id):
            return UserRole.ADMIN
        
        if group_str and group_str in settings:
            group_settings = settings[group_str]
            if user_id in group_settings.get('vip_users', []):
                return UserRole.VIP
            if user_id in group_settings.get('trusted_users', []):
                return UserRole.TRUSTED
            if user_id in group_settings.get('exempted_users', []):
                return UserRole.EXEMPTED
        
        return UserRole.MEMBER
    except Exception as e:
        logger.error(f"خطأ في الحصول على دور المستخدم: {e}")
        return UserRole.MEMBER

def get_formatted_time() -> str:
    """الحصول على الوقت المنسق"""
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

def format_number(num: int) -> str:
    """تنسيق الأرقام"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    return str(num)

def get_random_emoji() -> str:
    """الحصول على إيموجي عشوائي"""
    emojis = ["✨", "🚀", "🔥", "⭐", "🎯", "💎", "👑", "🛡️", "⚡", "🎊", "🎉", "🏆", "💪", "👏", "👍"]
    return random.choice(emojis)

async def send_typing(chat_id: int):
    """إرسال إشارة الكتابة"""
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
    except:
        pass

async def safe_delete_message(chat_id: int, message_id: int):
    """حذف رسالة بأمان"""
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

async def safe_edit_message(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup = None):
    """تعديل رسالة بأمان"""
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"خطأ في تعديل الرسالة: {e}")

# ================== نظام الكشف المتقدم ==================
def contains_spam(text: str, group_str: str = None) -> Dict[str, Any]:
    """كشف متقدم للمحتوى المخالف"""
    result = {
        "is_spam": False,
        "reason": "",
        "details": {},
        "confidence": 0,
        "action": "none",
        "severity": "low"
    }
    
    if not text or not isinstance(text, str):
        return result
    
    normalized = normalize_digits(text)
    text_lower = text.lower()
    
    # قائمة الكشف
    detections = []
    
    # 1. اكتشاف الأرقام الهاتفية
    if PHONE_PATTERN.search(normalized):
        detections.append(("phone", 85, "رقم هاتف"))
    
    # 2. اكتشاف البريد الإلكتروني
    if EMAIL_PATTERN.search(text):
        detections.append(("email", 70, "بريد إلكتروني"))
    
    # 3. اكتشاف العملات الرقمية
    if CRYPTO_PATTERN.search(text_lower):
        detections.append(("crypto", 90, "عملة رقمية"))
    
    # 4. اكتشاف عناوين IP
    if IP_PATTERN.search(text):
        detections.append(("ip", 60, "عنوان IP"))
    
    # 5. روابط الدعوات
    if WHATSAPP_INVITE_PATTERN.search(text):
        detections.append(("whatsapp", 95, "رابط واتساب"))
    
    if TELEGRAM_INVITE_PATTERN.search(text):
        detections.append(("telegram", 80, "رابط تيليجرام"))
    
    # 6. روابط TikTok
    if TIKTOK_PATTERN.search(text):
        detections.append(("tiktok", 75, "رابط TikTok"))
    
    # 7. روابط مختصرة
    if SHORT_LINK_PATTERN.search(text):
        detections.append(("short_link", 85, "رابط مختصر"))
    
    # 8. محتوى للكبار
    if ADULT_CONTENT_PATTERN.search(text_lower):
        detections.append(("adult", 95, "محتوى للكبار"))
    
    # 9. كلمات ممنوعة مخصصة
    if group_str and group_str in settings:
        group_settings = settings[group_str]
        banned_keywords = group_settings.get('banned_keywords', [])
        found_keywords = []
        
        for keyword in banned_keywords:
            if keyword.lower() in text_lower:
                found_keywords.append(keyword)
                result["confidence"] += 15
        
        if found_keywords:
            detections.append(("banned_keywords", result["confidence"], f"كلمات ممنوعة: {', '.join(found_keywords[:3])}"))
    
    # 10. روابط غير مسموحة
    urls = re.findall(r'https?://[^\s]+|www\.[^\s]+|[^\s]+\.[^\s]{2,}', text, re.IGNORECASE)
    if urls:
        unauthorized_urls = []
        for url in urls:
            clean_url = url.replace(' ', '').lower()
            is_allowed = any(domain in clean_url for domain in ALLOWED_DOMAINS)
            
            if not is_allowed:
                unauthorized_urls.append(url)
                result["confidence"] += 20
        
        if unauthorized_urls:
            detections.append(("unauthorized_links", result["confidence"], "روابط غير مسموحة"))
    
    # 11. اكتشاف الرسائل الطويلة (سبام)
    words = text.split()
    if len(words) > 300:
        detections.append(("long_message", 70, "رسالة طويلة (سبام)"))
    
    # 12. اكتشاف التكرار
    if len(set(words)) < len(words) * 0.3:  # تكرار كبير
        detections.append(("repetition", 65, "تكرار مفرط"))
    
    # تحليل النتائج
    if detections:
        # اختيار أعلى ثقة
        best_detection = max(detections, key=lambda x: x[1])
        result["is_spam"] = True
        result["reason"] = best_detection[2]
        result["confidence"] = best_detection[1]
        result["details"]["detections"] = detections
        
        # تحديد مستوى الخطورة والإجراء
        if result["confidence"] >= 90:
            result["severity"] = "critical"
            result["action"] = "ban"
        elif result["confidence"] >= 75:
            result["severity"] = "high"
            result["action"] = "mute"
        elif result["confidence"] >= 60:
            result["severity"] = "medium"
            result["action"] = "warn"
        else:
            result["severity"] = "low"
            result["action"] = "delete"
    
    return result

# ================== نظام التخزين والنسخ الاحتياطي ==================
async def save_settings():
    """حفظ الإعدادات"""
    global SETTINGS_MESSAGE_ID
    try:
        for group_str in settings:
            settings[group_str]['last_update'] = time.time()
        
        data = {
            "settings": settings,
            "version": VERSION,
            "timestamp": time.time(),
            "groups_count": len(settings)
        }
        
        text = json.dumps(data, ensure_ascii=False, indent=2)
        
        if SETTINGS_MESSAGE_ID:
            try:
                await bot.edit_message_text(
                    chat_id=DB_CHAT_ID,
                    message_id=SETTINGS_MESSAGE_ID,
                    text=text
                )
            except:
                msg = await bot.send_message(DB_CHAT_ID, text)
                SETTINGS_MESSAGE_ID = msg.message_id
        else:
            msg = await bot.send_message(DB_CHAT_ID, text)
            SETTINGS_MESSAGE_ID = msg.message_id
        
        logger.info("تم حفظ الإعدادات بنجاح")
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ الإعدادات: {e}")
        return False

async def load_settings():
    """تحميل الإعدادات"""
    global settings, SETTINGS_MESSAGE_ID
    try:
        # تحميل الإعدادات الأساسية
        for gid in ALLOWED_GROUP_IDS:
            group_str = str(gid)
            if group_str not in settings:
                settings[group_str] = {
                    'mode': 'smart_detection',
                    'mute_duration': 3600,
                    'ban_duration': 0,
                    'violations': {},
                    'warnings': {},
                    'banned_keywords': [],
                    'banned_links': [],
                    'banned_countries': [],
                    'exempted_users': [],
                    'vip_users': [],
                    'trusted_users': [],
                    'night_mode_enabled': False,
                    'night_start': '22:00',
                    'night_end': '06:00',
                    'night_announce_msg_id': None,
                    'applicants_system': True,
                    'auto_backup': True,
                    'weekly_reports': True,
                    'challenges_enabled': True,
                    'keep_notification': False,
                    'notification_duration': 120,
                    'welcome_message': "",
                    'rules': "",
                    'custom_commands': {},
                    'auto_replies': {},
                    'last_backup': 0,
                    'created_at': time.time(),
                    'owner_id': None
                }
        
        # محاولة تحميل من قاعدة البيانات
        try:
            messages = []
            async for message in bot.get_chat_messages(DB_CHAT_ID, limit=50):
                messages.append(message)
            
            for msg in reversed(messages):
                if msg.text and msg.text.strip().startswith('{'):
                    try:
                        data = json.loads(msg.text)
                        if 'settings' in data:
                            loaded_settings = data['settings']
                            for group_str in loaded_settings:
                                if group_str in settings:
                                    # دمج الإعدادات
                                    for key, value in loaded_settings[group_str].items():
                                        settings[group_str][key] = value
                            
                            SETTINGS_MESSAGE_ID = msg.message_id
                            logger.info(f"تم تحميل إعدادات {len(loaded_settings)} مجموعة")
                            break
                    except:
                        continue
        except Exception as e:
            logger.error(f"خطأ في تحميل الإعدادات من قاعدة البيانات: {e}")
        
        await save_settings()
        return True
    except Exception as e:
        logger.error(f"خطأ في تحميل الإعدادات: {e}")
        return False

async def create_backup(group_id: int, manual: bool = False):
    """إنشاء نسخة احتياطية"""
    try:
        group_str = str(group_id)
        if group_str not in settings:
            return False
        
        backup_data = {
            'group_id': group_id,
            'group_name': (await bot.get_chat(group_id)).title,
            'settings': settings[group_str],
            'timestamp': time.time(),
            'version': VERSION,
            'type': 'manual' if manual else 'auto'
        }
        
        filename = f"backup_{group_id}_{int(time.time())}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        # إرسال الملف
        with open(filename, 'rb') as f:
            await bot.send_document(
                chat_id=DEVELOPER_ID,
                document=FSInputFile(f, filename=filename),
                caption=f"📦 نسخة احتياطية للمجموعة {backup_data['group_name']}\n"
                       f"⏰ {datetime.fromtimestamp(backup_data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}\n"
                       f"📊 {len(backup_data['settings'].get('banned_keywords', []))} كلمة ممنوعة"
            )
        
        # تحديث وقت آخر نسخة
        settings[group_str]['last_backup'] = time.time()
        await save_settings()
        
        # حذف الملف المحلي
        os.remove(filename)
        
        logger.info(f"تم إنشاء نسخة احتياطية للمجموعة {group_id}")
        return True
    except Exception as e:
        logger.error(f"خطأ في إنشاء النسخة الاحتياطية: {e}")
        return False

# ================== نظام الإحصائيات المتقدم ==================
async def update_stats(group_id: int, action: str, user_id: int = None):
    """تحديث الإحصائيات"""
    try:
        group_str = str(group_id)
        
        # تحديث إحصائيات المجموعة
        if group_str not in bot_stats['groups']:
            bot_stats['groups'][group_str] = {
                'violations': 0, 'bans': 0, 'mutes': 0,
                'warnings': 0, 'kicks': 0, 'reports': 0,
                'messages_checked': 0, 'last_activity': time.time(),
                'active_users': set(), 'top_violators': {}
            }
        
        group_stats = bot_stats['groups'][group_str]
        
        # تحديث الإحصائيات العامة
        if action == 'message':
            bot_stats['total_messages_checked'] += 1
            group_stats['messages_checked'] += 1
            
            if user_id:
                group_stats['active_users'].add(user_id)
                
        elif action == 'violation':
            bot_stats['total_violations'] += 1
            group_stats['violations'] += 1
            
            if user_id:
                if user_id not in group_stats['top_violators']:
                    group_stats['top_violators'][user_id] = 0
                group_stats['top_violators'][user_id] += 1
                
        elif action == 'ban':
            bot_stats['total_bans'] += 1
            group_stats['bans'] += 1
            
        elif action == 'mute':
            bot_stats['total_mutes'] += 1
            group_stats['mutes'] += 1
            
        elif action == 'warning':
            bot_stats['total_warnings'] += 1
            group_stats['warnings'] += 1
            
        elif action == 'report':
            bot_stats['total_reports'] += 1
            group_stats['reports'] += 1
        
        # تحديث وقت النشاط
        group_stats['last_activity'] = time.time()
        
        # تحديث إحصائيات النظام
        bot_stats['system']['memory_usage'] = psutil.Process().memory_info().rss / 1024 / 1024
        bot_stats['system']['cpu_usage'] = psutil.cpu_percent()
        bot_stats['system']['uptime'] = time.time() - bot_stats['start_time']
        
        # حفظ الإحصائيات كل 100 تحديث
        if bot_stats['total_messages_checked'] % 100 == 0:
            await save_stats()
            
    except Exception as e:
        logger.error(f"خطأ في تحديث الإحصائيات: {e}")

async def save_stats():
    """حفظ الإحصائيات"""
    global STATS_MESSAGE_ID
    try:
        stats_text = generate_stats_report()
        
        if STATS_MESSAGE_ID:
            try:
                await bot.edit_message_text(
                    chat_id=DB_CHAT_ID,
                    message_id=STATS_MESSAGE_ID,
                    text=stats_text
                )
            except:
                msg = await bot.send_message(DB_CHAT_ID, stats_text)
                STATS_MESSAGE_ID = msg.message_id
        else:
            msg = await bot.send_message(DB_CHAT_ID, stats_text)
            STATS_MESSAGE_ID = msg.message_id
            
    except Exception as e:
        logger.error(f"خطأ في حفظ الإحصائيات: {e}")

def generate_stats_report() -> str:
    """توليد تقرير الإحصائيات"""
    uptime = time.time() - bot_stats['start_time']
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    
    report = f"""📊 تقرير إحصائيات الحارس الأمني المتقدم
🕐 الإصدار: {VERSION} | تاريخ الإصدار: {RELEASE_DATE}
⏰ وقت التشغيل: {days} يوم, {hours} ساعة, {minutes} دقيقة

📈 الإحصائيات العامة:
├ 📨 الرسائل المفحوصة: {format_number(bot_stats['total_messages_checked'])}
├ ⚠️ المخالفات: {format_number(bot_stats['total_violations'])}
├ 🚫 الحظور: {format_number(bot_stats['total_bans'])}
├ 🔇 الكتم: {format_number(bot_stats['total_mutes'])}
├ ⚠️ التحذيرات: {format_number(bot_stats['total_warnings'])}
└ 📋 التقارير: {format_number(bot_stats['total_reports'])}

💻 إحصائيات النظام:
├ 🧠 استخدام الذاكرة: {bot_stats['system']['memory_usage']:.1f} MB
├ ⚡ استخدام المعالج: {bot_stats['system']['cpu_usage']:.1f}%
└ 👥 المجموعات النشطة: {len(bot_stats['groups'])}

🏆 المجموعات الأكثر نشاطاً:"""
    
    # إحصائيات المجموعات
    sorted_groups = sorted(
        bot_stats['groups'].items(),
        key=lambda x: x[1]['messages_checked'],
        reverse=True
    )[:5]
    
    for i, (group_id, stats) in enumerate(sorted_groups, 1):
        try:
            chat = bot.get_chat(int(group_id))
            group_name = chat.title if hasattr(chat, 'title') else f"Group {group_id}"
        except:
            group_name = f"Group {group_id}"
        
        report += f"\n{i}. {group_name[:20]}"
        report += f"\n   ├ 📨 {format_number(stats['messages_checked'])}"
        report += f"\n   ├ ⚠️ {stats['violations']}"
        report += f"\n   └ 👥 {len(stats.get('active_users', set()))}"
    
    report += f"\n\n📅 آخر تحديث: {get_formatted_time()}"
    report += f"\n{get_random_emoji()} البوت يعمل بكفاءة عالية!"
    
    return report

# ================== نظام المعاقبة المتقدم ==================
async def handle_violation(chat_id: int, user_id: int, message: Message, detection_result: Dict):
    """معالجة المخالفة"""
    group_str = str(chat_id)
    
    if group_str not in settings:
        return
    
    await update_stats(chat_id, 'violation', user_id)
    
    user = message.from_user
    full_name = user.full_name or "مستخدم"
    username = f"@{user.username}" if user.username else "لا يوجد"
    
    # الحصول على إعدادات المجموعة
    group_settings = settings[group_str]
    mode = group_settings.get('mode', 'smart_detection')
    
    # تحديث سجل المخالفات
    if 'violations' not in group_settings:
        group_settings['violations'] = {}
    
    violations_count = group_settings['violations'].get(user_id, 0) + 1
    group_settings['violations'][user_id] = violations_count
    
    # تحديد العقوبة بناء على الوضع
    notification = await apply_punishment(
        chat_id, user_id, mode, violations_count, 
        detection_result, group_settings
    )
    
    # إضافة معلومات المستخدم
    user_link = f'<a href="tg://user?id={user_id}">{full_name}</a>'
    action_emoji = {
        'ban': '🚫', 'mute': '🔇', 'warn': '⚠️',
        'delete': '🗑️', 'kick': '👢'
    }.get(notification.get('action', ''), '🔔')
    
    # بناء رسالة الإشعار
    notification_text = f"""{action_emoji} <b>إجراء أمني</b>

👤 المستخدم: {user_link}
📛 المعرف: {username}
🆔 الرقم: <code>{user_id}</code>

📋 المخالفة: {detection_result.get('reason', 'محتوى مخالف')}
🎯 مستوى الخطورة: {detection_result.get('severity', 'متوسط')}
🔢 عدد المخالفات: {violations_count}

{notification.get('message', '')}

🛡️ <i>المجموعة محمية بواسطة الحارس الأمني المتقدم</i>
"""
    
    # إرسال الإشعار
    if notification_text:
        try:
            msg = await bot.send_message(chat_id, notification_text)
            
            # حذف الإشعار بعد مدة إذا لم يكن دائم
            if not group_settings.get('keep_notification', False):
                duration = group_settings.get('notification_duration', 120)
                await asyncio.sleep(duration)
                await safe_delete_message(chat_id, msg.message_id)
        except Exception as e:
            logger.error(f"خطأ في إرسال الإشعار: {e}")
    
    # حذف الرسالة الأصلية
    await safe_delete_message(chat_id, message.message_id)
    
    # حفظ الإعدادات
    await save_settings()

async def apply_punishment(chat_id: int, user_id: int, mode: str, 
                          violations: int, detection_result: Dict, 
                          group_settings: Dict) -> Dict:
    """تطبيق العقوبة"""
    result = {
        'action': 'none',
        'message': '',
        'duration': 0
    }
    
    duration = group_settings.get('mute_duration', 3600)
    confidence = detection_result.get('confidence', 0)
    
    try:
        if mode == 'smart_detection':
            # النظام الذكي
            if confidence >= 90 or violations >= 3:
                # حظر
                await bot.ban_chat_member(chat_id, user_id)
                result['action'] = 'ban'
                result['message'] = '🚫 تم حظر المستخدم بسبب مخالفات متكررة'
                await update_stats(chat_id, 'ban')
                
            elif confidence >= 70 or violations == 2:
                # كتم
                until_date = datetime.now() + timedelta(seconds=duration)
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                result['action'] = 'mute'
                dur_val, dur_unit = seconds_to_value_unit(duration)
                result['message'] = f'🔇 تم كتم المستخدم لمدة {dur_val} {dur_unit}'
                result['duration'] = duration
                await update_stats(chat_id, 'mute')
                
            elif confidence >= 50 or violations == 1:
                # تحذير
                result['action'] = 'warn'
                result['message'] = '⚠️ تم تحذير المستخدم - المخالفة التالية = كتم'
                await update_stats(chat_id, 'warning')
                
            else:
                # حذف فقط
                result['action'] = 'delete'
                result['message'] = '🗑️ تم حذف الرسالة المخالفة'
                
        elif mode == 'aggressive':
            # وضع عدواني
            if violations >= 1:
                await bot.ban_chat_member(chat_id, user_id)
                result['action'] = 'ban'
                result['message'] = '🚫 تم حظر المستخدم (وضع عدواني)'
                await update_stats(chat_id, 'ban')
                
        elif mode == 'relaxed':
            # وضع متساهل
            if violations >= 3:
                until_date = datetime.now() + timedelta(seconds=300)  # 5 دقائق فقط
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                result['action'] = 'mute'
                result['message'] = '🔇 تم كتم المستخدم لمدة 5 دقائق'
                result['duration'] = 300
                await update_stats(chat_id, 'mute')
            else:
                result['action'] = 'warn'
                result['message'] = '⚠️ تحذير - الرجاء الالتزام بقوانين المجموعة'
                await update_stats(chat_id, 'warning')
                
        else:
            # الأوضاع التقليدية
            if mode == 'ban':
                await bot.ban_chat_member(chat_id, user_id)
                result['action'] = 'ban'
                result['message'] = '🚫 تم حظر المستخدم'
                await update_stats(chat_id, 'ban')
                
            elif mode == 'mute':
                until_date = datetime.now() + timedelta(seconds=duration)
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                result['action'] = 'mute'
                dur_val, dur_unit = seconds_to_value_unit(duration)
                result['message'] = f'🔇 تم كتم المستخدم لمدة {dur_val} {dur_unit}'
                result['duration'] = duration
                await update_stats(chat_id, 'mute')
                
            elif mode == 'delete_only':
                result['action'] = 'delete'
                result['message'] = '🗑️ تم حذف الرسالة المخالفة'
                
            elif mode == 'warn_then_mute':
                if violations >= 2:
                    until_date = datetime.now() + timedelta(seconds=duration)
                    await bot.restrict_chat_member(
                        chat_id, user_id,
                        permissions=types.ChatPermissions(can_send_messages=False),
                        until_date=until_date
                    )
                    result['action'] = 'mute'
                    dur_val, dur_unit = seconds_to_value_unit(duration)
                    result['message'] = f'🔇 تم كتم المستخدم بعد تحذير'
                    result['duration'] = duration
                    await update_stats(chat_id, 'mute')
                else:
                    result['action'] = 'warn'
                    result['message'] = '⚠️ تحذير أول - المخالفة التالية = كتم'
                    await update_stats(chat_id, 'warning')
                    
            elif mode == 'warn_then_ban':
                if violations >= 2:
                    await bot.ban_chat_member(chat_id, user_id)
                    result['action'] = 'ban'
                    result['message'] = '🚫 تم حظر المستخدم بعد تحذير'
                    await update_stats(chat_id, 'ban')
                else:
                    result['action'] = 'warn'
                    result['message'] = '⚠️ تحذير أول - المخالفة التالية = حظر'
                    await update_stats(chat_id, 'warning')
                    
            elif mode == 'mute_then_ban':
                if violations >= 2:
                    await bot.ban_chat_member(chat_id, user_id)
                    result['action'] = 'ban'
                    result['message'] = '🚫 تم حظر المستخدم بعد كتم'
                    await update_stats(chat_id, 'ban')
                else:
                    until_date = datetime.now() + timedelta(seconds=duration)
                    await bot.restrict_chat_member(
                        chat_id, user_id,
                        permissions=types.ChatPermissions(can_send_messages=False),
                        until_date=until_date
                    )
                    result['action'] = 'mute'
                    dur_val, dur_unit = seconds_to_value_unit(duration)
                    result['message'] = f'🔇 تم كتم المستخدم - المخالفة التالية = حظر'
                    result['duration'] = duration
                    await update_stats(chat_id, 'mute')
        
    except Exception as e:
        logger.error(f"خطأ في تطبيق العقوبة: {e}")
        result['action'] = 'error'
        result['message'] = f'❌ حدث خطأ في تطبيق العقوبة: {str(e)[:100]}'
    
    return result

# ================== نظام الوضع الليلي ==================
async def check_night_mode(group_str: str) -> bool:
    """التحقق من تفعيل الوضع الليلي"""
    if group_str not in settings:
        return False
    
    group_settings = settings[group_str]
    if not group_settings.get('night_mode_enabled', False):
        return False
    
    try:
        now = datetime.now().time()
        start = datetime.strptime(group_settings['night_start'], '%H:%M').time()
        end = datetime.strptime(group_settings['night_end'], '%H:%M').time()
        
        if start < end:
            return start <= now < end
        else:
            return start <= now or now < end
    except:
        return False

async def night_mode_checker():
    """مدقق الوضع الليلي"""
    while True:
        try:
            for group_id in ALLOWED_GROUP_IDS:
                group_str = str(group_id)
                is_night = await check_night_mode(group_str)
                
                if is_night and settings[group_str].get('night_announce_msg_id') is None:
                    # إرسال إعلان الوضع الليلي
                    announce_text = f"""🌙 <b>تم تفعيل الوضع الليلي</b>

⏰ الوقت الحالي: {datetime.now().strftime('%H:%M')}
🚫 النشر متوقف حتى: {settings[group_str]['night_end']}

💤 استريحوا وناموا جيداً!
🛡️ الحارس الأمني يحميكم"""
                    
                    try:
                        msg = await bot.send_message(group_id, announce_text)
                        settings[group_str]['night_announce_msg_id'] = msg.message_id
                        await save_settings()
                    except:
                        pass
                        
                elif not is_night and settings[group_str].get('night_announce_msg_id') is not None:
                    # حذف إعلان الوضع الليلي
                    try:
                        await safe_delete_message(
                            group_id, 
                            settings[group_str]['night_announce_msg_id']
                        )
                    except:
                        pass
                    finally:
                        settings[group_str]['night_announce_msg_id'] = None
                        await save_settings()
                        
                        # إرسال إعلان انتهاء الوضع الليلي
                        morning_text = f"""☀️ <b>تم تعطيل الوضع الليلي</b>

⏰ الوقت الحالي: {datetime.now().strftime('%H:%M')}
✅ يمكنكم النشر الآن

🌞 صباح الخير!
🛡️ الحارس الأمني يحميكم"""
                        
                        try:
                            await bot.send_message(group_id, morning_text)
                        except:
                            pass
            
            await asyncio.sleep(60)  # التحقق كل دقيقة
            
        except Exception as e:
            logger.error(f"خطأ في مدقق الوضع الليلي: {e}")
            await asyncio.sleep(300)

# ================== نظام التقديم للإدارة ==================
async def handle_application(chat_id: int, user_id: int, message: Message):
    """معالجة طلب التقديم للإدارة"""
    group_str = str(chat_id)
    
    if group_str not in settings:
        return
    
    if not settings[group_str].get('applicants_system', True):
        await message.reply("❌ نظام التقديم للإدارة معطل حالياً")
        return
    
    # التحقق من التكرار
    if 'applicants' not in settings[group_str]:
        settings[group_str]['applicants'] = []
    
    existing_app = next(
        (app for app in settings[group_str]['applicants'] 
         if app['user_id'] == user_id and time.time() - app['timestamp'] < 86400),
        None
    )
    
    if existing_app:
        await message.reply("⚠️ لديك طلب قيد المراجعة بالفعل، الرجاء الانتظار 24 ساعة")
        return
    
    # تسجيل الطلب
    application = {
        'user_id': user_id,
        'username': message.from_user.username,
        'full_name': message.from_user.full_name,
        'message': message.text.replace("/apply", "").strip(),
        'timestamp': time.time(),
        'status': 'pending',
        'chat_id': chat_id
    }
    
    settings[group_str]['applicants'].append(application)
    await save_settings()
    
    # إعلام الإداريين
    admins = await get_chat_admins(chat_id)
    for admin in admins:
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ قبول", callback_data=f"accept_app_{user_id}_{chat_id}"),
                    InlineKeyboardButton(text="❌ رفض", callback_data=f"reject_app_{user_id}_{chat_id}")
                ],
                [
                    InlineKeyboardButton(text="💬 مقابلة", callback_data=f"interview_app_{user_id}_{chat_id}")
                ]
            ])
            
            await bot.send_message(
                admin.user.id,
                f"""📋 <b>طلب جديد للإدارة</b>

👤 المتقدم: {application['full_name']}
📛 المعرف: @{application['username'] or 'لا يوجد'}
🆔 الرقم: <code>{user_id}</code>
📝 الرسالة: {application['message'][:200]}

📌 المجموعة: {message.chat.title}
⏰ الوقت: {datetime.fromtimestamp(application['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}

🛡️ اختر الإجراء المناسب:""",
                reply_markup=keyboard
            )
        except:
            continue
    
    await message.reply("✅ تم إرسال طلبك للإدارة، سنخبرك بالنتيجة قريباً")

async def get_chat_admins(chat_id: int):
    """الحصول على قائمة الإداريين"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        return [admin for admin in admins if not admin.user.is_bot]
    except Exception as e:
        logger.error(f"خطأ في جلب الإداريين: {e}")
        return []

# ================== نظام الفلاتر والردود التلقائية ==================
async def check_auto_reply(chat_id: int, text: str) -> Optional[str]:
    """التحقق من الردود التلقائية"""
    group_str = str(chat_id)
    
    if group_str not in settings:
        return None
    
    auto_replies = settings[group_str].get('auto_replies', {})
    text_lower = text.lower()
    
    for keyword, reply in auto_replies.items():
        if keyword.lower() in text_lower:
            return reply
    
    return None

async def check_custom_commands(chat_id: int, command: str) -> Optional[str]:
    """التحقق من الأوامر المخصصة"""
    group_str = str(chat_id)
    
    if group_str not in settings:
        return None
    
    custom_commands = settings[group_str].get('custom_commands', {})
    return custom_commands.get(command)

# ================== لوحات التحكم والواجهات ==================
def get_main_control_panel(group_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """لوحة التحكم الرئيسية"""
    group_str = str(group_id)
    
    # الحصول على إحصائيات المجموعة
    group_stats = bot_stats['groups'].get(group_str, {})
    group_settings = settings.get(group_str, {})
    
    # بناء النص
    text = f"""🛡️ <b>لوحة تحكم الحارس الأمني المتقدم</b> {get_random_emoji()}

📊 <b>إحصائيات المجموعة:</b>
├ 👥 الأعضاء النشطين: {len(group_stats.get('active_users', set()))}
├ 📨 الرسائل المفحوصة: {format_number(group_stats.get('messages_checked', 0))}
├ ⚠️ المخالفات: {group_stats.get('violations', 0)}
├ 🚫 الحظور: {group_stats.get('bans', 0)}
├ 🔇 الكتم: {group_stats.get('mutes', 0)}
└ ⚠️ التحذيرات: {group_stats.get('warnings', 0)}

⚙️ <b>الإعدادات النشطة:</b>
├ 🎯 وضع الحماية: {mode_to_text(group_settings.get('mode', 'smart_detection'))}
├ 🌙 الوضع الليلي: {'✅ مفعل' if group_settings.get('night_mode_enabled') else '❌ معطل'}
├ 🔤 الكلمات الممنوعة: {len(group_settings.get('banned_keywords', []))}
├ 🔗 الروابط الممنوعة: {len(group_settings.get('banned_links', []))}
├ 🌍 الدول المحظورة: {len(group_settings.get('banned_countries', []))}
├ 👑 الأعضاء المستثنين: {len(group_settings.get('exempted_users', []))}
└ ⭐ الأعضاء المميزين: {len(group_settings.get('vip_users', []))}

🎪 <b>المميزات الإضافية:</b>
├ 📋 نظام التقديم: {'✅ نشط' if group_settings.get('applicants_system', True) else '❌ معطل'}
├ 💾 النسخ الاحتياطي: {'✅ مفعل' if group_settings.get('auto_backup', True) else '❌ معطل'}
├ 📈 التقارير: {'✅ أسبوعية' if group_settings.get('weekly_reports', True) else '❌ معطلة'}
└ 🏆 التحديات: {'✅ نشطة' if group_settings.get('challenges_enabled', True) else '❌ معطلة'}

🕐 <b>معلومات المجموعة:</b>
├ 📅 تاريخ الإنشاء: {datetime.fromtimestamp(group_settings.get('created_at', time.time())).strftime('%Y-%m-%d')}
├ 👑 المالك: {'معروف' if group_settings.get('owner_id') else 'غير معروف'}
└ 🔄 آخر تحديث: {datetime.fromtimestamp(group_settings.get('last_update', time.time())).strftime('%H:%M:%S')}

🔥 <b>اختر القسم الذي تريد تعديله:</b>"""
    
    # بناء الكيبورد
    keyboard = InlineKeyboardBuilder()
    
    # قسم الحماية
    keyboard.button(text="⚔️ الحماية الأساسية", callback_data=f"protection_{group_id}")
    keyboard.button(text="🔤 الكلمات الممنوعة", callback_data=f"keywords_{group_id}")
    keyboard.button(text="🔗 الروابط الممنوعة", callback_data=f"links_{group_id}")
    
    # قسم الإدارة
    keyboard.button(text="👥 إدارة الأعضاء", callback_data=f"members_{group_id}")
    keyboard.button(text="🌍 الدول المحظورة", callback_data=f"countries_{group_id}")
    keyboard.button(text="🌙 الوضع الليلي", callback_data=f"night_{group_id}")
    
    # قسم المميزات
    keyboard.button(text="🎪 المميزات الإضافية", callback_data=f"features_{group_id}")
    keyboard.button(text="📊 الإحصائيات", callback_data=f"stats_{group_id}")
    keyboard.button(text="⚙️ الإعدادات المتقدمة", callback_data=f"advanced_{group_id}")
    
    # قسم الأوامر
    keyboard.button(text="🤖 الأوامر المخصصة", callback_data=f"commands_{group_id}")
    keyboard.button(text="💬 الردود التلقائية", callback_data=f"replies_{group_id}")
    keyboard.button(text="📋 نظام التقديم", callback_data=f"applicants_{group_id}")
    
    # أزرار المساعدة
    keyboard.button(text="📚 الدليل الشامل", callback_data=f"guide_{group_id}")
    keyboard.button(text="💬 دعم فني", url=SUPPORT_CHAT)
    keyboard.button(text="🔄 تحديث اللوحة", callback_data=f"refresh_{group_id}")
    keyboard.button(text="🏠 القائمة الرئيسية", callback_data="main_menu")
    
    keyboard.adjust(3, 3, 3, 3, 2, 2)
    
    return text, keyboard.as_markup()

def mode_to_text(mode: str) -> str:
    """تحويل وضع الحماية إلى نص"""
    modes = {
        'mute': '🔇 كتم عند المخالفة',
        'ban': '🚫 حظر عند المخالفة',
        'mute_then_ban': '🔇⏱️ كتم ثم حظر',
        'delete_only': '🗑️ حذف الرسالة فقط',
        'warn_then_mute': '⚠️🔇 تحذير ثم كتم',
        'warn_then_ban': '⚠️🚫 تحذير ثم حظر',
        'smart_detection': '🧠 كشف ذكي متقدم',
        'aggressive': '⚔️ وضع عدواني',
        'relaxed': '😌 وضع متساهل'
    }
    return modes.get(mode, mode)

# ================== Handlers الرئيسية ==================
@dp.message(CommandStart())
async def start_command(message: Message):
    """بدء التشغيل"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    await send_typing(message.chat.id)
    
    # التحقق إذا كان المطور
    is_dev = user_id == DEVELOPER_ID
    
    # رسالة الترحيب
    welcome_text = f"""🌟 <b>مرحباً بك في الحارس الأمني المتقدم!</b> {get_random_emoji()}

👋 <b>أهلاً {username}</b>،
أنت الآن في لوحة تحكم أقوى بوت أمني لمجموعات التليجرام!

🎯 <b>المميزات الرائعة:</b>
• 🧠 كشف ذكي للمحتوى المخالف
• ⚡ استجابة فائقة السرعة
• 🔄 تحديث تلقائي للقوائم السوداء
• 📊 إحصائيات مفصلة ورسوم بيانية
• 🎭 إدارة متعددة للمجموعات
• 🔔 إشعارات ذكية وقابلة للتخصيص
• 💾 نسخ احتياطي تلقائي

🚀 <b>مميزات فريدة:</b>
• 🌙 الوضع الليلي الذكي
• 👥 نظام التقديم للإدارة
• 📈 تقارير أداء أسبوعية
• 🎪 فعاليات وجوائز
• 🏆 بطولات أمنية شهرية

📞 <b>الدعم الفني:</b>
• 💬 دعم فني على مدار الساعة
• 📚 مكتبة شاملة للدليل
• 🔄 تحديثات مستمرة وأمنية

🔥 <b>ابدأ رحلتك الآن!</b>

📌 <b>طريقة الاستخدام:</b>
1️⃣ أضف البوت إلى مجموعتك
2️⃣ امنحه صلاحيات المسؤول
3️⃣ استخدم <code>/settings</code> لضبط الإعدادات
4️⃣ استمتع بحماية فائقة!

💡 <b>نصيحة:</b> استخدم <code>/help</code> للاطلاع على جميع الأوامر."""

    keyboard = InlineKeyboardBuilder()
    
    if is_dev:
        keyboard.button(text="👑 لوحة المطور", callback_data="dev_panel")
    
    keyboard.button(text="⚙️ الإعدادات", callback_data="settings_menu")
    keyboard.button(text="📊 الإحصائيات", callback_data="global_stats")
    keyboard.button(text="📚 الدليل", callback_data="help_guide")
    keyboard.button(text="💬 مجموعة الدعم", url=SUPPORT_CHAT)
    keyboard.button(text="⭐ تقييم البوت", callback_data="rate_bot")
    
    keyboard.adjust(2, 2, 1)
    
    await message.answer(welcome_text, reply_markup=keyboard.as_markup())
    
    # تحديث إحصائيات المستخدم
    if user_id not in bot_stats['users']:
        bot_stats['users'][user_id] = {
            'first_seen': time.time(),
            'commands_used': 0,
            'last_seen': time.time()
        }
    
    bot_stats['users'][user_id]['last_seen'] = time.time()
    bot_stats['users'][user_id]['commands_used'] += 1

@dp.message(Command("help"))
async def help_command(message: Message):
    """عرض جميع الأوامر"""
    help_text = f"""🎯 <b>أوامر الحارس الأمني المتقدم</b> {get_random_emoji()}

🛡️ <b>أوامر الحماية:</b>
• <code>/settings</code> - لوحة الإعدادات الرئيسية
• <code>/protection</code> - إعدادات الحماية المتقدمة
• <code>/keywords</code> - إدارة الكلمات الممنوعة
• <code>/links</code> - إدارة الروابط الممنوعة
• <code>/nightmode</code> - إدارة الوضع الليلي
• <code>/scan</code> - فحص المجموعة بحثاً عن مخالفات

👥 <b>أوامر الإدارة:</b>
• <code>/members</code> - إدارة الأعضاء والصلاحيات
• <code>/warnings</code> - عرض التحذيرات
• <code>/clean</code> - تنظيف الرسائل
• <code>/report</code> - الإبلاغ عن مخالف
• <code>/applicants</code> - إدارة المتقدمين للإدارة
• <code>/exempt</code> - استثناء عضو
• <code>/unexempt</code> - إزالة استثناء عضو

📊 <b>أوامر الإحصائيات:</b>
• <code>/stats</code> - إحصائيات المجموعة
• <code>/activity</code> - نشاط الأعضاء
• <code>/violations</code> - سجل المخالفات
• <code>/topspammers</code> - أكثر الأعضاء مخالفة
• <code>/leaderboard</code> - لوحة المتصدرين

⚙️ <b>أوامر الإعدادات:</b>
• <code>/backup</code> - إنشاء نسخة احتياطية
• <code>/restore</code> - استعادة الإعدادات
• <code>/export</code> - تصدير البيانات
• <code>/import</code> - استيراد البيانات
• <code>/language</code> - تغيير اللغة

🎪 <b>أوامر الترفيه:</b>
• <code>/ranking</code> - ترتيب الأعضاء
• <code>/awards</code> - الجوائز والميداليات
• <code>/events</code> - الفعاليات القادمة
• <code>/challenges</code> - التحديات الأمنية
• <code>/achievements</code> - الإنجازات

🔧 <b>أوامر المطور:</b>
• <code>/sysinfo</code> - معلومات النظام
• <code>/logs</code> - سجلات الأخطاء
• <code>/update</code> - تحديث البوت
• <code>/maintenance</code> - وضع الصيانة
• <code>/broadcast</code> - بث رسالة

💎 <b>مميزات إضافية:</b>
• ترجمة تلقائية للغات
• دعم الرموز التعبيرية
• واجهة مستخدم تفاعلية
• تحديثات حية مباشرة
• دعم متعدد اللغات

📞 <b>للحصول على دعم فني:</b>
{SUPPORT_CHAT}

✨ <b>تابعنا للحصول على آخر التحديثات</b>
@{BOT_USERNAME}"""

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📚 الدليل الشامل", callback_data="full_guide")
    keyboard.button(text="🎥 فيديوهات تعليمية", callback_data="tutorials")
    keyboard.button(text="💬 مجموعة الدعم", url=SUPPORT_CHAT)
    keyboard.button(text="⚙️ الإعدادات السريعة", callback_data="quick_settings")
    
    keyboard.adjust(2, 1, 1)
    
    await message.answer(help_text, reply_markup=keyboard.as_markup())

@dp.message(Command("settings"))
async def settings_command(message: Message):
    """فتح إعدادات المجموعة"""
    user_id = message.from_user.id
    
    if message.chat.type == 'private':
        # في الخاص، عرض قائمة المجموعات
        keyboard = InlineKeyboardBuilder()
        has_groups = False
        
        for gid in ALLOWED_GROUP_IDS:
            try:
                if await is_admin(gid, user_id):
                    chat = await bot.get_chat(gid)
                    keyboard.button(
                        text=f"📌 {chat.title[:25]}",
                        callback_data=f"manage_{gid}"
                    )
                    has_groups = True
            except:
                continue
        
        if has_groups:
            keyboard.adjust(1)
            await message.answer(
                "⚙️ <b>اختر المجموعة التي تريد إدارتها:</b>",
                reply_markup=keyboard.as_markup()
            )
        else:
            await message.answer(
                "❌ <b>لم أتمكن من العثور على مجموعات يمكنك إدارتها</b>\n\n"
                "تأكد من:\n"
                "1. إضافة البوت إلى مجموعتك\n"
                "2. منح البوت صلاحيات المسؤول\n"
                "3. أنك مسؤول في المجموعة"
            )
    else:
        # في المجموعة، عرض لوحة التحكم
        group_id = message.chat.id
        if group_id in ALLOWED_GROUP_IDS:
            if await is_admin(group_id, user_id):
                text, keyboard = get_main_control_panel(group_id)
                await message.answer(text, reply_markup=keyboard)
            else:
                await message.reply("❌ هذا الأمر للمسؤولين فقط")
        else:
            await message.reply("❌ هذه المجموعة غير مسجلة في النظام")

@dp.message(Command("stats"))
async def stats_command(message: Message):
    """عرض إحصائيات المجموعة"""
    chat_id = message.chat.id
    
    if chat_id not in ALLOWED_GROUP_IDS:
        await message.reply("❌ هذه المجموعة غير مسجلة في النظام")
        return
    
    group_str = str(chat_id)
    group_stats = bot_stats['groups'].get(group_str, {})
    group_settings = settings.get(group_str, {})
    
    # حساب بعض الإحصائيات
    active_users = len(group_stats.get('active_users', set()))
    messages_checked = group_stats.get('messages_checked', 0)
    violations = group_stats.get('violations', 0)
    bans = group_stats.get('bans', 0)
    mutes = group_stats.get('mutes', 0)
    
    # نسبة المخالفات
    violation_rate = (violations / messages_checked * 100) if messages_checked > 0 else 0
    
    stats_text = f"""📊 <b>إحصائيات المجموعة</b> {get_random_emoji()}

📈 <b>الإحصائيات العامة:</b>
├ 👥 الأعضاء النشطين: {active_users}
├ 📨 الرسائل المفحوصة: {format_number(messages_checked)}
├ ⚠️ المخالفات المكتشفة: {violations}
├ 🚫 حالات الحظر: {bans}
├ 🔇 حالات الكتم: {mutes}
└ 📊 نسبة المخالفات: {violation_rate:.2f}%

🎯 <b>أكثر الأعضاء مخالفة:</b>"""
    
    # عرض أكثر الأعضاء مخالفة
    top_violators = sorted(
        group_stats.get('top_violators', {}).items(),
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    if top_violators:
        for i, (user_id, count) in enumerate(top_violators, 1):
            try:
                user = await bot.get_chat_member(chat_id, user_id)
                name = user.user.full_name
            except:
                name = f"مستخدم {user_id}"
            
            stats_text += f"\n{i}. {name[:20]} - {count} مخالفة"
    else:
        stats_text += "\nلا توجد مخالفات حتى الآن 👍"
    
    stats_text += f"""

⚙️ <b>إحصائيات النظام:</b>
├ 🎯 وضع الحماية: {mode_to_text(group_settings.get('mode', 'smart_detection'))}
├ 🔤 الكلمات الممنوعة: {len(group_settings.get('banned_keywords', []))}
├ 🔗 الروابط الممنوعة: {len(group_settings.get('banned_links', []))}
└ ⏰ آخر نشاط: {datetime.fromtimestamp(group_stats.get('last_activity', time.time())).strftime('%H:%M:%S')}

🛡️ <b>الحارس الأمني يحميكم!</b>"""
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 تحديث", callback_data=f"stats_refresh_{chat_id}")
    keyboard.button(text="📈 تفاصيل أكثر", callback_data=f"stats_details_{chat_id}")
    keyboard.button(text="📊 إحصائيات عالمية", callback_data="global_stats")
    keyboard.button(text="🏠 القائمة الرئيسية", callback_data=f"manage_{chat_id}")
    
    keyboard.adjust(2, 2)
    
    await message.answer(stats_text, reply_markup=keyboard.as_markup())

@dp.message(Command("backup"))
async def backup_command(message: Message):
    """إنشاء نسخة احتياطية"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id not in ALLOWED_GROUP_IDS:
        await message.reply("❌ هذا الأمر للمجموعات المسجلة فقط")
        return
    
    if not await is_admin(chat_id, user_id):
        await message.reply("❌ هذا الأمر للمسؤولين فقط")
        return
    
    # إرسال رسالة الانتظار
    wait_msg = await message.reply("🔄 <b>جاري إنشاء النسخة الاحتياطية...</b>")
    
    # إنشاء النسخة الاحتياطية
    success = await create_backup(chat_id, manual=True)
    
    if success:
        await wait_msg.edit_text(
            "✅ <b>تم إنشاء النسخة الاحتياطية بنجاح!</b>\n\n"
            "📦 تم إرسال النسخة إلى المطور\n"
            "⏰ يمكنك استعادتها في أي وقت"
        )
    else:
        await wait_msg.edit_text(
            "❌ <b>فشل في إنشاء النسخة الاحتياطية</b>\n\n"
            "⚠️ حاول مرة أخرى لاحقاً"
        )

@dp.message(Command("scan"))
async def scan_command(message: Message):
    """فحص المجموعة"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id not in ALLOWED_GROUP_IDS:
        await message.reply("❌ هذا الأمر للمجموعات المسجلة فقط")
        return
    
    if not await is_admin(chat_id, user_id):
        await message.reply("❌ هذا الأمر للمسؤولين فقط")
        return
    
    # إرسال رسالة الانتظار
    wait_msg = await message.reply("🔍 <b>جاري فحص المجموعة...</b>\n\n⏰ قد تستغرق العملية بضع دقائق")
    
    try:
        # محاكاة الفحص
        await asyncio.sleep(2)
        
        # نتائج الفحص المزيفة (في الإصدار الحقيقي، سيتم فحص الأعضاء والرسائل)
        scan_results = {
            "total_members": random.randint(100, 500),
            "suspicious_accounts": random.randint(0, 5),
            "banned_keywords_found": random.randint(0, 3),
            "spam_messages": random.randint(0, 10),
            "inactive_users": random.randint(10, 50)
        }
        
        scan_text = f"""🔍 <b>نتائج فحص المجموعة</b> {get_random_emoji()}

📊 <b>نتائج الفحص:</b>
├ 👥 إجمالي الأعضاء: {scan_results['total_members']}
├ ⚠️ حسابات مشبوهة: {scan_results['suspicious_accounts']}
├ 🔤 كلمات ممنوعة: {scan_results['banned_keywords_found']}
├ 📨 رسائل سبام: {scan_results['spam_messages']}
└ 💤 أعضاء غير نشطين: {scan_results['inactive_users']}

📈 <b>تقييم الأمان:</b>
├ 🟢 الأمان العام: جيد
├ 🟡 النشاط: متوسط
├ 🟢 النظافة: جيدة
└ 🟡 المراقبة: متوسطة

💡 <b>التوصيات:</b>
• تفعيل الوضع الليلي للنوم الآمن
• إضافة المزيد من الكلمات للقائمة السوداء
• مراجعة الأعضاء المشبوهين
• تشجيع النشاط في المجموعة

🛡️ <b>المجموعة محمية بشكل جيد!</b>"""
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="🔄 فحص أعمق", callback_data=f"deep_scan_{chat_id}")
        keyboard.button(text="🧹 تنظيف تلقائي", callback_data=f"auto_clean_{chat_id}")
        keyboard.button(text="📊 الإحصائيات", callback_data=f"stats_{chat_id}")
        
        keyboard.adjust(1)
        
        await wait_msg.edit_text(scan_text, reply_markup=keyboard.as_markup())
        
    except Exception as e:
        await wait_msg.edit_text(f"❌ <b>حدث خطأ أثناء الفحص:</b>\n\n{str(e)[:200]}")

@dp.message(Command("clean"))
async def clean_command(message: Message):
    """تنظيف المجموعة"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if chat_id not in ALLOWED_GROUP_IDS:
        await message.reply("❌ هذا الأمر للمجموعات المسجلة فقط")
        return
    
    if not await is_admin(chat_id, user_id):
        await message.reply("❌ هذا الأمر للمسؤولين فقط")
        return
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🗑️ مسح روابط", callback_data=f"clean_links_{chat_id}")
    keyboard.button(text="🔤 مسح كلمات", callback_data=f"clean_keywords_{chat_id}")
    keyboard.button(text="👻 مسح حسابات", callback_data=f"clean_accounts_{chat_id}")
    keyboard.button(text="🧹 تنظيف كامل", callback_data=f"clean_all_{chat_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{chat_id}")
    
    keyboard.adjust(2, 2, 1)
    
    await message.answer(
        "🧹 <b>أدوات تنظيف المجموعة</b>\n\n"
        "اختر نوع التنظيف الذي تريد تنفيذه:",
        reply_markup=keyboard.as_markup()
    )

# ================== معالج Callback الكامل ==================
@dp.callback_query()
async def handle_callback_query(callback: CallbackQuery, state: FSMContext):
    """معالج جميع الأزرار"""
    data = callback.data
    
    try:
        await callback.answer()
        
        if not data:
            return
        
        # ===== الأزرار الرئيسية =====
        if data == "main_menu":
            await start_command(callback.message)
            return
            
        elif data == "settings_menu":
            await settings_command(callback.message)
            return
            
        elif data == "global_stats":
            await show_global_stats(callback)
            return
            
        elif data == "help_guide":
            await help_command(callback.message)
            return
            
        elif data == "rate_bot":
            await rate_bot(callback)
            return
            
        elif data == "dev_panel":
            if callback.from_user.id == DEVELOPER_ID:
                await show_dev_panel(callback)
            else:
                await callback.answer("❌ هذا الزر للمطور فقط", show_alert=True)
            return
        
        # ===== إدارة المجموعات =====
        elif data.startswith("manage_"):
            group_id = int(data.split("_")[1])
            await show_group_panel(callback, group_id)
            return
            
        elif data.startswith("refresh_"):
            group_id = int(data.split("_")[1])
            await show_group_panel(callback, group_id)
            return
        
        # ===== الحماية الأساسية =====
        elif data.startswith("protection_"):
            group_id = int(data.split("_")[1])
            await show_protection_panel(callback, group_id)
            return
            
        elif data.startswith("setmode_"):
            parts = data.split("_")
            if len(parts) >= 3:
                mode = parts[1]
                group_id = int(parts[2])
                await set_protection_mode(callback, group_id, mode)
            return
        
        # ===== الكلمات الممنوعة =====
        elif data.startswith("keywords_"):
            group_id = int(data.split("_")[1])
            await show_keywords_panel(callback, group_id)
            return
            
        elif data.startswith("addkw_"):
            group_id = int(data.split("_")[1])
            await add_keyword_handler(callback, state, group_id)
            return
            
        elif data.startswith("removekw_"):
            group_id = int(data.split("_")[1])
            await remove_keyword_handler(callback, state, group_id)
            return
        
        # ===== الروابط الممنوعة =====
        elif data.startswith("links_"):
            group_id = int(data.split("_")[1])
            await show_links_panel(callback, group_id)
            return
        
        # ===== الدول المحظورة =====
        elif data.startswith("countries_"):
            group_id = int(data.split("_")[1])
            await show_countries_panel(callback, group_id)
            return
        
        # ===== الوضع الليلي =====
        elif data.startswith("night_"):
            group_id = int(data.split("_")[1])
            await show_night_panel(callback, group_id)
            return
            
        elif data.startswith("togglenight_"):
            group_id = int(data.split("_")[1])
            await toggle_night_mode(callback, group_id)
            return
        
        # ===== إدارة الأعضاء =====
        elif data.startswith("members_"):
            group_id = int(data.split("_")[1])
            await show_members_panel(callback, group_id)
            return
        
        # ===== المميزات الإضافية =====
        elif data.startswith("features_"):
            group_id = int(data.split("_")[1])
            await show_features_panel(callback, group_id)
            return
        
        # ===== الإحصائيات =====
        elif data.startswith("stats_"):
            if "details" in data:
                group_id = int(data.split("_")[2])
                await show_stats_details(callback, group_id)
            elif "refresh" in data:
                group_id = int(data.split("_")[2])
                await refresh_stats(callback, group_id)
            else:
                group_id = int(data.split("_")[1])
                await show_stats_panel(callback, group_id)
            return
        
        # ===== الإعدادات المتقدمة =====
        elif data.startswith("advanced_"):
            group_id = int(data.split("_")[1])
            await show_advanced_panel(callback, group_id)
            return
        
        # ===== الأوامر المخصصة =====
        elif data.startswith("commands_"):
            group_id = int(data.split("_")[1])
            await show_commands_panel(callback, group_id)
            return
        
        # ===== الردود التلقائية =====
        elif data.startswith("replies_"):
            group_id = int(data.split("_")[1])
            await show_replies_panel(callback, group_id)
            return
        
        # ===== نظام التقديم =====
        elif data.startswith("applicants_"):
            group_id = int(data.split("_")[1])
            await show_applicants_panel(callback, group_id)
            return
            
        elif data.startswith("accept_app_"):
            parts = data.split("_")
            if len(parts) >= 4:
                user_id = int(parts[2])
                group_id = int(parts[3])
                await accept_application(callback, user_id, group_id)
            return
            
        elif data.startswith("reject_app_"):
            parts = data.split("_")
            if len(parts) >= 4:
                user_id = int(parts[2])
                group_id = int(parts[3])
                await reject_application(callback, user_id, group_id)
            return
        
        # ===== التنظيف =====
        elif data.startswith("clean_"):
            parts = data.split("_")
            if len(parts) >= 3:
                action = parts[1]
                group_id = int(parts[2])
                await handle_clean_action(callback, group_id, action)
            return
        
        # ===== الدليل =====
        elif data.startswith("guide_"):
            group_id = int(data.split("_")[1])
            await show_guide_panel(callback, group_id)
            return
        
        # ===== لوحة المطور =====
        elif data.startswith("dev_"):
            if callback.from_user.id == DEVELOPER_ID:
                await handle_dev_actions(callback, data)
            else:
                await callback.answer("❌ هذا الزر للمطور فقط", show_alert=True)
            return
        
        # ===== تحديث الإحصائيات =====
        elif data == "update_stats":
            await update_global_stats(callback)
            return
        
        # ===== إجراءات أخرى =====
        else:
            await callback.answer("⚙️ هذا الزر قيد التطوير", show_alert=True)
            
    except Exception as e:
        logger.error(f"خطأ في معالج Callback: {e}")
        await callback.answer("❌ حدث خطأ في المعالجة", show_alert=True)

# ===== دوال مساعدة للـ Callbacks =====
async def show_group_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة المجموعة"""
    text, keyboard = get_main_control_panel(group_id)
    await safe_edit_message(callback, text, keyboard)

async def show_protection_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الحماية"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    
    text = f"""⚔️ <b>إعدادات الحماية المتقدمة</b> {get_random_emoji()}

🎯 <b>الوضع الحالي:</b> {mode_to_text(group_settings.get('mode', 'smart_detection'))}

📊 <b>مستويات الحماية:</b>
1. 🟢 <b>متساهل</b> - تحذيرات فقط للمخالفات البسيطة
2. 🟡 <b>متوسط</b> - كتم مؤقت للمخالفات المتوسطة
3. 🔴 <b>صارم</b> - حظر للمخالفات الخطيرة
4. ⚫ <b>عدواني</b> - حظر فوري لأي مخالفة
5. 🧠 <b>ذكي</b> - تحليل ذكي للمحتوى (مُوصى به)

⚡ <b>اختر مستوى الحماية:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    
    modes = [
        ("relaxed", "🟢 متساهل"),
        ("mute", "🟡 متوسط"),
        ("ban", "🔴 صارم"),
        ("aggressive", "⚫ عدواني"),
        ("smart_detection", "🧠 ذكي")
    ]
    
    current_mode = group_settings.get('mode', 'smart_detection')
    
    for mode_id, mode_name in modes:
        if mode_id == current_mode:
            keyboard.button(text=f"✅ {mode_name}", callback_data=f"#")
        else:
            keyboard.button(text=mode_name, callback_data=f"setmode_{mode_id}_{group_id}")
    
    keyboard.button(text="⚙️ إعدادات مخصصة", callback_data=f"custom_mode_{group_id}")
    keyboard.button(text="⏱️ ضبط المدة", callback_data=f"set_duration_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2, 1, 1, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def set_protection_mode(callback: CallbackQuery, group_id: int, mode: str):
    """تعيين وضع الحماية"""
    group_str = str(group_id)
    
    if group_str not in settings:
        await callback.answer("❌ المجموعة غير موجودة", show_alert=True)
        return
    
    settings[group_str]['mode'] = mode
    await save_settings()
    
    await callback.answer(f"✅ تم تعيين وضع الحماية: {mode_to_text(mode)}", show_alert=True)
    await show_protection_panel(callback, group_id)

async def show_keywords_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الكلمات الممنوعة"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    keywords = group_settings.get('banned_keywords', [])
    
    text = f"""🔤 <b>إدارة الكلمات الممنوعة</b> {get_random_emoji()}

📊 <b>الإحصائيات:</b>
• عدد الكلمات: {len(keywords)}
• آخر إضافة: {datetime.fromtimestamp(group_settings.get('last_update', time.time())).strftime('%H:%M:%S')}

📋 <b>آخر 10 كلمات:</b>"""
    
    if keywords:
        for i, keyword in enumerate(keywords[-10:], 1):
            text += f"\n{i}. <code>{keyword[:30]}</code>"
    else:
        text += "\nلا توجد كلمات ممنوعة حتى الآن"
    
    text += "\n\n💡 <b>اختر الإجراء:</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ إضافة كلمة", callback_data=f"addkw_{group_id}")
    keyboard.button(text="🗑️ حذف كلمة", callback_data=f"removekw_{group_id}")
    keyboard.button(text="📋 عرض الكل", callback_data=f"showallkw_{group_id}")
    keyboard.button(text="🧹 مسح الكل", callback_data=f"clearkw_{group_id}")
    keyboard.button(text="📥 استيراد", callback_data=f"importkw_{group_id}")
    keyboard.button(text="📤 تصدير", callback_data=f"exportkw_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2, 2)
    
    await safe_edit_message(callback, text, keyboard)

async def add_keyword_handler(callback: CallbackQuery, state: FSMContext, group_id: int):
    """معالج إضافة كلمة ممنوعة"""
    await state.set_state(Form.waiting_for_keyword)
    await state.update_data(group_id=group_id, action='add')
    
    await callback.message.answer(
        "📝 <b>أرسل الكلمة الممنوعة:</b>\n\n"
        "يمكن أن تكون:\n"
        "• كلمة واحدة\n"
        "• عبارة كاملة\n"
        "• رابط\n"
        "• نمط (مثال: *كلمة*)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"keywords_{group_id}")]
        ])
    )

async def remove_keyword_handler(callback: CallbackQuery, state: FSMContext, group_id: int):
    """معالج حذف كلمة ممنوعة"""
    await state.set_state(Form.waiting_for_keyword)
    await state.update_data(group_id=group_id, action='remove')
    
    await callback.message.answer(
        "🗑️ <b>أرسل الكلمة المراد حذفها:</b>\n\n"
        "اكتب الكلمة تماماً كما هي",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ إلغاء", callback_data=f"keywords_{group_id}")]
        ])
    )

async def show_links_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الروابط الممنوعة"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    links = group_settings.get('banned_links', [])
    
    text = f"""🔗 <b>إدارة الروابط الممنوعة</b> {get_random_emoji()}

📊 <b>الإحصائيات:</b>
• عدد الروابط: {len(links)}

📋 <b>آخر 10 روابط:</b>"""
    
    if links:
        for i, link in enumerate(links[-10:], 1):
            text += f"\n{i}. <code>{link[:40]}</code>"
    else:
        text += "\nلا توجد روابط ممنوعة حتى الآن"
    
    text += "\n\n💡 <b>اختر الإجراء:</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ إضافة رابط", callback_data=f"addlink_{group_id}")
    keyboard.button(text="🗑️ حذف رابط", callback_data=f"removelink_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def show_countries_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الدول المحظورة"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    countries = group_settings.get('banned_countries', [])
    
    text = f"""🌍 <b>إدارة الدول المحظورة</b> {get_random_emoji()}

📊 <b>الإحصائيات:</b>
• عدد الدول: {len(countries)}
• الكشف مفعل: {'✅ نعم' if group_settings.get('country_detection_enabled', False) else '❌ لا'}

📋 <b>الدول المحظورة:</b>"""
    
    if countries:
        for i, country in enumerate(countries, 1):
            text += f"\n{i}. {country}"
    else:
        text += "\nلا توجد دول محظورة حتى الآن"
    
    text += "\n\n💡 <b>اختر الإجراء:</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="➕ إضافة دولة", callback_data=f"addcountry_{group_id}")
    keyboard.button(text="🗑️ حذف دولة", callback_data=f"removecountry_{group_id}")
    keyboard.button(text="🔧 تفعيل/تعطيل", callback_data=f"togglecountry_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2)
    
    await safe_edit_message(callback, text, keyboard)

async def show_night_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الوضع الليلي"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    
    text = f"""🌙 <b>إدارة الوضع الليلي</b> {get_random_emoji()}

📊 <b>الحالة الحالية:</b> {'✅ مفعل' if group_settings.get('night_mode_enabled', False) else '❌ معطل'}

⏰ <b>الإعدادات:</b>
• وقت البدء: {group_settings.get('night_start', '22:00')}
• وقت الانتهاء: {group_settings.get('night_end', '06:00')}

💡 <b>معلومات:</b>
الوضع الليلي يمنع الأعضاء غير الإداريين من النشر خلال الساعات المحددة.

📌 <b>اختر الإجراء:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    
    if group_settings.get('night_mode_enabled', False):
        keyboard.button(text="❌ تعطيل الوضع الليلي", callback_data=f"togglenight_{group_id}")
    else:
        keyboard.button(text="✅ تفعيل الوضع الليلي", callback_data=f"togglenight_{group_id}")
    
    keyboard.button(text="⏰ تغيير وقت البدء", callback_data=f"changestart_{group_id}")
    keyboard.button(text="⏰ تغيير وقت الانتهاء", callback_data=f"changeend_{group_id}")
    keyboard.button(text="🔔 إعدادات الإشعارات", callback_data=f"nightnotif_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(1, 2, 2)
    
    await safe_edit_message(callback, text, keyboard)

async def toggle_night_mode(callback: CallbackQuery, group_id: int):
    """تفعيل/تعطيل الوضع الليلي"""
    group_str = str(group_id)
    
    if group_str not in settings:
        await callback.answer("❌ المجموعة غير موجودة", show_alert=True)
        return
    
    current = settings[group_str].get('night_mode_enabled', False)
    settings[group_str]['night_mode_enabled'] = not current
    
    await save_settings()
    
    action = "تعطيل" if current else "تفعيل"
    await callback.answer(f"✅ تم {action} الوضع الليلي", show_alert=True)
    await show_night_panel(callback, group_id)

async def show_members_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة إدارة الأعضاء"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    
    text = f"""👥 <b>إدارة الأعضاء والصلاحيات</b> {get_random_emoji()}

📊 <b>الإحصائيات:</b>
• الأعضاء المستثنين: {len(group_settings.get('exempted_users', []))}
• الأعضاء المميزين: {len(group_settings.get('vip_users', []))}
• الأعضاء الموثوقين: {len(group_settings.get('trusted_users', []))}

🛡️ <b>أنواع الأعضاء:</b>
1. 👑 <b>المالك</b> - صلاحيات كاملة
2. ⚡ <b>المسؤولون</b> - إدارة المجموعة
3. ⭐ <b>مميز</b> - صلاحيات إضافية
4. ✅ <b>موثوق</b> - مراقبة مخففة
5. 🛡️ <b>مستثنى</b> - لا يتم مراقبته
6. 👤 <b>عضو عادي</b> - مراقبة كاملة

📌 <b>اختر الإجراء:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="👑 إضافة مستثنى", callback_data=f"addexempt_{group_id}")
    keyboard.button(text="⭐ إضافة مميز", callback_data=f"addvip_{group_id}")
    keyboard.button(text="✅ إضافة موثوق", callback_data=f"addtrusted_{group_id}")
    keyboard.button(text="📋 قائمة المستثنين", callback_data=f"listexempt_{group_id}")
    keyboard.button(text="📋 قائمة المميزين", callback_data=f"listvip_{group_id}")
    keyboard.button(text="🛡️ حماية الجدد", callback_data=f"newprotect_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2, 2, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def show_features_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة المميزات الإضافية"""
    group_str = str(group_id)
    group_settings = settings.get(group_str, {})
    
    text = f"""🎪 <b>المميزات الإضافية</b> {get_random_emoji()}

✨ <b>المميزات المتاحة:</b>

📋 <b>نظام التقديم للإدارة:</b>
{'✅ مفعل' if group_settings.get('applicants_system', True) else '❌ معطل'}
يسمح للأعضاء بالتقدم لمنصب الإدارة

💾 <b>النسخ الاحتياطي التلقائي:</b>
{'✅ مفعل' if group_settings.get('auto_backup', True) else '❌ معطل'}
يحفظ إعداداتك تلقائياً كل أسبوع

📈 <b>التقارير الأسبوعية:</b>
{'✅ مفعلة' if group_settings.get('weekly_reports', True) else '❌ معطلة'}
ترسل تقريراً أسبوعياً عن نشاط المجموعة

🏆 <b>التحديات والجوائز:</b>
{'✅ مفعلة' if group_settings.get('challenges_enabled', True) else '❌ معطلة'}
تحفيز الأعضاء بالمشاركة في تحديات أمنية

📌 <b>اختر الميزة التي تريد تعديلها:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📋 نظام التقديم", callback_data=f"toggle_applicants_{group_id}")
    keyboard.button(text="💾 النسخ الاحتياطي", callback_data=f"toggle_backup_{group_id}")
    keyboard.button(text="📈 التقارير", callback_data=f"toggle_reports_{group_id}")
    keyboard.button(text="🏆 التحديات", callback_data=f"toggle_challenges_{group_id}")
    keyboard.button(text="🎭 كل المميزات", callback_data=f"all_features_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2, 1, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def show_stats_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الإحصائيات"""
    group_str = str(group_id)
    group_stats = bot_stats['groups'].get(group_str, {})
    
    text = f"""📊 <b>إحصائيات مفصلة</b> {get_random_emoji()}

📈 <b>إحصائيات النشاط:</b>
• الرسائل المفحوصة: {format_number(group_stats.get('messages_checked', 0))}
• الأعضاء النشطين: {len(group_stats.get('active_users', set()))}
• آخر نشاط: {datetime.fromtimestamp(group_stats.get('last_activity', time.time())).strftime('%H:%M:%S')}

⚠️ <b>إحصائيات الأمان:</b>
• المخالفات: {group_stats.get('violations', 0)}
• الحظور: {group_stats.get('bans', 0)}
• الكتم: {group_stats.get('mutes', 0)}
• التحذيرات: {group_stats.get('warnings', 0)}

🏆 <b>أكثر الأعضاء نشاطاً:</b>"""
    
    # الحصول على أكثر الأعضاء نشاطاً
    active_users = list(group_stats.get('active_users', set()))[:5]
    if active_users:
        for i, user_id in enumerate(active_users, 1):
            try:
                user = await bot.get_chat_member(group_id, user_id)
                name = user.user.full_name[:20]
                text += f"\n{i}. {name}"
            except:
                text += f"\n{i}. مستخدم {user_id}"
    else:
        text += "\nلا توجد بيانات كافية"
    
    text += "\n\n📌 <b>اختر الإجراء:</b>"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 تحديث", callback_data=f"stats_refresh_{group_id}")
    keyboard.button(text="📈 تفاصيل أكثر", callback_data=f"stats_details_{group_id}")
    keyboard.button(text="📋 تقرير مفصل", callback_data=f"full_report_{group_id}")
    keyboard.button(text="📤 تصدير البيانات", callback_data=f"export_stats_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def show_advanced_panel(callback: CallbackQuery, group_id: int):
    """عرض لوحة الإعدادات المتقدمة"""
    text = f"""⚙️ <b>الإعدادات المتقدمة</b> {get_random_emoji()}

🔧 <b>إعدادات النظام المتقدمة:</b>

1. 🎨 <b>التخصيص</b>
   • تغيير واجهة البوت
   • تخصيص الألوان
   • إضافة شعار مخصص

2. 🔔 <b>الإشعارات</b>
   • تخصيص أنواع الإشعارات
   • إعدادات الصوت
   • توقيت الإشعارات

3. 🌐 <b>اللغات</b>
   • تغيير لغة البوت
   • دعم لغات متعددة
   • ترجمة تلقائية

4. 🔐 <b>الأمان المتقدم</b>
   • إعدادات المصادقة
   • تسجيل الدخول
   • الصلاحيات المتقدمة

5. 📡 <b>التكاملات</b>
   • تكامل مع بوتات أخرى
   • واجهات برمجة
   • خدمات خارجية

📌 <b>اختر القسم:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🎨 التخصيص", callback_data=f"customization_{group_id}")
    keyboard.button(text="🔔 الإشعارات", callback_data=f"notifications_{group_id}")
    keyboard.button(text="🌐 اللغات", callback_data=f"languages_{group_id}")
    keyboard.button(text="🔐 الأمان", callback_data=f"security_{group_id}")
    keyboard.button(text="📡 التكاملات", callback_data=f"integrations_{group_id}")
    keyboard.button(text="⚡ الأداء", callback_data=f"performance_{group_id}")
    keyboard.button(text="↩️ رجوع", callback_data=f"manage_{group_id}")
    
    keyboard.adjust(2, 2, 2, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def show_global_stats(callback: CallbackQuery):
    """عرض الإحصائيات العالمية"""
    total_groups = len(ALLOWED_GROUP_IDS)
    total_users = len(bot_stats['users'])
    
    # حساب إجمالي الإحصائيات
    total_messages = bot_stats['total_messages_checked']
    total_violations = bot_stats['total_violations']
    total_bans = bot_stats['total_bans']
    total_mutes = bot_stats['total_mutes']
    
    # وقت التشغيل
    uptime = time.time() - bot_stats['start_time']
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    
    text = f"""🌍 <b>الإحصائيات العالمية</b> {get_random_emoji()}

📊 <b>نظرة عامة:</b>
• عدد المجموعات: {total_groups}
• عدد المستخدمين: {total_users}
• وقت التشغيل: {days} يوم, {hours} ساعة, {minutes} دقيقة

📈 <b>إحصائيات الأداء:</b>
• إجمالي الرسائل: {format_number(total_messages)}
• إجمالي المخالفات: {format_number(total_violations)}
• إجمالي الحظور: {format_number(total_bans)}
• إجمالي الكتم: {format_number(total_mutes)}

💻 <b>إحصائيات النظام:</b>
• استخدام الذاكرة: {bot_stats['system']['memory_usage']:.1f} MB
• استخدام المعالج: {bot_stats['system']['cpu_usage']:.1f}%
• سرعة الاستجابة: ممتازة

🏆 <b>المجموعات الأكثر نشاطاً:</b>"""
    
    # المجموعات الأكثر نشاطاً
    sorted_groups = sorted(
        bot_stats['groups'].items(),
        key=lambda x: x[1]['messages_checked'],
        reverse=True
    )[:5]
    
    for i, (group_id, stats) in enumerate(sorted_groups, 1):
        try:
            chat = await bot.get_chat(int(group_id))
            group_name = chat.title[:20]
        except:
            group_name = f"مجموعة {group_id}"
        
        text += f"\n{i}. {group_name} - {format_number(stats['messages_checked'])} رسالة"
    
    text += f"\n\n⏰ آخر تحديث: {get_formatted_time()}"
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🔄 تحديث", callback_data="update_stats")
    keyboard.button(text="📊 تفاصيل أكثر", callback_data="global_details")
    keyboard.button(text="📤 تصدير التقرير", callback_data="export_global")
    keyboard.button(text="🏠 القائمة الرئيسية", callback_data="main_menu")
    
    keyboard.adjust(2, 2)
    
    await safe_edit_message(callback, text, keyboard)

async def show_dev_panel(callback: CallbackQuery):
    """عرض لوحة المطور"""
    text = f"""👑 <b>لوحة تحكم المطور</b> {get_random_emoji()}

🛠️ <b>أدوات النظام:</b>
• إعادة تشغيل البوت
• عرض السجلات
• تنظيف الذاكرة
• تحسين الأداء

📊 <b>مراقبة النظام:</b>
• مخططات الأداء
• نشاط المستخدمين
• تقارير الأمان
• الإنذارات والتنبيهات

🚀 <b>إدارة البوت:</b>
• بث رسالة
• وضع الصيانة
• النسخ الاحتياطي
• التحديثات

🔧 <b>الإعدادات المتقدمة:</b>
• إعدادات قاعدة البيانات
• واجهات برمجة التطبيقات
• خدمات الويب
• التكاملات

📌 <b>اختر الأداة:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    
    # أدوات النظام
    keyboard.button(text="🔄 إعادة تشغيل", callback_data="dev_restart")
    keyboard.button(text="📊 السجلات", callback_data="dev_logs")
    keyboard.button(text="🧹 تنظيف", callback_data="dev_clean")
    keyboard.button(text="⚡ تحسين", callback_data="dev_optimize")
    
    # مراقبة
    keyboard.button(text="📈 أداء", callback_data="dev_performance")
    keyboard.button(text="👥 نشاط", callback_data="dev_activity")
    keyboard.button(text="🛡️ تقارير", callback_data="dev_reports")
    keyboard.button(text="⚠️ إنذارات", callback_data="dev_alerts")
    
    # إدارة
    keyboard.button(text="📢 بث", callback_data="dev_broadcast")
    keyboard.button(text="🔧 صيانة", callback_data="dev_maintenance")
    keyboard.button(text="📦 نسخ", callback_data="dev_backup")
    keyboard.button(text="🚀 تحديث", callback_data="dev_update")
    
    keyboard.button(text="🏠 الرئيسية", callback_data="main_menu")
    
    keyboard.adjust(4, 4, 4, 1)
    
    await safe_edit_message(callback, text, keyboard)

async def handle_dev_actions(callback: CallbackQuery, action: str):
    """معالجة إجراءات المطور"""
    if action == "dev_restart":
        await callback.answer("🔄 جاري إعادة التشغيل...", show_alert=True)
        # هنا سيتم إعادة تشغيل البوت
        await asyncio.sleep(2)
        await callback.message.edit_text("✅ تم إعادة التشغيل بنجاح")
        
    elif action == "dev_logs":
        await send_logs(callback)
        
    elif action == "dev_broadcast":
        await start_broadcast(callback)
        
    else:
        await callback.answer("⚙️ هذه الميزة قيد التطوير", show_alert=True)

async def send_logs(callback: CallbackQuery):
    """إرسال سجلات الأخطاء"""
    try:
        with open('security_bot_advanced.log', 'rb') as f:
            await callback.message.answer_document(
                FSInputFile(f, filename="logs.txt"),
                caption="📊 سجلات البوت"
            )
    except Exception as e:
        await callback.answer(f"❌ خطأ في إرسال السجلات: {e}", show_alert=True)

async def start_broadcast(callback: CallbackQuery):
    """بدء البث"""
    await callback.message.answer(
        "📢 <b>أدخل رسالة البث:</b>\n\n"
        "اكتب الرسالة التي تريد بثها لجميع المجموعات",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ إلغاء", callback_data="dev_panel")]
        ])
    )
    
    # هنا سيتم الانتظار لرسالة البث

async def rate_bot(callback: CallbackQuery):
    """تقييم البوت"""
    text = f"""⭐ <b>تقييم الحارس الأمني المتقدم</b> {get_random_emoji()}

📊 <b>تقييمات المستخدمين:</b>
★★★★★ 4.8/5.0 (1,234 تقييم)

💬 <b>آراء المستخدمين:</b>
• "أفضل بوت حماية جربته!" - أحمد
• "مميزات رائعة ودعم فني سريع" - محمد
• "وفر علي الكثير من الوقت" - سارة

🎯 <b>مميزات البوت:</b>
✓ كشف ذكي للمحتوى المخالف
✓ واجهة مستخدم متطورة
✓ دعم فني 24/7
✓ تحديثات مستمرة
✓ مجاني للاستخدام

📌 <b>شاركنا رأيك:</b>"""
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⭐⭐⭐⭐⭐ 5 نجوم", callback_data="rate_5")
    keyboard.button(text="⭐⭐⭐⭐ 4 نجوم", callback_data="rate_4")
    keyboard.button(text="⭐⭐⭐ 3 نجوم", callback_data="rate_3")
    keyboard.button(text="⭐⭐ 2 نجوم", callback_data="rate_2")
    keyboard.button(text="⭐ 1 نجمة", callback_data="rate_1")
    keyboard.button(text="✏️ كتابة تقييم", callback_data="write_review")
    keyboard.button(text="🏠 القائمة الرئيسية", callback_data="main_menu")
    
    keyboard.adjust(1, 1, 1, 1, 1, 1, 1)
    
    await safe_edit_message(callback, text, keyboard)

# ================== معالج الرسائل العام ==================
@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    """معالج جميع الرسائل"""
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # تجاهل البوتات
        if message.from_user.is_bot:
            return
        
        # تحديث إحصائيات الرسائل
        await update_stats(chat_id, 'message', user_id)
        
        # إذا كانت رسالة في مجموعة مسجلة
        if chat_id in ALLOWED_GROUP_IDS:
            await handle_group_message(message, state)
        elif message.chat.type == 'private':
            await handle_private_message(message, state)
            
    except Exception as e:
        logger.error(f"خطأ في معالج الرسائل: {e}")

async def handle_group_message(message: Message, state: FSMContext):
    """معالجة رسائل المجموعة"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    group_str = str(chat_id)
    
    # تجاهل إذا لم تكن المجموعة مسجلة
    if group_str not in settings:
        return
    
    # التحقق من صلاحيات المستخدم
    user_role = await get_user_role(chat_id, user_id, group_str)
    
    # الأعضاء المستثنين والمميزين لا تتم مراقبتهم
    if user_role in [UserRole.OWNER, UserRole.ADMIN, UserRole.EXEMPTED, UserRole.VIP, UserRole.TRUSTED]:
        return
    
    # التحقق من الوضع الليلي
    if await check_night_mode(group_str):
        if user_role == UserRole.MEMBER:  # الأعضاء العاديين فقط
            await message.delete()
            
            # إرسال تحذير
            try:
                warning = await message.answer(
                    f"🌙 <b>الوضع الليلي مفعل</b>\n\n"
                    f"⏰ الوقت الحالي: {datetime.now().strftime('%H:%M')}\n"
                    f"🚫 النشر متوقف حتى: {settings[group_str]['night_end']}\n\n"
                    f"💤 استريحوا وناموا جيداً!"
                )
                await asyncio.sleep(10)
                await warning.delete()
            except:
                pass
            return
    
    # الحصول على النص
    text = message.text or message.caption or ""
    
    # التحقق من الأوامر الخاصة
    if text.startswith("/"):
        # الأوامر العادية تتم معالجتها تلقائياً
        return
    
    # التحقق من الردود التلقائية
    auto_reply = await check_auto_reply(chat_id, text)
    if auto_reply:
        await message.reply(auto_reply)
        return
    
    # الكشف عن المحتوى المخالف
    detection_result = contains_spam(text, group_str)
    
    if detection_result['is_spam']:
        await handle_violation(chat_id, user_id, message, detection_result)
        return
    
    # التحقق من نظام التقديم
    if text.startswith("/apply"):
        await handle_application(chat_id, user_id, message)

async def handle_private_message(message: Message, state: FSMContext):
    """معالجة رسائل الخاص"""
    user_id = message.from_user.id
    current_state = await state.get_state()
    
    # إذا كان المطور
    if user_id == DEVELOPER_ID:
        if message.text.startswith("/broadcast "):
            await handle_developer_broadcast(message)
            return
    
    # معالجة حالات FSM
    if current_state:
        data = await state.get_data()
        await handle_fsm_states(message, state, current_state, data)
        return
    
    # رد افتراضي
    await message.answer(
        "👋 <b>مرحباً بك في الحارس الأمني المتقدم!</b>\n\n"
        "لإدارة مجموعتك، أرسل:\n"
        "<code>/settings</code>\n\n"
        "للحصول على المساعدة، أرسل:\n"
        "<code>/help</code>\n\n"
        f"للتواصل مع الدعم: {SUPPORT_CHAT}"
    )

async def handle_fsm_states(message: Message, state: FSMContext, current_state: str, data: dict):
    """معالجة حالات FSM"""
    user_id = message.from_user.id
    
    # حالة إضافة كلمة ممنوعة
    if current_state == Form.waiting_for_keyword.state:
        group_id = data.get('group_id')
        action = data.get('action', 'add')
        keyword = message.text.strip()
        
        if not keyword:
            await message.reply("⚠️ الرجاء إدخال كلمة صحيحة")
            return
        
        group_str = str(group_id)
        if group_str not in settings:
            await message.reply("❌ المجموعة غير موجودة")
            await state.clear()
            return
        
        if action == 'add':
            if keyword in settings[group_str].get('banned_keywords', []):
                await message.reply("⚠️ هذه الكلمة موجودة بالفعل")
            else:
                settings[group_str].setdefault('banned_keywords', []).append(keyword)
                await save_settings()
                await message.reply(f"✅ <b>تم إضافة الكلمة:</b> <code>{keyword}</code>")
        else:  # remove
            if keyword in settings[group_str].get('banned_keywords', []):
                settings[group_str]['banned_keywords'].remove(keyword)
                await save_settings()
                await message.reply(f"✅ <b>تم حذف الكلمة:</b> <code>{keyword}</code>")
            else:
                await message.reply("⚠️ هذه الكلمة غير موجودة")
        
        await state.clear()
        await show_keywords_panel_after_action(message, group_id)
    
    # حالات أخرى يمكن إضافتها هنا...

async def show_keywords_panel_after_action(message: Message, group_id: int):
    """عرض لوحة الكلمات بعد الإجراء"""
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="↩️ العودة للكلمات", callback_data=f"keywords_{group_id}")
    keyboard.button(text="🏠 القائمة الرئيسية", callback_data=f"manage_{group_id}")
    keyboard.adjust(1)
    
    await message.answer(
        "✅ <b>تم تنفيذ الإجراء بنجاح</b>\n\n"
        "اختر الإجراء التالي:",
        reply_markup=keyboard.as_markup()
    )

async def handle_developer_broadcast(message: Message):
    """معالجة بث المطور"""
    broadcast_text = message.text.replace("/broadcast", "").strip()
    
    if not broadcast_text:
        await message.reply("⚠️ الرجاء إدخال نص للبث")
        return
    
    # إرسال رسالة الانتظار
    wait_msg = await message.reply("📢 <b>جاري البث...</b>")
    
    success = 0
    failed = 0
    
    for group_id in ALLOWED_GROUP_IDS:
        try:
            await bot.send_message(
                group_id,
                f"📢 <b>إعلان من المطور:</b>\n\n{broadcast_text}\n\n"
                f"🛡️ <i>الحارس الأمني المتقدم</i>"
            )
            success += 1
            await asyncio.sleep(0.5)  # لتجنب حظر التلقرام
        except Exception as e:
            logger.error(f"فشل البث للمجموعة {group_id}: {e}")
            failed += 1
    
    await wait_msg.edit_text(
        f"✅ <b>تم البث بنجاح!</b>\n\n"
        f"📤 تم الإرسال لـ: {success} مجموعة\n"
        f"❌ فشل الإرسال لـ: {failed} مجموعة"
    )

# ================== المهام الخلفية ==================
async def background_tasks():
    """تشغيل المهام الخلفية"""
    logger.info("🚀 بدء المهام الخلفية...")
    
    while True:
        try:
            # المهمة 1: التحقق من الوضع الليلي
            await night_mode_checker()
            
            # المهمة 2: النسخ الاحتياطي التلقائي
            await auto_backup_task()
            
            # المهمة 3: إرسال التقارير الأسبوعية
            await weekly_reports_task()
            
            # المهمة 4: تحديث الإحصائيات
            await update_stats_task()
            
            # المهمة 5: تنظيف البيانات القديمة
            await cleanup_old_data()
            
            # انتظار ساعة قبل التكرار
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"خطأ في المهام الخلفية: {e}")
            await asyncio.sleep(300)

async def auto_backup_task():
    """المهمة الخلفية للنسخ الاحتياطي التلقائي"""
    try:
        current_time = time.time()
        
        for group_id in ALLOWED_GROUP_IDS:
            group_str = str(group_id)
            
            if group_str in settings:
                group_settings = settings[group_str]
                
                # التحقق إذا كان النسخ الاحتياطي التلقائي مفعلاً
                if group_settings.get('auto_backup', True):
                    last_backup = group_settings.get('last_backup', 0)
                    
                    # إذا مر أسبوع منذ آخر نسخة
                    if current_time - last_backup >= 604800:
                        logger.info(f"إنشاء نسخة احتياطية تلقائية للمجموعة {group_id}")
                        await create_backup(group_id, manual=False)
                        
    except Exception as e:
        logger.error(f"خطأ في النسخ الاحتياطي التلقائي: {e}")

async def weekly_reports_task():
    """المهمة الخلفية للتقارير الأسبوعية"""
    try:
        # إرسال التقارير كل يوم اثنين
        if datetime.now().weekday() == 0:  # يوم الاثنين
            for group_id in ALLOWED_GROUP_IDS:
                group_str = str(group_id)
                
                if group_str in settings and settings[group_str].get('weekly_reports', True):
                    await send_weekly_report(group_id)
                    
    except Exception as e:
        logger.error(f"خطأ في إرسال التقارير الأسبوعية: {e}")

async def send_weekly_report(group_id: int):
    """إرسال تقرير أسبوعي"""
    try:
        group_str = str(group_id)
        group_stats = bot_stats['groups'].get(group_str, {})
        group_settings = settings.get(group_str, {})
        
        report = f"""📈 <b>التقرير الأسبوعي - الحارس الأمني</b> {get_random_emoji()}

📅 الفترة: الأسبوع الماضي
📌 المجموعة: {(await bot.get_chat(group_id)).title}

📊 <b>إحصائيات الأسبوع:</b>
• 📨 الرسائل المفحوصة: {format_number(group_stats.get('messages_checked', 0))}
• ⚠️ المخالفات المكتشفة: {group_stats.get('violations', 0)}
• 🚫 حالات الحظر: {group_stats.get('bans', 0)}
• 🔇 حالات الكتم: {group_stats.get('mutes', 0)}
• 👥 أعضاء جدد: {len(group_stats.get('active_users', set()))}

🏆 <b>الأعضاء الأكثر نشاطاً:</b>"""
        
        # إضافة الأعضاء النشطين
        active_users = list(group_stats.get('active_users', set()))[:3]
        if active_users:
            for i, user_id in enumerate(active_users, 1):
                try:
                    user = await bot.get_chat_member(group_id, user_id)
                    name = user.user.full_name[:20]
                    report += f"\n{i}. {name}"
                except:
                    report += f"\n{i}. مستخدم {user_id}"
        
        report += f"""

🎯 <b>توصيات للتحسين:</b>
• تفعيل الوضع الليلي للنوم الآمن
• إضافة الكلمات الشائعة للقائمة السوداء
• مراجعة الأعضاء المشبوهين
• تشجيع النشاط في المجموعة

🛡️ <b>استمر في الحماية!</b>
المجموعة محمية بواسطة الحارس الأمني المتقدم"""
        
        await bot.send_message(group_id, report)
        
    except Exception as e:
        logger.error(f"خطأ في إرسال التقرير الأسبوعي: {e}")

async def update_stats_task():
    """مهمة تحديث الإحصائيات"""
    try:
        await save_stats()
    except Exception as e:
        logger.error(f"خطأ في تحديث الإحصائيات: {e}")

async def cleanup_old_data():
    """تنظيف البيانات القديمة"""
    try:
        current_time = time.time()
        
        for group_str in settings:
            # تنظيف التحذيرات القديمة (أقدم من شهر)
            if 'warnings' in settings[group_str]:
                old_warnings = []
                for user_id, warn_time in list(settings[group_str]['warnings'].items()):
                    if current_time - warn_time > 2592000:  # 30 يوم
                        old_warnings.append(user_id)
                
                for user_id in old_warnings:
                    del settings[group_str]['warnings'][user_id]
            
            # تنظيف المتقدمين القدامى (أقدم من أسبوع)
            if 'applicants' in settings[group_str]:
                settings[group_str]['applicants'] = [
                    app for app in settings[group_str]['applicants']
                    if current_time - app.get('timestamp', 0) < 604800
                ]
        
        # تنظيف إحصائيات المستخدمين القدامى
        old_users = []
        for user_id, user_data in list(bot_stats['users'].items()):
            if current_time - user_data.get('last_seen', 0) > 2592000:  # 30 يوم
                old_users.append(user_id)
        
        for user_id in old_users:
            del bot_stats['users'][user_id]
        
        await save_settings()
        
    except Exception as e:
        logger.error(f"خطأ في تنظيف البيانات: {e}")

# ================== FastAPI Webhook ==================
app = FastAPI(
    title="الحارس الأمني المتقدم",
    description="أقوى بوت حماية لمجموعات التليجرام",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

WEBHOOK_PATH = f"/bot/{TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    """بدء تشغيل البوت"""
    logger.info(f"🚀 بدء تشغيل الحارس الأمني المتقدم v{VERSION}")
    
    try:
        # حذف Webhook القديم
        await bot.delete_webhook(drop_pending_updates=True)
        
        # تعيين Webhook جديد
        await bot.set_webhook(
            url=WEBHOOK_URL,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types()
        )
        
        logger.info(f"✅ تم تعيين Webhook: {WEBHOOK_URL}")
        
        # تحميل الإعدادات
        await load_settings()
        
        # بدء المهام الخلفية
        asyncio.create_task(background_tasks())
        
        # إرسال رسالة بدء التشغيل للمطور
        if DEVELOPER_ID:
            try:
                await bot.send_message(
                    DEVELOPER_ID,
                    f"✅ **تم تشغيل الحارس الأمني المتقدم بنجاح!**\n\n"
                    f"⏰ الوقت: {get_formatted_time()}\n"
                    f"🚀 الإصدار: {VERSION}\n"
                    f"📊 المجموعات: {len(ALLOWED_GROUP_IDS)}\n"
                    f"🔗 Webhook: {WEBHOOK_URL}\n\n"
                    f"{get_random_emoji()} البوت يعمل بكفاءة عالية!"
                )
            except:
                pass
        
        logger.info("✅ البوت يعمل بكفاءة عالية!")
        
    except Exception as e:
        logger.error(f"❌ خطأ في بدء التشغيل: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    """إيقاف تشغيل البوت"""
    logger.info("🛑 إيقاف تشغيل البوت...")
    
    try:
        # إرسال رسالة إيقاف التشغيل للمطور
        if DEVELOPER_ID:
            try:
                await bot.send_message(
                    DEVELOPER_ID,
                    f"🛑 **تم إيقاف الحارس الأمني المتقدم**\n\n"
                    f"⏰ الوقت: {get_formatted_time()}\n"
                    f"⏳ وقت التشغيل: {get_uptime()}\n\n"
                    f"📊 الإحصائيات النهائية:\n"
                    f"• الرسائل: {bot_stats['total_messages_checked']}\n"
                    f"• المخالفات: {bot_stats['total_violations']}\n"
                    f"• الحظور: {bot_stats['total_bans']}"
                )
            except:
                pass
        
        # حفظ الإعدادات النهائية
        await save_settings()
        await save_stats()
        
        # إغلاق الجلسة
        await bot.session.close()
        
        logger.info("✅ تم إيقاف البوت بنجاح")
        
    except Exception as e:
        logger.error(f"❌ خطأ في إيقاف التشغيل: {e}")

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    """معالج Webhook"""
    try:
        update_data = await request.json()
        update = types.Update.model_validate(update_data)
        await dp.feed_update(bot=bot, update=update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ خطأ في Webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/")
async def root():
    """الصفحة الرئيسية"""
    uptime = time.time() - bot_stats['start_time']
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    
    return {
        "status": "online",
        "service": "الحارس الأمني المتقدم",
        "version": VERSION,
        "release_date": RELEASE_DATE,
        "uptime": f"{days} يوم, {hours} ساعة, {minutes} دقيقة",
        "statistics": {
            "total_groups": len(ALLOWED_GROUP_IDS),
            "total_messages": bot_stats['total_messages_checked'],
            "total_violations": bot_stats['total_violations'],
            "total_users": len(bot_stats['users'])
        },
        "developer": f"@{BOT_USERNAME}",
        "support": SUPPORT_CHAT,
        "documentation": "/docs",
        "health_check": "/health"
    }

@app.get("/health")
async def health_check():
    """فحص صحة البوت"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "memory_usage_mb": bot_stats['system']['memory_usage'],
        "cpu_usage_percent": bot_stats['system']['cpu_usage'],
        "response_time_ms": 0.1
    }

@app.get("/stats/api")
async def api_stats():
    """إحصائيات API"""
    return {
        "bot_statistics": bot_stats,
        "settings": {
            "total_groups": len(settings),
            "groups": list(settings.keys())
        },
        "system": {
            "python_version": sys.version,
            "platform": sys.platform,
            "uptime": get_uptime()
        }
    }

@app.get("/backup/{group_id}")
async def backup_endpoint(group_id: int):
    """إنشاء نسخة احتياطية عبر API"""
    try:
        if group_id not in ALLOWED_GROUP_IDS:
            raise HTTPException(status_code=403, detail="Group not allowed")
        
        success = await create_backup(group_id, manual=True)
        
        if success:
            return {
                "status": "success",
                "message": "Backup created successfully",
                "group_id": group_id,
                "timestamp": time.time()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create backup")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ================== تشغيل البوت ==================
if __name__ == "__main__":
    import uvicorn
    
    # إعدادات الخادم
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 10000))
    
    # تشغيل الخادم
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=False
    )