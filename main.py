import asyncio
import logging
import os
import re
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from enum import Enum
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ================== الإعدادات الأساسية ==================
TOKEN = os.getenv("TOKEN")

ALLOWED_GROUP_IDS = [-1001224326322, -1002370282238]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# قاعدة البيانات في قناة تيليجرام
DB_CHAT_ID = -1002370282238
SETTINGS_MESSAGE_ID = None

# ================== تعريف الأنظمة ==================

class ListType(Enum):
    """أنواع القوائم الذكية"""
    BLACK = "black"      # القائمة السوداء - منع تام
    WHITE = "white"      # القائمة البيضاء - إعفاء كامل
    GRAY = "gray"        # القائمة الرمادية - مراقبة مشددة
    KEYWORDS = "keywords" # قائمة الكلمات المفتاحية

class SmartListsSystem:
    """نظام القوائم الذكي"""
    def __init__(self):
        self.lists_enabled = True
        self.list_status = {
            ListType.BLACK: True,
            ListType.WHITE: True,
            ListType.GRAY: False,
            ListType.KEYWORDS: False
        }
        
        # تخزين القوائم
        self.lists = {
            ListType.BLACK: {
                "users": set(),     # معرفات المستخدمين
                "keywords": set(),  # كلمات ممنوعة
                "urls": set(),      # روابط ممنوعة
                "phones": set()     # أرقام ممنوعة
            },
            ListType.WHITE: {
                "users": set(),     # مستخدمون معفون
                "urls": set()       # روابط مسموحة
            },
            ListType.GRAY: {
                "users": set()      # مستخدمون تحت المراقبة
            },
            ListType.KEYWORDS: {
                "spam_keywords": set(),    # كلمات سبام
                "ad_keywords": set(),      # كلمات إعلانية
                "suspicious_keywords": set() # كلمات مشبوهة
            }
        }
        
        # إحصائيات
        self.stats = {
            "blocks_today": 0,
            "total_blocks": 0,
            "last_updated": datetime.now()
        }
    
    async def check_user(self, user_id: int, list_type: ListType = None) -> bool:
        """فحص المستخدم في القوائم"""
        if not self.lists_enabled:
            return False
        
        if list_type:
            return user_id in self.lists[list_type]["users"]
        else:
            for ltype, enabled in self.list_status.items():
                if enabled and user_id in self.lists[ltype]["users"]:
                    return True
            return False
    
    async def check_keywords(self, text: str) -> Dict:
        """فحص الكلمات المفتاحية"""
        result = {
            "found_keywords": [],
            "category": None,
            "score": 0
        }
        
        if not self.list_status[ListType.KEYWORDS]:
            return result
        
        text_lower = text.lower()
        
        # فحص كل فئة
        for category, keywords in self.lists[ListType.KEYWORDS].items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    result["found_keywords"].append(keyword)
                    result["category"] = category
                    result["score"] += 1
        
        return result
    
    async def check_message(self, message_text: str, user_id: int) -> dict:
        """فحص الرسالة في جميع القوائم"""
        result = {
            "blocked": False,
            "reason": "",
            "list_type": None,
            "matches": [],
            "action": "none"  # none, warn, mute, ban
        }
        
        if not self.lists_enabled:
            return result
        
        # فحص المستخدم في القائمة السوداء
        if self.list_status[ListType.BLACK] and user_id in self.lists[ListType.BLACK]["users"]:
            result.update({
                "blocked": True,
                "reason": "👤 المستخدم في القائمة السوداء",
                "list_type": ListType.BLACK,
                "action": "ban"
            })
            return result
        
        # فحص المستخدم في القائمة البيضاء (إعفاء)
        if self.list_status[ListType.WHITE] and user_id in self.lists[ListType.WHITE]["users"]:
            return result
        
        # فحص الكلمات المفتاحية
        if self.list_status[ListType.KEYWORDS]:
            keyword_check = await self.check_keywords(message_text)
            if keyword_check["score"] > 0:
                category_name = {
                    "spam_keywords": "سبام",
                    "ad_keywords": "إعلان",
                    "suspicious_keywords": "مشبوه"
                }.get(keyword_check["category"], "غير معروف")
                
                result.update({
                    "blocked": keyword_check["score"] >= 2,
                    "reason": f"🔤 كلمات {category_name} ({', '.join(keyword_check['found_keywords'][:3])})",
                    "list_type": ListType.KEYWORDS,
                    "matches": keyword_check["found_keywords"],
                    "action": "mute" if keyword_check["score"] >= 2 else "warn"
                })
        
        # فحص الروابط في القائمة السوداء
        if self.list_status[ListType.BLACK]:
            urls = re.findall(r'https?://[^\s]+', message_text, re.IGNORECASE)
            for url in urls:
                for blocked_url in self.lists[ListType.BLACK]["urls"]:
                    if blocked_url.lower() in url.lower():
                        result["matches"].append(f"🔗 رابط محظور: {blocked_url}")
                        result["blocked"] = True
                        result["reason"] = "🔗 رابط في القائمة السوداء"
                        result["action"] = "delete"
                        break
        
        # فحص الأرقام في القائمة السوداء
        if self.list_status[ListType.BLACK]:
            phones = re.findall(r'\b\d[\d\s\-\.]{7,}\d\b', message_text)
            for phone in phones:
                clean_phone = re.sub(r'[\s\-\.]', '', phone)
                for blocked_phone in self.lists[ListType.BLACK]["phones"]:
                    if blocked_phone in clean_phone:
                        result["matches"].append(f"📞 رقم محظور: {blocked_phone}")
                        result["blocked"] = True
                        result["reason"] = "📞 رقم في القائمة السوداء"
                        result["action"] = "mute"
                        break
        
        if result["blocked"]:
            self.stats["blocks_today"] += 1
            self.stats["total_blocks"] += 1
        
        return result
    
    async def add_to_list(self, list_type: ListType, item_type: str, value: str) -> bool:
        """إضافة عنصر إلى قائمة"""
        if item_type in self.lists[list_type]:
            if item_type == "users":
                self.lists[list_type][item_type].add(int(value))
            else:
                self.lists[list_type][item_type].add(value)
            self.stats["last_updated"] = datetime.now()
            return True
        return False
    
    async def remove_from_list(self, list_type: ListType, item_type: str, value: str) -> bool:
        """إزالة عنصر من قائمة"""
        if item_type in self.lists[list_type]:
            if item_type == "users":
                self.lists[list_type][item_type].discard(int(value))
            else:
                self.lists[list_type][item_type].discard(value)
            return True
        return False
    
    async def get_list_info(self, list_type: ListType) -> dict:
        """الحصول على معلومات القائمة"""
        return {
            "enabled": self.list_status[list_type],
            "counts": {k: len(v) for k, v in self.lists[list_type].items()},
            "last_updated": self.stats["last_updated"]
        }
    
    async def toggle_list(self, list_type: ListType, enabled: bool = None) -> bool:
        """تفعيل/إيقاف قائمة محددة"""
        if enabled is None:
            enabled = not self.list_status[list_type]
        
        self.list_status[list_type] = enabled
        return enabled
    
    async def toggle_system(self, enabled: bool = None) -> bool:
        """تفعيل/إيقاف النظام كاملاً"""
        if enabled is None:
            enabled = not self.lists_enabled
        
        self.lists_enabled = enabled
        return enabled
    
    async def export_lists(self) -> dict:
        """تصدير جميع القوائم"""
        export_data = {
            "system_enabled": self.lists_enabled,
            "lists_status": {k.value: v for k, v in self.list_status.items()},
            "lists": {},
            "stats": self.stats
        }
        
        for list_type, items in self.lists.items():
            export_data["lists"][list_type.value] = {}
            for item_type, values in items.items():
                if isinstance(values, set):
                    export_data["lists"][list_type.value][item_type] = list(values)
                else:
                    export_data["lists"][list_type.value][item_type] = values
        
        return export_data
    
    async def import_lists(self, data: dict):
        """استيراد القوائم"""
        if "system_enabled" in data:
            self.lists_enabled = data["system_enabled"]
        
        if "lists_status" in data:
            for list_str, status in data["lists_status"].items():
                try:
                    list_type = ListType(list_str)
                    self.list_status[list_type] = status
                except:
                    continue
        
        if "lists" in data:
            for list_str, items in data["lists"].items():
                try:
                    list_type = ListType(list_str)
                    for item_type, values in items.items():
                        if item_type in self.lists[list_type]:
                            if isinstance(self.lists[list_type][item_type], set):
                                self.lists[list_type][item_type] = set(values)
                            else:
                                self.lists[list_type][item_type] = values
                except:
                    continue

# ================== نظام كشف الأرقام المحسن ==================

def normalize_digits(text: str) -> str:
    """تحويل الأرقام العربية والفارسية إلى لاتينية"""
    arabic_to_latin = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹',
        '01234567890123456789'
    )
    return text.translate(arabic_to_latin)

def extract_phone_numbers(text: str) -> List[str]:
    """استخراج الأرقام الهاتفية من النص"""
    normalized = normalize_digits(text)
    
    # أنماط متنوعة للأرقام
    patterns = [
        r'(?:\+?966|00966|966|0?5)[\d\s\-\.]{8,}',  # أرقام سعودية
        r'(?:\+?[1-9]\d{0,3}[\s\-\.]?)?[\d\s\-\.]{9,}',  # أرقام دولية
        r'\d[\d\s\-\.]{7,}\d',  # أرقام عامة
    ]
    
    phones = []
    for pattern in patterns:
        matches = re.finditer(pattern, normalized)
        for match in matches:
            phone = re.sub(r'[\s\-\.]', '', match.group())
            if 8 <= len(phone) <= 15 and phone.isdigit():
                phones.append(phone)
    
    return list(set(phones))  # إزالة التكرارات

def contains_phone_context(text: str) -> bool:
    """الكشف عن السياق الذي يشير إلى رقم هاتف"""
    context_patterns = [
        r'(?:اتصل|رقمي|واتس|هاتف|موبايل|mobile|phone|call|contact|whatsapp)[^\d]{0,10}[\d\s\-\.]{8,}',
        r'[\d\s\-\.]{8,}.*?(?:اتصل|رقمي|واتس|هاتف|موبايل)',
        r'📞.*?[\d\s\-\.]{8,}',
        r'[\d\s\-\.]{8,}.*?📞',
    ]
    
    for pattern in context_patterns:
        if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
            return True
    
    return False

# ================== نظام كشف الروابط المحسن ==================

class LinkAnalysisSystem:
    """نظام تحليل الروابط"""
    def __init__(self):
        # نطاقات مسموحة افتراضياً
        self.allowed_domains = {
            "youtube.com", "youtu.be",
            "instagram.com", "instagr.am",
            "x.com", "twitter.com",
            "facebook.com", "fb.com",
            "linkedin.com", "tiktok.com",
            "snapchat.com", "pinterest.com",
            "reddit.com", "discord.gg",
        }
        
        # نطاقات مشبوهة (مجموعات وقنوات)
        self.suspicious_patterns = [
            r'(?:t\.me|telegram\.me)/(?:joinchat/|\+)[\w\-]+',  # روابط انضمام
            r'(?:t\.me|telegram\.me)/[^\s/]+/[\d]+',  # روابط مشاركات
            r'@[\w]{5,}',  # معرفات
        ]
        
        # روابط مختصرة
        self.short_link_domains = {
            "bit.ly", "tinyurl.com", "goo.gl", "t.co",
            "ow.ly", "is.gd", "buff.ly", "shorte.st",
            "adf.ly", "bc.vc", "bitly.com", "cutt.ly",
        }
        
        # مواقع التواصل الأخرى
        self.other_messaging = {
            "whatsapp.com", "chat.whatsapp.com", "wa.me",
            "wechat.com", "line.me", "kakao.com",
            "signal.org", "viber.com", "skype.com",
        }
    
    def analyze_url(self, url: str) -> Dict:
        """تحليل الرابط وإرجاع معلومات عنه"""
        result = {
            "url": url,
            "is_telegram_group": False,
            "is_telegram_channel": False,
            "is_telegram_invite": False,
            "is_whatsapp": False,
            "is_short_link": False,
            "is_allowed_social": False,
            "is_other_messaging": False,
            "domain": "",
            "risk_level": "low",  # low, medium, high
            "reason": ""
        }
        
        try:
            # إضافة https:// إذا لم يكن موجوداً
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            result["domain"] = domain
            
            # إزالة www
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # التحقق من نطاقات مواقع التواصل المسموحة
            for allowed_domain in self.allowed_domains:
                if allowed_domain in domain:
                    result["is_allowed_social"] = True
                    result["risk_level"] = "low"
                    result["reason"] = "موقع تواصل مسموح"
                    return result
            
            # التحقق من نطاقات التواصل الأخرى
            for msg_domain in self.other_messaging:
                if msg_domain in domain:
                    result["is_other_messaging"] = True
                    result["risk_level"] = "high"
                    result["reason"] = "منصة مراسلة أخرى"
                    return result
            
            # التحقق من الروابط المختصرة
            for short_domain in self.short_link_domains:
                if short_domain in domain:
                    result["is_short_link"] = True
                    result["risk_level"] = "high"
                    result["reason"] = "رابط مختصر"
                    return result
            
            # التحقق من روابط تيليجرام
            if 't.me' in domain or 'telegram.me' in domain:
                path = parsed.path.lower()
                
                # روابط انضمام للمجموعات
                if '/joinchat/' in path or '/+' in path:
                    result["is_telegram_invite"] = True
                    result["risk_level"] = "high"
                    result["reason"] = "رابط دعوة تيليجرام"
                
                # روابط المجموعات العامة
                elif len(path.split('/')) == 2 and path != '/':
                    result["is_telegram_group"] = True
                    result["risk_level"] = "medium"
                    result["reason"] = "رابط مجموعة تيليجرام"
                
                # روابط القنوات
                elif path.startswith('/c/') or path.startswith('/channel/'):
                    result["is_telegram_channel"] = True
                    result["risk_level"] = "medium"
                    result["reason"] = "رابط قناة تيليجرام"
            
            # إذا كان نطاق غير معروف
            if result["risk_level"] == "low":
                result["risk_level"] = "medium"
                result["reason"] = "رابط خارجي غير معروف"
        
        except Exception as e:
            logger.error(f"خطأ في تحليل الرابط: {e}")
            result["risk_level"] = "high"
            result["reason"] = "خطأ في تحليل الرابط"
        
        return result
    
    def extract_urls(self, text: str) -> List[str]:
        """استخراج جميع الروابط من النص"""
        url_pattern = r'https?://[^\s]+|www\.[^\s]+\.[^\s]{2,}|[\w\-]+\.[\w]{2,3}(?:\.[\w]{2,3})?/[^\s]*'
        matches = re.findall(url_pattern, text, re.IGNORECASE)
        return list(set(matches))  # إزالة التكرارات
    
    def check_text_urls(self, text: str) -> Dict:
        """فحص جميع الروابط في النص"""
        urls = self.extract_urls(text)
        results = []
        high_risk_count = 0
        medium_risk_count = 0
        
        for url in urls:
            analysis = self.analyze_url(url)
            results.append(analysis)
            
            if analysis["risk_level"] == "high":
                high_risk_count += 1
            elif analysis["risk_level"] == "medium":
                medium_risk_count += 1
        
        return {
            "total_urls": len(urls),
            "high_risk": high_risk_count,
            "medium_risk": medium_risk_count,
            "results": results,
            "has_high_risk": high_risk_count > 0,
            "has_medium_risk": medium_risk_count > 0
        }

# ================== نظام حماية الأعضاء الجدد ==================

class NewMemberProtection:
    """نظام حماية وتخفيف القيود"""
    def __init__(self):
        self.member_join_dates = {}
        self.restriction_levels = {
            "hour_1": {  # أول ساعة
                "max_messages": 3,
                "allow_links": False,
                "allow_phones": False,
                "strict_mode": True
            },
            "day_1": {  # أول يوم
                "max_messages_per_hour": 10,
                "allow_social_links": True,
                "allow_external_links": False,
                "strict_mode": True
            },
            "week_1": {  # أول أسبوع
                "max_messages_per_hour": 20,
                "allow_all_links": True,
                "warning_on_suspicious": True,
                "strict_mode": False
            }
        }
    
    async def track_member_join(self, user_id: int):
        """تسجيل تاريخ انضمام العضو"""
        self.member_join_dates[user_id] = datetime.now()
    
    def get_member_status(self, user_id: int) -> Dict:
        """الحصول على حالة العضو"""
        if user_id not in self.member_join_dates:
            return {
                "is_new": False,
                "restriction_level": "veteran",
                "days_since_join": 999
            }
        
        join_date = self.member_join_dates[user_id]
        time_diff = datetime.now() - join_date
        
        hours = time_diff.total_seconds() / 3600
        days = time_diff.days
        
        if hours < 1:
            return {
                "is_new": True,
                "restriction_level": "hour_1",
                "hours_since_join": hours,
                "restrictions": self.restriction_levels["hour_1"]
            }
        elif days < 1:
            return {
                "is_new": True,
                "restriction_level": "day_1",
                "hours_since_join": hours,
                "restrictions": self.restriction_levels["day_1"]
            }
        elif days < 7:
            return {
                "is_new": True,
                "restriction_level": "week_1",
                "days_since_join": days,
                "restrictions": self.restriction_levels["week_1"]
            }
        else:
            return {
                "is_new": False,
                "restriction_level": "veteran",
                "days_since_join": days
            }
    
    def should_relax_for_veteran(self, user_id: int) -> bool:
        """تحديد إذا كان العضو يستحق تخفيف القيود"""
        status = self.get_member_status(user_id)
        return status["days_since_join"] >= 30  # شهر أو أكثر

# ================== تهيئة الأنظمة ==================
smart_lists = SmartListsSystem()
link_analyzer = LinkAnalysisSystem()
new_member_protection = NewMemberProtection()

# ================== إعدادات البوت ==================
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
        return '🔇 كتم عند المخالفة الأولى'
    elif mode == 'ban':
        return '🚫 حظر عند المخالفة الأولى'
    elif mode == 'mute_then_ban':
        return '🔇→🚫 كتم الأولى + حظر الثانية'
    return mode

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
            'new_member_protection': True,
            'veteran_relaxation': True,
            'link_control_enabled': True,
            'strict_phone_detection': True,
            'enable_smart_lists': True,
        }

    try:
        dummy = await bot.send_message(DB_CHAT_ID, "📥 تحميل الإعدادات...")
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
                    for key in ['violations', 'night_mode_enabled', 'night_start', 'night_end',
                               'night_announce_msg_id', 'new_member_protection', 'veteran_relaxation',
                               'link_control_enabled', 'strict_phone_detection', 'enable_smart_lists']:
                        settings[group_str].setdefault(key, settings[group_str].get(key, None))
            SETTINGS_MESSAGE_ID = json_msg.message_id
        else:
            await save_settings_to_tg()
    except Exception as e:
        logger.error(f"❌ خطأ تحميل: {e}")
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
        logger.error(f"❌ خطأ حفظ: {e}")
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
                        f"⏰ <b>وقت الإغلاق:</b> {settings[group_str]['night_start']}\n"
                        f"🌅 <b>وقت الفتح:</b> {settings[group_str]['night_end']}\n"
                        f"🚫 <b>الحالة:</b> المشاركات متوقفة مؤقتًا\n\n"
                        "💤 استريحوا وناموا جيدًا! 🛌"
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

# ================== حالات FSM ==================
class ListManagement(StatesGroup):
    waiting_for_item = State()
    waiting_for_value = State()
    waiting_for_keyword = State()
    waiting_for_keyword_category = State()

# ================== لوحات التحكم ==================

def get_smart_lists_main_menu(group_id: int):
    """القائمة الرئيسية لنظام القوائم"""
    system_status = "✅ مفعل" if smart_lists.lists_enabled else "❌ معطل"
    
    text = f"📋 <b>نظام القوائم الذكي</b>\n\n"
    text += f"🎯 <b>حالة النظام:</b> {system_status}\n\n"
    text += "📊 <b>حالة القوائم:</b>\n"
    
    for list_type in ListType:
        status = "✅" if smart_lists.list_status[list_type] else "❌"
        count = sum(len(items) for items in smart_lists.lists[list_type].values() if isinstance(items, set))
        
        list_name = {
            ListType.BLACK: "⚫ القائمة السوداء",
            ListType.WHITE: "⚪ القائمة البيضاء",
            ListType.GRAY: "🔘 القائمة الرمادية",
            ListType.KEYWORDS: "🔤 الكلمات المفتاحية"
        }[list_type]
        
        text += f"{status} {list_name}: {count} عنصر\n"
    
    text += f"\n📈 <b>الإحصائيات:</b>\n"
    text += f"• الحظر اليوم: {smart_lists.stats['blocks_today']}\n"
    text += f"• إجمالي الحظر: {smart_lists.stats['total_blocks']}\n"
    text += f"• آخر تحديث: {smart_lists.stats['last_updated'].strftime('%Y-%m-%d %H:%M')}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{'❌ إيقاف' if smart_lists.lists_enabled else '✅ تفعيل'} النظام",
                callback_data=f"lists_toggle_system_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(text="⚫ القائمة السوداء", callback_data=f"lists_manage_black_{group_id}"),
            InlineKeyboardButton(text="⚪ القائمة البيضاء", callback_data=f"lists_manage_white_{group_id}")
        ],
        [
            InlineKeyboardButton(text="🔘 القائمة الرمادية", callback_data=f"lists_manage_gray_{group_id}"),
            InlineKeyboardButton(text="🔤 الكلمات المفتاحية", callback_data=f"lists_manage_keywords_{group_id}")
        ],
        [
            InlineKeyboardButton(text="📊 الإحصائيات", callback_data=f"lists_stats_{group_id}"),
            InlineKeyboardButton(text="💾 نسخ احتياطي", callback_data=f"lists_backup_{group_id}")
        ],
        [
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")
        ]
    ])
    
    return text, keyboard

def get_list_management_menu(list_type: ListType, group_id: int):
    """قائمة إدارة قائمة محددة"""
    list_name = {
        ListType.BLACK: "⚫ القائمة السوداء",
        ListType.WHITE: "⚪ القائمة البيضاء",
        ListType.GRAY: "🔘 القائمة الرمادية",
        ListType.KEYWORDS: "🔤 الكلمات المفتاحية"
    }[list_type]
    
    list_info = asyncio.run(smart_lists.get_list_info(list_type))
    status = "✅ مفعلة" if list_info["enabled"] else "❌ معطلة"
    
    text = f"<b>إدارة {list_name}</b>\n\n"
    text += f"🎯 <b>الحالة:</b> {status}\n\n"
    
    if list_type == ListType.KEYWORDS:
        text += "📝 <b>فئات الكلمات:</b>\n"
        for item_type, count in list_info["counts"].items():
            category_name = {
                "spam_keywords": "🔞 كلمات سبام",
                "ad_keywords": "📢 كلمات إعلانية",
                "suspicious_keywords": "👁️ كلمات مشبوهة"
            }.get(item_type, item_type)
            text += f"• {category_name}: {count} كلمة\n"
    else:
        text += "📊 <b>عدد العناصر:</b>\n"
        for item_type, count in list_info["counts"].items():
            item_name = {
                "users": "👥 مستخدمين",
                "keywords": "📝 كلمات",
                "urls": "🔗 روابط",
                "phones": "📞 أرقام"
            }.get(item_type, item_type)
            text += f"• {item_name}: {count}\n"
    
    keyboard_buttons = []
    
    if list_type == ListType.KEYWORDS:
        keyboard_buttons.extend([
            [InlineKeyboardButton(text="➕ إضافة كلمة سبام", callback_data=f"lists_add_spam_keyword_{group_id}")],
            [InlineKeyboardButton(text="➕ إضافة كلمة إعلانية", callback_data=f"lists_add_ad_keyword_{group_id}")],
            [InlineKeyboardButton(text="➕ إضافة كلمة مشبوهة", callback_data=f"lists_add_suspicious_keyword_{group_id}")],
            [InlineKeyboardButton(text="👁️ عرض الكل", callback_data=f"lists_view_keywords_{group_id}")],
        ])
    else:
        item_types = {
            ListType.BLACK: ["users", "keywords", "urls", "phones"],
            ListType.WHITE: ["users", "urls"],
            ListType.GRAY: ["users"]
        }[list_type]
        
        for item_type in item_types:
            button_text = {
                "users": "👥 إدارة المستخدمين",
                "keywords": "📝 إدارة الكلمات",
                "urls": "🔗 إدارة الروابط",
                "phones": "📞 إدارة الأرقام"
            }[item_type]
            
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"lists_manage_items_{list_type.value}_{item_type}_{group_id}"
                )
            ])
    
    keyboard_buttons.extend([
        [
            InlineKeyboardButton(
                text=f"{'❌ إيقاف' if list_info['enabled'] else '✅ تفعيل'} القائمة",
                callback_data=f"lists_toggle_{list_type.value}_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"lists_main_{group_id}")
        ]
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    return text, keyboard

def get_items_management_menu(list_type: ListType, item_type: str, group_id: int):
    """قائمة إدارة عناصر محددة"""
    list_name = {
        ListType.BLACK: "القائمة السوداء",
        ListType.WHITE: "القائمة البيضاء",
        ListType.GRAY: "القائمة الرمادية"
    }[list_type]
    
    item_name = {
        "users": "المستخدمين",
        "keywords": "الكلمات",
        "urls": "الروابط",
        "phones": "الأرقام"
    }[item_type]
    
    text = f"<b>إدارة {item_name} في {list_name}</b>\n\n"
    
    items = list(smart_lists.lists[list_type][item_type])
    if items:
        text += f"📋 <b>أحدث 5 عناصر:</b>\n"
        for i, item in enumerate(items[-5:], 1):
            text += f"{i}. {item}\n"
        if len(items) > 5:
            text += f"\n📦 و {len(items) - 5} عناصر أخرى..."
    else:
        text += "📭 لا توجد عناصر في هذه القائمة."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ إضافة", callback_data=f"lists_add_item_{list_type.value}_{item_type}_{group_id}"),
            InlineKeyboardButton(text="🗑️ حذف", callback_data=f"lists_remove_item_{list_type.value}_{item_type}_{group_id}")
        ],
        [
            InlineKeyboardButton(text="👁️ عرض الكل", callback_data=f"lists_view_all_{list_type.value}_{item_type}_{group_id}"),
            InlineKeyboardButton(text="🧹 تنظيف", callback_data=f"lists_clear_all_{list_type.value}_{item_type}_{group_id}")
        ],
        [
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"lists_manage_{list_type.value}_{group_id}")
        ]
    ])
    
    return text, keyboard

def get_new_member_panel(group_id):
    """لوحة حماية الأعضاء الجدد"""
    group_str = str(group_id)
    protection_enabled = settings[group_str].get('new_member_protection', True)
    veteran_enabled = settings[group_str].get('veteran_relaxation', True)
    
    text = "🆕 <b>حماية الأعضاء الجدد</b>\n\n"
    text += f"🛡️ <b>حماية الجدد:</b> {'✅ مفعلة' if protection_enabled else '❌ معطلة'}\n"
    text += f"🌟 <b>تخفيف للقدامى:</b> {'✅ مفعل' if veteran_enabled else '❌ معطل'}\n\n"
    text += "📋 <b>القيود التلقائية:</b>\n"
    text += "⏰ <b>الساعة الأولى:</b> ٣ رسائل فقط، بدون روابط\n"
    text += "📅 <b>اليوم الأول:</b> ١٠ رسائل/ساعة، روابط تواصل اجتماعي فقط\n"
    text += "📆 <b>الأسبوع الأول:</b> ٢٠ رسائل/ساعة، تحذير على المشبوه\n"
    text += "🎖️ <b>بعد شهر:</b> تخفيف كامل للقيود\n\n"
    text += "🎯 <b>الهدف:</b> منع إساءة استخدام الحسابات الجديدة مع إعطاء مرونة للمنتسبين القدامى"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{'❌ إيقاف' if protection_enabled else '✅ تفعيل'} حماية الجدد",
                callback_data=f"newmem_toggle_protection_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'❌ إيقاف' if veteran_enabled else '✅ تفعيل'} تخفيف القدامى",
                callback_data=f"newmem_toggle_veteran_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(text="📊 الإحصائيات", callback_data=f"newmem_stats_{group_id}")
        ],
        [
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")
        ]
    ])
    
    return text, keyboard

def get_link_control_panel(group_id):
    """لوحة التحكم في الروابط"""
    group_str = str(group_id)
    enabled = settings[group_str].get('link_control_enabled', True)
    
    text = "🔗 <b>التحكم في الروابط</b>\n\n"
    text += f"🎯 <b>حالة النظام:</b> {'✅ مفعل' if enabled else '❌ معطل'}\n\n"
    text += "✅ <b>المواقع المسموحة تلقائياً:</b>\n"
    text += "يوتيوب، إنستغرام، تويتر، فيسبوك، تيك توك\n"
    text += "لينكدإن، سناب شات، ريديت، ديسكورد\n\n"
    text += "🚫 <b>المواقع الممنوعة تلقائياً:</b>\n"
    text += "• روابط تيليجرام (مجموعات وقنوات)\n"
    text += "• روابط واتساب ودردشات\n"
    text += "• الروابط المختصرة\n"
    text += "• منصات المراسلة الأخرى\n\n"
    text += "💡 <b>ملاحظة:</b> يمكن تخصيص القوائم من نظام القوائم الذكي"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"{'❌ إيقاف' if enabled else '✅ تفعيل'} النظام",
                callback_data=f"link_toggle_{group_id}"
            )
        ],
        [
            InlineKeyboardButton(text="🔍 اختبار رابط", callback_data=f"link_test_{group_id}")
        ],
        [
            InlineKeyboardButton(text="📊 إحصائيات", callback_data=f"link_stats_{group_id}")
        ],
        [
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")
        ]
    ])
    
    return text, keyboard

def get_main_control_panel(group_id):
    """لوحة التحكم الرئيسية"""
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    current_duration = settings[group_str]['mute_duration']
    duration_value, duration_unit = seconds_to_value_unit(current_duration)
    night_enabled = settings[group_str]['night_mode_enabled']
    night_start = settings[group_str]['night_start']
    night_end = settings[group_str]['night_end']
    
    new_member_enabled = settings[group_str].get('new_member_protection', True)
    veteran_enabled = settings[group_str].get('veteran_relaxation', True)
    link_control_enabled = settings[group_str].get('link_control_enabled', True)
    smart_lists_enabled = settings[group_str].get('enable_smart_lists', True)
    
    text = f"🛡️ <b>لوحة تحكم البوت الذكي</b>\n\n"
    text += f"🎯 <b>وضع الحماية:</b> {mode_to_text(current_mode)}\n"
    text += f"⏱️ <b>مدة الكتم:</b> {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n"
    text += f"🌙 <b>الوضع الليلي:</b> {'✅ مفعل' if night_enabled else '❌ معطل'}\n"
    text += f"📋 <b>القوائم الذكية:</b> {'✅ مفعل' if smart_lists_enabled else '❌ معطل'}\n"
    text += f"🆕 <b>حماية الجدد:</b> {'✅ مفعلة' if new_member_enabled else '❌ معطلة'}\n"
    text += f"🌟 <b>تخفيف القدامى:</b> {'✅ مفعل' if veteran_enabled else '❌ معطل'}\n"
    text += f"🔗 <b>تحكم الروابط:</b> {'✅ مفعل' if link_control_enabled else '❌ معطل'}\n"
    
    if night_enabled:
        text += f"⏰ <b>توقيت الليل:</b> {night_start} → {night_end}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 وضع الحماية", callback_data=f"mode_menu_{group_id}")],
        [InlineKeyboardButton(text="⏱️ مدة الكتم", callback_data=f"dur_{group_id}")],
        [InlineKeyboardButton(text="🌙 الوضع الليلي", callback_data=f"night_menu_{group_id}")],
        [InlineKeyboardButton(text="📋 القوائم الذكية", callback_data=f"lists_main_{group_id}")],
        [InlineKeyboardButton(text="🆕 حماية الجدد", callback_data=f"new_member_{group_id}")],
        [InlineKeyboardButton(text="🔗 تحكم الروابط", callback_data=f"link_control_{group_id}")],
        [InlineKeyboardButton(text="🔄 تحديث اللوحة", callback_data=f"refresh_{group_id}")],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="main_menu")]
    ])
    
    return text, keyboard

def get_mode_menu(group_id):
    """قائمة وضع الحماية"""
    group_str = str(group_id)
    current_mode = settings[group_str]['mode']
    
    text = "🛡️ <b>اختر وضع الحماية:</b>\n\n"
    text += f"🎯 <b>الوضع الحالي:</b> {mode_to_text(current_mode)}\n\n"
    text += "📋 <b>خيارات الحماية:</b>\n"
    text += "• 🔇 <b>كتم أولى:</b> كتم العضو عند المخالفة الأولى\n"
    text += "• 🚫 <b>حظر فوري:</b> حظر العضو عند المخالفة الأولى\n"
    text += "• 🔇→🚫 <b>كتم ثم حظر:</b> كتم أولاً، ثم حظر عند المخالفة الثانية\n\n"
    text += "💡 <b>ملاحظة:</b> نظام متعدد المراحل لحماية فعالة"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'✅ ' if current_mode == 'mute' else ''}🔇 كتم أولى", callback_data=f"mode_mute_{group_id}")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_mode == 'ban' else ''}🚫 حظر فوري", callback_data=f"mode_ban_{group_id}")],
        [InlineKeyboardButton(text=f"{'✅ ' if current_mode == 'mute_then_ban' else ''}🔇→🚫 كتم ثم حظر", callback_data=f"mode_mtb_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

def get_night_menu(group_id):
    """قائمة الوضع الليلي"""
    group_str = str(group_id)
    night_enabled = settings[group_str]['night_mode_enabled']
    night_start = settings[group_str]['night_start']
    night_end = settings[group_str]['night_end']
    
    text = "🌙 <b>إعدادات الوضع الليلي</b>\n\n"
    text += f"💡 <b>الحالة:</b> {'✅ <b>مفعل</b>' if night_enabled else '❌ <b>معطل</b>'}\n"
    text += f"🌜 <b>وقت الإغلاق:</b> {night_start}\n"
    text += f"🌅 <b>وقت الفتح:</b> {night_end}\n\n"
    text += "🛌 <b>مميزات الوضع الليلي:</b>\n"
    text += "• إغلاق المجموعة تلقائياً في وقت محدد\n"
    text += "• رسالة إعلان أنيقة عند التفعيل\n"
    text += "• حذف المشاركات من غير المشرفين\n"
    text += "• استثناء المشرفين فقط من القيود"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'❌ إيقاف' if night_enabled else '✅ تشغيل'} الوضع الليلي", callback_data=f"night_toggle_{group_id}")],
        [InlineKeyboardButton(text="⏰ تعديل التوقيت", callback_data=f"night_time_{group_id}")],
        [InlineKeyboardButton(text="📊 إحصائيات", callback_data=f"night_stats_{group_id}")],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}")]
    ])
    
    return text, keyboard

# ================== Handlers ==================

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
        intro_text = "🛡️ <b>مرحباً بك في لوحة تحكم بوت الحارس الأمني!</b>\n\n"
        intro_text += "🔒 <i>أقوى نظام حماية متكامل لمجموعات تيليجرام</i>\n\n"
        intro_text += "📋 <b>اختر المجموعة التي تريد إدارتها:</b>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for gid, title in admin_groups:
            keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"⚙️ إدارة {title}", callback_data=f"manage_{gid}")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="❓ مساعدة أو استفسار", url="https://t.me/ql_om")])
        
        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        intro_text = (
            "🛡️ <b>مرحباً بك في بوت الحارس الأمني الذكي!</b>\n\n"
            "🔒 <i>نظام حماية متقدم لمجموعات تيليجرام</i>\n\n"
            "🎯 <b>المميزات الرئيسية:</b>\n"
            "• كشف ذكي متطور للأرقام والروابط\n"
            "• نظام قوائم ذكي قابل للتخصيص\n"
            "• حماية ذكية للأعضاء الجدد\n"
            "• وضع ليلي مع رسائل إعلانية\n"
            "• لوحة تحكم متكاملة وسهلة\n\n"
            "📌 <b>البوت يعمل فقط في المجموعات المسجلة.</b>\n\n"
            "📞 للتواصل أو التسجيل:\n"
            "👉 @ql_om"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="🌟 معلومات إضافية", callback_data="more_info")]
        ])
        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)

@dp.callback_query()
async def handle_callback_query(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    await callback.answer()

    if data == "main_menu":
        await start_command(callback.message)
        return
        
    if data == "more_info":
        more_info_text = (
            "🛡️ <b>الحارس الأمني المتقدم</b>\n\n"
            "🚀 <b>المميزات الرئيسية:</b>\n"
            "• 🔍 <b>كشف ذكي متطور</b> للأرقام (عربي/فارسي/لاتيني)\n"
            "• 🔗 <b>تحليل روابط متقدم</b> مع فلترة ذكية\n"
            "• 📋 <b>نظام قوائم ذكي</b> قابل للتخصيص الكامل\n"
            "• 🆕 <b>حماية الأعضاء الجدد</b> بقيود ذكية\n"
            "• 🌟 <b>تخفيف للأعضاء القدامى</b> بناءً على السمعة\n"
            "• 🌙 <b>الوضع الليلي</b> مع إعلانات أنيقة\n"
            "• ⚙️ <b>إعدادات متقدمة</b> قابلة للتخصيص\n\n"
            "🎯 <b>نظام الحماية المتعدد الطبقات:</b>\n"
            "1. 🟢 فحص أولي سريع\n"
            "2. 🟡 تحليل محتوى متقدم\n"
            "3. 🔴 كشف سبام ذكي\n"
            "4. 🛡️ تطبيق إجراءات وقائية\n\n"
            "📊 <b>مميزات خاصة:</b>\n"
            "• لا توجد كلمات مفتاحية ثابتة (كل مجموعة تخصص قوائمها)\n"
            "• نظام مرن يناسب جميع أنواع المجموعات\n"
            "• حماية فعالة دون تعطيل نشاط المجموعة\n\n"
            "🏆 <b>بوت سريع، دقيق، ومستمر في التحديث</b>\n\n"
            "📞 للتواصل أو التسجيل:\n"
            "👉 @ql_om"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="main_menu")]
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

    if data.startswith("lists_main_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_smart_lists_main_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("lists_toggle_system_"):
        group_id = int(data.split("_")[3])
        new_status = await smart_lists.toggle_system()
        group_str = str(group_id)
        settings[group_str]['enable_smart_lists'] = new_status
        await save_settings_to_tg()
        
        status_text = "✅ تم تفعيل نظام القوائم" if new_status else "❌ تم إيقاف نظام القوائم"
        await callback.answer(status_text)
        
        text, keyboard = get_smart_lists_main_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("lists_manage_"):
        parts = data.split("_")
        list_type_str = parts[2]
        group_id = int(parts[3])
        
        try:
            list_type = ListType(list_type_str)
            text, keyboard = get_list_management_menu(list_type, group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        except:
            await callback.answer("❌ خطأ في تحميل القائمة")
        return

    if data.startswith("lists_toggle_"):
        parts = data.split("_")
        list_type_str = parts[2]
        group_id = int(parts[3])
        
        try:
            list_type = ListType(list_type_str)
            new_status = await smart_lists.toggle_list(list_type)
            
            list_name = {
                "black": "القائمة السوداء",
                "white": "القائمة البيضاء",
                "gray": "القائمة الرمادية",
                "keywords": "الكلمات المفتاحية"
            }[list_type_str]
            
            status_text = f"✅ تم تفعيل {list_name}" if new_status else f"❌ تم إيقاف {list_name}"
            await callback.answer(status_text)
            
            text, keyboard = get_list_management_menu(list_type, group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        except:
            await callback.answer("❌ خطأ في تغيير الحالة")
        return

    if data.startswith("lists_manage_items_"):
        parts = data.split("_")
        list_type_str = parts[3]
        item_type = parts[4]
        group_id = int(parts[5])
        
        try:
            list_type = ListType(list_type_str)
            text, keyboard = get_items_management_menu(list_type, item_type, group_id)
            await callback.message.edit_text(text, reply_markup=keyboard)
        except:
            await callback.answer("❌ خطأ في تحميل القائمة")
        return

    if data.startswith("lists_add_item_"):
        parts = data.split("_")
        list_type_str = parts[3]
        item_type = parts[4]
        group_id = int(parts[5])
        
        try:
            list_type = ListType(list_type_str)
            await state.update_data(
                list_type=list_type_str,
                item_type=item_type,
                group_id=group_id,
                action="add"
            )
            
            item_name = {
                "users": "معرف المستخدم (رقم)",
                "keywords": "الكلمة الممنوعة",
                "urls": "الرابط الممنوع (بدون https://)",
                "phones": "رقم الهاتف"
            }[item_type]
            
            await callback.message.answer(f"📝 <b>إضافة عنصر جديد</b>\n\n"
                                        f"🔤 <b>نوع العنصر:</b> {item_name}\n"
                                        f"📋 <b>القائمة:</b> {list_type_str}\n\n"
                                        f"📥 <b>الرجاء إرسال {item_name}:</b>")
            await state.set_state(ListManagement.waiting_for_value)
        except:
            await callback.answer("❌ خطأ في بدء الإضافة")
        return

    if data.startswith("new_member_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_new_member_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("newmem_toggle_protection_"):
        group_id = int(data.split("_")[3])
        group_str = str(group_id)
        current = settings[group_str].get('new_member_protection', True)
        settings[group_str]['new_member_protection'] = not current
        await save_settings_to_tg()
        
        status = "✅ تم تفعيل" if not current else "❌ تم إيقاف"
        await callback.answer(f"{status} حماية الأعضاء الجدد")
        
        text, keyboard = get_new_member_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("newmem_toggle_veteran_"):
        group_id = int(data.split("_")[3])
        group_str = str(group_id)
        current = settings[group_str].get('veteran_relaxation', True)
        settings[group_str]['veteran_relaxation'] = not current
        await save_settings_to_tg()
        
        status = "✅ تم تفعيل" if not current else "❌ تم إيقاف"
        await callback.answer(f"{status} تخفيف القدامى")
        
        text, keyboard = get_new_member_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("link_control_"):
        group_id = int(data.split("_")[2])
        text, keyboard = get_link_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    if data.startswith("link_toggle_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        current = settings[group_str].get('link_control_enabled', True)
        settings[group_str]['link_control_enabled'] = not current
        await save_settings_to_tg()
        
        status = "✅ تم تفعيل" if not current else "❌ تم إيقاف"
        await callback.answer(f"{status} تحكم الروابط")
        
        text, keyboard = get_link_control_panel(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    # تغيير وضع الحماية
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
        
        text, keyboard = get_mode_menu(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    # مدة الكتم
    if data.startswith("dur_"):
        parts = data.split("_")
        action = parts[1]
        
        if len(parts) == 2:
            group_id = int(parts[1])
            group_str = str(group_id)
            current = settings[group_str]['mute_duration']
            value, unit = seconds_to_value_unit(current)
            temp_duration[group_id] = {'value': max(1, value), 'unit': unit}
            
            unit_text = unit_to_text_dict.get(unit, unit)
            text = f"⏱️ <b>تحرير مدة الكتم</b>\n\n"
            text += f"🎯 <b>القيمة الحالية:</b> {value} {unit_text}\n\n"
            text += "📱 <b>استخدم الأزرار للتعديل:</b>"
            
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

        value = temp_duration[group_id]['value']
        unit = temp_duration[group_id]['unit']
        unit_text = unit_to_text_dict.get(unit, unit)
        
        text = f"⏱️ <b>تحرير مدة الكتم</b>\n\n"
        text += f"🎯 <b>القيمة الحالية:</b> {value} {unit_text}\n\n"
        text += "📱 <b>استخدم الأزرار للتعديل:</b>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="-10", callback_data=f"dur_minus10_{group_id}"),
                InlineKeyboardButton(text="-1", callback_data=f"dur_minus1_{group_id}"),
                InlineKeyboardButton(text=f"{value}", callback_data="ignore"),
                InlineKeyboardButton(text="+1", callback_data=f"dur_plus1_{group_id}"),
                InlineKeyboardButton(text="+10", callback_data=f"dur_plus10_{group_id}")
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
            group_id = int(parts[2])
            group_str = str(group_id)
            temp_night[group_id] = {'start': settings[group_str]['night_start'], 'end': settings[group_str]['night_end']}
            
            start = temp_night[group_id]['start']
            end = temp_night[group_id]['end']
            
            text = f"🌙 <b>تحرير توقيت الوضع الليلي</b>\n\n"
            text += f"🌜 <b>وقت الإغلاق:</b> {start}\n"
            text += f"🌅 <b>وقت الفتح:</b> {end}\n\n"
            text += "⏰ <b>اختر الوقت المناسب:</b>"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="🌜 وقت الإغلاق:", callback_data="ignore")
            ])
            
            hour_buttons = []
            for h in [20, 21, 22, 23, 0, 1, 2, 3]:
                hour_str = f"{h:02d}"
                hour_buttons.append(InlineKeyboardButton(
                    text=f"{hour_str}:00", 
                    callback_data=f"night_start_{hour_str}:00_{group_id}"
                ))
            
            for i in range(0, len(hour_buttons), 4):
                keyboard.inline_keyboard.append(hour_buttons[i:i+4])
            
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="↔️ تعديل الدقائق", callback_data="ignore")
            ])
            
            start_hour, start_minute = map(int, start.split(':'))
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="◀️ -30 دقيقة", callback_data=f"night_start_min30_{group_id}"),
                InlineKeyboardButton(text="-15 دقيقة", callback_data=f"night_start_min15_{group_id}"),
                InlineKeyboardButton(text=f"{start_minute:02d}", callback_data="ignore"),
                InlineKeyboardButton(text="+15 دقيقة", callback_data=f"night_start_plus15_{group_id}"),
                InlineKeyboardButton(text="+30 دقيقة ▶️", callback_data=f"night_start_plus30_{group_id}")
            ])
            
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="🌅 وقت الفتح:", callback_data="ignore")
            ])
            
            hour_buttons_end = []
            for h in [4, 5, 6, 7, 8, 9, 10, 11]:
                hour_str = f"{h:02d}"
                hour_buttons_end.append(InlineKeyboardButton(
                    text=f"{hour_str}:00", 
                    callback_data=f"night_end_{hour_str}:00_{group_id}"
                ))
            
            for i in range(0, len(hour_buttons_end), 4):
                keyboard.inline_keyboard.append(hour_buttons_end[i:i+4])
            
            end_hour, end_minute = map(int, end.split(':'))
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="◀️ -30 دقيقة", callback_data=f"night_end_min30_{group_id}"),
                InlineKeyboardButton(text="-15 دقيقة", callback_data=f"night_end_min15_{group_id}"),
                InlineKeyboardButton(text=f"{end_minute:02d}", callback_data="ignore"),
                InlineKeyboardButton(text="+15 دقيقة", callback_data=f"night_end_plus15_{group_id}"),
                InlineKeyboardButton(text="+30 دقيقة ▶️", callback_data=f"night_end_plus30_{group_id}")
            ])
            
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="💾 حفظ", callback_data=f"night_save_{group_id}"),
                InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}"),
                InlineKeyboardButton(text="❌ إلغاء", callback_data=f"night_cancel_{group_id}")
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard)
            return

    if data.startswith("night_start_") or data.startswith("night_end_"):
        parts = data.split("_")
        action = parts[1]
        
        if parts[2] in ["min30", "min15", "plus15", "plus30"]:
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
            time_val = parts[2]
            group_id = int(parts[3])
            temp_night[group_id][action] = time_val
            
        start = temp_night[group_id]['start']
        end = temp_night[group_id]['end']
        
        text = f"🌙 <b>تحرير توقيت الوضع الليلي</b>\n\n"
        text += f"🌜 <b>وقت الإغلاق:</b> {start}\n"
        text += f"🌅 <b>وقت الفتح:</b> {end}\n\n"
        text += "⏰ <b>اختر الوقت المناسب:</b>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🌜 وقت الإغلاق:", callback_data="ignore")
        ])
        
        hour_buttons = []
        for h in [20, 21, 22, 23, 0, 1, 2, 3]:
            hour_str = f"{h:02d}"
            hour_buttons.append(InlineKeyboardButton(
                text=f"{hour_str}:00", 
                callback_data=f"night_start_{hour_str}:00_{group_id}"
            ))
        
        for i in range(0, len(hour_buttons), 4):
            keyboard.inline_keyboard.append(hour_buttons[i:i+4])
        
        start_hour, start_minute = map(int, start.split(':'))
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="◀️ -30 دقيقة", callback_data=f"night_start_min30_{group_id}"),
            InlineKeyboardButton(text="-15 دقيقة", callback_data=f"night_start_min15_{group_id}"),
            InlineKeyboardButton(text=f"{start_minute:02d}", callback_data="ignore"),
            InlineKeyboardButton(text="+15 دقيقة", callback_data=f"night_start_plus15_{group_id}"),
            InlineKeyboardButton(text="+30 دقيقة ▶️", callback_data=f"night_start_plus30_{group_id}")
        ])
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🌅 وقت الفتح:", callback_data="ignore")
        ])
        
        hour_buttons_end = []
        for h in [4, 5, 6, 7, 8, 9, 10, 11]:
            hour_str = f"{h:02d}"
            hour_buttons_end.append(InlineKeyboardButton(
                text=f"{hour_str}:00", 
                callback_data=f"night_end_{hour_str}:00_{group_id}"
            ))
        
        for i in range(0, len(hour_buttons_end), 4):
            keyboard.inline_keyboard.append(hour_buttons_end[i:i+4])
        
        end_hour, end_minute = map(int, end.split(':'))
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="◀️ -30 دقيقة", callback_data=f"night_end_min30_{group_id}"),
            InlineKeyboardButton(text="-15 دقيقة", callback_data=f"night_end_min15_{group_id}"),
            InlineKeyboardButton(text=f"{end_minute:02d}", callback_data="ignore"),
            InlineKeyboardButton(text="+15 دقيقة", callback_data=f"night_end_plus15_{group_id}"),
            InlineKeyboardButton(text="+30 دقيقة ▶️", callback_data=f"night_end_plus30_{group_id}")
        ])
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="💾 حفظ", callback_data=f"night_save_{group_id}"),
            InlineKeyboardButton(text="↩️ رجوع", callback_data=f"back_{group_id}"),
            InlineKeyboardButton(text="❌ إلغاء", callback_data=f"night_cancel_{group_id}")
        ])
        
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

# ================== معالجة إدخال المستخدم ==================

@dp.message(ListManagement.waiting_for_value)
async def handle_item_value(message: types.Message, state: FSMContext):
    """معالجة القيمة المدخلة"""
    data = await state.get_data()
    list_type_str = data.get("list_type")
    item_type = data.get("item_type")
    group_id = data.get("group_id")
    action = data.get("action", "add")
    
    value = message.text.strip()
    
    try:
        list_type = ListType(list_type_str)
        
        if action == "add":
            success = await smart_lists.add_to_list(list_type, item_type, value)
            if success:
                await message.answer(f"✅ <b>تمت الإضافة بنجاح</b>\n\n"
                                   f"📝 <b>العنصر:</b> {value}\n"
                                   f"📋 <b>إلى:</b> {list_type_str}")
                
                # العودة إلى قائمة الإدارة
                if list_type == ListType.KEYWORDS:
                    text, keyboard = get_list_management_menu(list_type, group_id)
                else:
                    text, keyboard = get_items_management_menu(list_type, item_type, group_id)
                await message.answer(text, reply_markup=keyboard)
            else:
                await message.answer("❌ <b>فشل في الإضافة</b>\n\n"
                                   "⚠️ الرجاء التحقق من نوع العنصر والمحاولة مرة أخرى.")
    
    except Exception as e:
        logger.error(f"خطأ في إضافة العنصر: {e}")
        await message.answer("❌ <b>حدث خطأ</b>\n\n"
                           "⚠️ تعذر إضافة العنصر. الرجاء المحاولة مرة أخرى.")
    
    await state.clear()

# ================== معالجة الرسائل ==================

@dp.message()
async def check_message(message: types.Message):
    if message.chat.type == 'private':
        await message.answer(
            "🛡️ <b>مرحباً بك في بوت الحارس الأمني الذكي!</b>\n\n"
            "🔒 <i>نظام حماية متكامل لمجموعات تيليجرام</i>\n\n"
            "📞 للتواصل أو التسجيل:\n"
            "👉 @ql_om",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📞 تواصل معنا", url="https://t.me/ql_om")]
            ])
        )
        return

    chat_id = message.chat.id
    if chat_id not in ALLOWED_GROUP_IDS:
        return

    user_id = message.from_user.id
    group_str = str(chat_id)

    # تتبع انضمام الأعضاء الجدد
    await new_member_protection.track_member_join(user_id)

    # === الوضع الليلي ===
    if group_str in settings and settings[group_str]['night_mode_enabled']:
        start = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
        end = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
        now = datetime.now().time()
        is_night = (start <= now < end) if start < end else (start <= now or now < end)
        
        if is_night and not await is_admin(chat_id, user_id):
            try:
                night_msg = await message.reply(
                    "🌙 <b>الوضع الليلي مفعل حالياً</b>\n\n"
                    f"⏰ <b>وقت الإغلاق:</b> {settings[group_str]['night_start']}\n"
                    f"🌅 <b>وقت الفتح:</b> {settings[group_str]['night_end']}\n"
                    f"🚫 <b>الحالة:</b> المشاركات متوقفة مؤقتاً\n\n"
                    "💤 استريحوا وناموا جيداً!\n"
                    "🛡️ <i>مجموعة محمية</i>"
                )
                asyncio.create_task(delete_after_delay(night_msg, 10))
            except:
                pass
            await message.delete()
            return

    # === استثناء المشرفين ===
    if await is_admin(chat_id, user_id):
        return

    text_content = (message.text or message.caption or "").strip()
    
    # === 1. فحص نظام القوائم الذكية ===
    if settings[group_str].get('enable_smart_lists', True):
        list_check = await smart_lists.check_message(text_content, user_id)
        
        if list_check["blocked"]:
            await message.delete()
            
            action_emoji = {
                "ban": "🚫",
                "mute": "🔇",
                "warn": "⚠️",
                "delete": "🗑️"
            }.get(list_check["action"], "❌")
            
            notify_text = f"{action_emoji} <b>تم حظر الرسالة</b>\n\n"
            notify_text += f"👤 <b>العضو:</b> {message.from_user.full_name}\n"
            notify_text += f"📝 <b>السبب:</b> {list_check['reason']}\n"
            
            if list_check["matches"]:
                notify_text += f"🎯 <b>التطابقات:</b> {', '.join(list_check['matches'][:3])}\n"
            
            notify_text += f"📋 <b>النظام:</b> القوائم الذكية\n\n"
            notify_text += "🛡️ <i>مجموعة محمية</i>"
            
            notification = await message.answer(notify_text)
            asyncio.create_task(delete_after_delay(notification, 20))
            return

    # === 2. فحص حماية الأعضاء الجدد ===
    if settings[group_str].get('new_member_protection', True):
        member_status = new_member_protection.get_member_status(user_id)
        
        if member_status["is_new"]:
            restrictions = member_status.get("restrictions", {})
            
            # التحقق من الروابط للأعضاء الجدد
            if not restrictions.get("allow_external_links", True):
                url_check = link_analyzer.check_text_urls(text_content)
                if url_check["total_urls"] > 0 and not all(r["is_allowed_social"] for r in url_check["results"]):
                    await message.delete()
                    
                    warning = await message.answer(
                        "🆕 <b>تنبيه للأعضاء الجدد</b>\n\n"
                        f"👤 <b>العضو:</b> {message.from_user.full_name}\n"
                        f"⏳ <b>مدة العضوية:</b> {member_status.get('hours_since_join', 0):.1f} ساعة\n\n"
                        f"🚫 <b>السبب:</b> الروابط الخارجية غير مسموحة للأعضاء الجدد\n"
                        f"💡 <b>ملاحظة:</b> يمكنك مشاركة الروابط بعد {7 - member_status.get('days_since_join', 0)} أيام\n\n"
                        "🛡️ <i>حماية نشطة للأعضاء الجدد</i>"
                    )
                    asyncio.create_task(delete_after_delay(warning, 20))
                    return

    # === 3. فحص الروابط (إذا كان النظام مفعل) ===
    if settings[group_str].get('link_control_enabled', True):
        url_check = link_analyzer.check_text_urls(text_content)
        
        if url_check["has_high_risk"]:
            await message.delete()
            
            high_risk_urls = [r for r in url_check["results"] if r["risk_level"] == "high"]
            
            notify_text = "🚫 <b>تم حظر الرسالة</b>\n\n"
            notify_text += f"👤 <b>العضو:</b> {message.from_user.full_name}\n"
            notify_text += f"🔗 <b>سبب الحظر:</b> {high_risk_urls[0]['reason']}\n"
            notify_text += f"🌐 <b>نوع الرابط:</b> "
            
            if high_risk_urls[0]["is_telegram_invite"]:
                notify_text += "دعوة تيليجرام"
            elif high_risk_urls[0]["is_telegram_group"]:
                notify_text += "مجموعة تيليجرام"
            elif high_risk_urls[0]["is_whatsapp"]:
                notify_text += "رابط واتساب"
            elif high_risk_urls[0]["is_short_link"]:
                notify_text += "رابط مختصر"
            else:
                notify_text += "رابط مشبوه"
            
            notify_text += "\n\n🛡️ <i>مجموعة محمية ضد الروابط الضارة</i>"
            
            notification = await message.answer(notify_text)
            asyncio.create_task(delete_after_delay(notification, 20))
            return

    # === 4. فحص الأرقام الهاتفية ===
    phones = extract_phone_numbers(text_content)
    has_phone_context = contains_phone_context(text_content)
    
    # التخفيف للأعضاء القدامى
    should_relax = new_member_protection.should_relax_for_veteran(user_id)
    if settings[group_str].get('veteran_relaxation', True) and should_relax:
        # تخفيف القيود للأعضاء القدامى
        pass
    else:
        # تطبيق القيود العادية
        if phones and has_phone_context:
            await message.delete()
            
            notify_text = "📞 <b>تم حظر الرسالة</b>\n\n"
            notify_text += f"👤 <b>العضو:</b> {message.from_user.full_name}\n"
            notify_text += f"📝 <b>السبب:</b> مشاركة أرقام هاتفية\n"
            notify_text += f"🔢 <b>الأرقام المكتشفة:</b> {', '.join(phones[:3])}\n\n"
            notify_text += "🛡️ <i>مجموعة محمية ضد مشاركة المعلومات الشخصية</i>"
            
            notification = await message.answer(notify_text)
            asyncio.create_task(delete_after_delay(notification, 20))
            
            # تطبيق العقوبة حسب الإعدادات
            mode = settings[group_str]['mode']
            mute_duration = settings[group_str]['mute_duration']
            full_name = message.from_user.full_name
            
            if mode == 'ban':
                if not await is_banned(chat_id, user_id):
                    await bot.ban_chat_member(chat_id, user_id)
                    ban_notify = (
                        f"🚫 <b>تم حظر العضو نهائياً</b>\n\n"
                        f"👤 <b>العضو:</b> <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                        f"📝 <b>السبب:</b> مشاركة أرقام هاتفية\n"
                        f"🔢 <b>الأرقام:</b> {phones[0]}...\n\n"
                        f"🛡️ <i>مجموعة محمية</i>"
                    )
                    msg = await bot.send_message(chat_id, ban_notify)
                    asyncio.create_task(delete_after_delay(msg, 30))

            elif mode == 'mute':
                until_date = int(time.time()) + mute_duration if mute_duration > 30 else 0
                await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
                duration_value, duration_unit = seconds_to_value_unit(mute_duration)
                duration_text = f"{duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}"
                
                mute_notify = (
                    f"🔇 <b>تم كتم العضو</b>\n\n"
                    f"👤 <b>العضو:</b> <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                    f"⏱️ <b>المدة:</b> {duration_text}\n"
                    f"📝 <b>السبب:</b> مشاركة أرقام هاتفية\n\n"
                    f"🛡️ <i>مجموعة محمية</i>"
                )
                msg = await bot.send_message(chat_id, mute_notify)
                asyncio.create_task(delete_after_delay(msg, 30))

            elif mode == 'mute_then_ban':
                if 'violations' not in settings[group_str]:
                    settings[group_str]['violations'] = {}

                violations_count = settings[group_str]['violations'].get(user_id, 0) + 1
                settings[group_str]['violations'][user_id] = violations_count
                await save_settings_to_tg()

                if violations_count == 1:
                    until_date = int(time.time()) + mute_duration if mute_duration > 30 else 0
                    await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
                    duration_value, duration_unit = seconds_to_value_unit(mute_duration)
                    duration_text = f"{duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}"
                    
                    mute_notify = (
                        f"⚠️ <b>مخالفة أولى - تم الكتم</b>\n\n"
                        f"👤 <b>العضو:</b> <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                        f"⏱️ <b>المدة:</b> {duration_text}\n"
                        f"📝 <b>السبب:</b> مشاركة أرقام هاتفية\n"
                        f"🔢 <b>المخالفة:</b> {violations_count}/2\n\n"
                        f"💡 <b>تنبيه:</b> المخالفة الثانية ستسبب حظراً نهائياً\n"
                        f"🛡️ <i>نظام الحماية متعدد المراحل</i>"
                    )
                    msg = await bot.send_message(chat_id, mute_notify)
                    asyncio.create_task(delete_after_delay(msg, 30))
                else:
                    if not await is_banned(chat_id, user_id):
                        await bot.ban_chat_member(chat_id, user_id)
                        ban_notify = (
                            f"🚫 <b>مخالفة ثانية - تم الحظر</b>\n\n"
                            f"👤 <b>العضو:</b> <a href='tg://user?id={user_id}'>{full_name}</a>\n"
                            f"📝 <b>السبب:</b> مشاركة أرقام هاتفية (مخالفة متكررة)\n"
                            f"🔢 <b>المخالفات:</b> {violations_count}\n\n"
                            f"🛡️ <i>تم تطبيق النظام الوقائي</i>"
                        )
                        msg = await bot.send_message(chat_id, ban_notify)
                        asyncio.create_task(delete_after_delay(msg, 30))
            
            return

async def delete_after_delay(message: types.Message, delay: int = 30):
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
        logger.info(f"✅ Webhook تم تفعيله: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ فشل الـ webhook: {e}")

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
        logger.error(f"❌ خطأ تحديث: {e}")
    return Response(content="OK", status_code=200)

@app.get("/")
async def root():
    return {"status": "✅ البوت يعمل بنجاح! 🟢"}