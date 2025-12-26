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

GROUP_USERNAME = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# قاعدة البيانات في قناة تيليجرام
DB_CHAT_ID = -1002370282238
SETTINGS_MESSAGE_ID = None  # سيتم تحديده تلقائيًا

# تحويل الأرقام العربية إلى لاتينية
def normalize_digits(text: str) -> str:
    trans = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣४۵۶۷۸۹',
        '012345678901234567890123456789'
    )
    return text.translate(trans)

# أنماط كشف السبام
PHONE_PATTERN = re.compile(
    r'(?:\+?966|00966|966|05|5|0)?'
    r'(\d[\s\W_*/.-]*){8,12}',
    re.IGNORECASE
)

PHONE_CONTEXT_PATTERN = re.compile(
    r'(?:اتصل|رقمي|واتس|هاتف|موبايل|mobile|phone|call|contact|whatsapp|واتساب|📞|☎️)[\s\W_*/]{0,10}'
    r'(?:\+\d{1,4}[\s\W_*/.-]*\d{5,15}|\d{9,15})',
    re.IGNORECASE | re.UNICODE
)

WHATSAPP_INVITE_PATTERN = re.compile(r'(?:https?://)?(?:chat\.whatsapp\.com|wa\.me)/[^\s]*|\+\w{8,}', re.IGNORECASE)
TELEGRAM_INVITE_PATTERN = re.compile(
    r'(?:https?://)?t\.me/(?:joinchat/|[+])[\w-]{10,}|(?:https?://)?t\.me/(?!' + (GROUP_USERNAME or '') + r')[^\s/]+',
    re.IGNORECASE
)
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

    if (WHATSAPP_INVITE_PATTERN.search(text) or
        TELEGRAM_INVITE_PATTERN.search(text) or
        TIKTOK_PATTERN.search(text) or
        SHORT_LINK_PATTERN.search(text)):
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
settings = {}  # {group_id_str: {'mode': ..., 'mute_duration': ..., 'violations': {user_id: count}, 'night_mode_enabled': bool, 'night_start': 'HH:MM', 'night_end': 'HH:MM', 'night_announce_msg_id': int or None}}
temp_duration = {}  # مؤقت لتحرير المدة
temp_night = {}  # مؤقت لتحرير الوضع الليلي {group_id: {'start': 'HH:MM', 'end': 'HH:MM'}}

unit_seconds = {
    'minute': 60,
    'hour': 3600,
    'day': 86400,
    'month': 2592000,
    'year': 31536000
}

unit_to_text_dict = {'minute': 'دقيقة', 'hour': 'ساعة', 'day': 'يوم', 'month': 'شهر', 'year': 'سنة'}

def seconds_to_value_unit(seconds: int):
    if seconds == 0:
        return 0, 'minute'
    for unit, secs in sorted(unit_seconds.items(), key=lambda x: x[1], reverse=True):
        if seconds >= secs:
            value = seconds // secs
            return value, unit
    return seconds // 60, 'minute'

# ================== وظائف قاعدة البيانات في تيليجرام ==================
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
        dummy_msg = await bot.send_message(DB_CHAT_ID, "🔄 جاري تحميل إعدادات البوت...")
        history = []
        offset_id = 0
        while len(history) < 50:
            msgs = await bot.get_chat_history(DB_CHAT_ID, limit=100, offset_id=offset_id)
            if not msgs:
                break
            history.extend(msgs)
            if len(msgs) < 100:
                break
            offset_id = msgs[-1].message_id + 1

        json_msg = None
        for msg in reversed(history):
            if msg.text and msg.text.strip().startswith('{') and msg.text.strip().endswith('}'):
                try:
                    loaded = json.loads(msg.text)
                    if isinstance(loaded, dict):
                        json_msg = msg
                        break
                except json.JSONDecodeError:
                    continue

        if json_msg:
            loaded = json.loads(json_msg.text)
            for group_str in settings:
                if group_str in loaded:
                    settings[group_str].update(loaded[group_str])
                    if 'violations' not in settings[group_str]:
                        settings[group_str]['violations'] = {}
                    if 'night_mode_enabled' not in settings[group_str]:
                        settings[group_str]['night_mode_enabled'] = False
                    if 'night_start' not in settings[group_str]:
                        settings[group_str]['night_start'] = '22:00'
                    if 'night_end' not in settings[group_str]:
                        settings[group_str]['night_end'] = '06:00'
                    if 'night_announce_msg_id' not in settings[group_str]:
                        settings[group_str]['night_announce_msg_id'] = None
            SETTINGS_MESSAGE_ID = json_msg.message_id
            logger.info(f"تم تحميل الإعدادات من الرسالة ID: {SETTINGS_MESSAGE_ID}")
        else:
            logger.info("لم يتم العثور على إعدادات سابقة → إنشاء جديدة")
            await save_settings_to_tg()

        await bot.delete_message(DB_CHAT_ID, dummy_msg.message_id)

    except Exception as e:
        logger.error(f"خطأ في تحميل الإعدادات: {e}")
        await save_settings_to_tg()

async def save_settings_to_tg():
    global SETTINGS_MESSAGE_ID
    text = json.dumps(settings, ensure_ascii=False, indent=2)
    try:
        if SETTINGS_MESSAGE_ID is not None:
            await bot.edit_message_text(chat_id=DB_CHAT_ID, message_id=SETTINGS_MESSAGE_ID, text=text)
            logger.info(f"تم تعديل الإعدادات في الرسالة ID: {SETTINGS_MESSAGE_ID}")
        else:
            msg = await bot.send_message(chat_id=DB_CHAT_ID, text=text)
            SETTINGS_MESSAGE_ID = msg.message_id
            logger.info(f"تم إنشاء رسالة إعدادات جديدة ID: {SETTINGS_MESSAGE_ID}")
    except Exception as e:
        logger.error(f"خطأ في حفظ الإعدادات: {e}")
        try:
            msg = await bot.send_message(chat_id=DB_CHAT_ID, text=text)
            SETTINGS_MESSAGE_ID = msg.message_id
            logger.info(f"تم إنشاء رسالة احتياطية جديدة ID: {SETTINGS_MESSAGE_ID}")
        except Exception as e2:
            logger.critical(f"فشل نهائي في الحفظ: {e2}")

# ================== دالة للتحقق من الوضع الليلي دوريًا ==================
async def night_mode_checker():
    while True:
        now = datetime.now().time()
        for gid in ALLOWED_GROUP_IDS:
            group_str = str(gid)
            if group_str in settings and settings[group_str]['night_mode_enabled']:
                start_time = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
                end_time = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()

                # التحقق إذا الوقت الحالي داخل الفترة الليلية (مع مراعاة إذا الفترة عابرة لمنتصف الليل)
                is_night = False
                if start_time < end_time:
                    is_night = start_time <= now < end_time
                else:
                    is_night = start_time <= now or now < end_time

                if is_night and settings[group_str]['night_announce_msg_id'] is None:
                    # إغلاق: أرسل رسالة إعلان
                    announce_text = f"🌙 <b>تم تفعيل الوضع الليلي</b>\n\n🚫 المشاركات متوقفة مؤقتًا حتى الساعة {settings[group_str]['night_end']}.\n🛡️ استريحوا جيدًا!"
                    msg = await bot.send_message(gid, announce_text)
                    settings[group_str]['night_announce_msg_id'] = msg.message_id
                    await save_settings_to_tg()
                elif not is_night and settings[group_str]['night_announce_msg_id'] is not None:
                    # فتح: احذف الرسالة
                    try:
                        await bot.delete_message(gid, settings[group_str]['night_announce_msg_id'])
                    except Exception:
                        pass
                    settings[group_str]['night_announce_msg_id'] = None
                    await save_settings_to_tg()

        await asyncio.sleep(60)  # تحقق كل دقيقة

# ================== handler /start ==================
@dp.message(Command(commands=["start"]))
async def start_command(message: types.Message):
    logger.info(f"تم استلام /start من {message.from_user.id}")

    user_id = message.from_user.id
    if message.chat.type != 'private':
        return

    # تحقق إذا كان أدمن في أي مجموعة مسموحة
    admin_groups = []
    for gid in ALLOWED_GROUP_IDS:
        if await is_admin(gid, user_id):
            chat = await bot.get_chat(gid)
            admin_groups.append((gid, chat.title or f"Group {gid}"))

    if admin_groups:
        # لوحة تحكم
        intro_text = "🛡️ <b>مرحباً بك في لوحة تحكم بوت الحارس الأمني!</b>\n\nاختر المجموعة التي تريد إدارتها:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for gid, title in admin_groups:
            keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"إدارة {title}", callback_data=f"manage_{gid}")])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="❓ مساعدة أو استفسار", url="https://t.me/ql_om")])
        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        # الرسالة لغير الأدمن
        intro_text = (
            "🛡️ <b>مرحباً بك في بوت الحارس الأمني الذكي!</b>\n\n"
            "🔒 <i>هذا البوت مصمم خصيصًا للحفاظ على أمان مجموعاتك من السبام، الأرقام، والروابط المشبوهة. يعمل بذكاء عالي لكشف المخالفات تلقائيًا، مع حظر فوري للمخالفين.</i>\n\n"
            "📌 <b>ملاحظة:</b> البوت يعمل فقط في المجموعات المسجلة لدينا.\n\n"
            "🌟 لتسجيل مجموعتك أو لأي استفسار، تواصل معنا من الزر أدناه 👇"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 تسجيل مجموعتك الآن", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="❓ مساعدة أو استفسار", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="🌟 معلومات إضافية", callback_data="more_info")]
        ])

        await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)

# ================== handler الـ callback ==================
@dp.callback_query()
async def handle_callback_query(callback: types.CallbackQuery):
    data = callback.data
    if data == "more_info":
        more_info_text = (
            "🛡️ <b>تفاصيل كاملة عن بوت «الحارس الأمني» الذكي</b>\n\n"

            "🔥 <b>ما هو البوت وما هدفه؟</b>\n"
            "الحارس الأمني هو بوت حماية متقدم وذكي مصمم خصيصًا لحماية مجموعات التيليجرام الكبيرة والصغيرة من جميع أنواع السبام والمحتوى المزعج. يعمل تلقائيًا 24/7 دون تدخل يدوي، ويستخدم خوارزميات ذكية لكشف المخالفات بدقة عالية جدًا، مع التركيز على الحماية الفورية والفعالة.\n\n"

            "🛡️ <b>كيف يحمي البوت مجموعتك؟</b>\n"
            "• <b>كشف الأرقام الهواتف بذكاء فائق:</b> يكشف الأرقام حتى لو كانت مخفية بكل الحيل الشائعة (مثل 0/5/6/9/6/6/7/0 أو 0-5-6-9-6-6-7-0 أو ٠٥٦٩٦٦٧٠ أو مع إيموجي أو مسافات أو رموز). يدعم الأرقام السعودية والخليجية بشكل خاص (+966، 05، 5، إلخ).\n\n"
            "• <b>منع الروابط المشبوهة تمامًا:</b> يحظر روابط الواتساب الجماعية، روابط التيك توك، روابط التيليجرام غير المسموحة، والروابط المختصرة (bit.ly، t.co، إلخ). يسمح فقط بالروابط الموثوقة مثل يوتيوب، إنستغرام، تويتر (X).\n\n"
            "• <b>حظر فوري ونهائي:</b> من أول مخالفة فقط، يحذف الرسالة ويحظر العضو مباشرة (بدون كتم مؤقت أو تحذيرات)، عشان يضمن نظافة المجموعة فورًا.\n\n"
            "• <b>التعامل مع التكرار السريع:</b> حتى لو أرسل السبامر 100 رسالة في ثانية، البوت يحذفها كلها ويحظر من الأولى دون توقف أو أخطاء.\n\n"
            "• <b>إشعارات أنيقة ومؤقتة:</b> يرسل إشعار احترافي في المجموعة عن الحظر أو الحذف، ويحذفه تلقائيًا بعد دقيقتين عشان ما يزعج الشات.\n\n"
            "• <b>حماية من الإعلانات والدعوات الخارجية:</b> يمنع دعوات الواتساب والتيليجرام الغير مرغوبة، والروابط الترويجية.\n\n"

            "⚙️ <b>لماذا البوت مختلف عن البوتات الأخرى؟</b>\n"
            "• دقة كشف عالية جدًا (لا false positive تقريبًا).\n"
            "• سرعة فائقة ولا يتوقف أبدًا.\n"
            "• تصميم احترافي وإشعارات أنيقة.\n"
            "• تحديثات مستمرة لمواكبة حيل السبام الجديدة.\n\n"

            "⚠️ <b>كيفية التفعيل في مجموعتك؟</b>\n"
            "البوت لا يُضاف مباشرة ويعمل تلقائيًا، بل يتطلب تسجيل المجموعة لدينا أولاً لضمان الخصوصية والأمان والكفاءة العالية. بعد التسجيل، نضيف البوت يدويًا ويبدأ الحماية فورًا!\n\n"

            "💎 <b>هل في نسخة مدفوعة أو مخصصة؟</b>\n"
            "نعم، نوفر نسخ مخصصة بمميزات إضافية (مثل لوغز متقدم، إحصائيات، أوامر إدارية، إلخ) حسب احتياج المجموعة.\n\n"

            "📩 <b>جاهز للحماية الفائقة؟</b>\n"
            "تواصل معنا الآن لتسجيل مجموعتك أو لأي استفسار، واستمتع بمجموعة نظيفة وآمنة 100% 👇"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا للتسجيل أو الاستفسار", url="https://t.me/ql_om")]
        ])

        await callback.message.answer(more_info_text, reply_markup=keyboard, disable_web_page_preview=True)
        await callback.answer()

    elif data.startswith("manage_"):
        group_id = int(data.split("_")[1])
        group_str = str(group_id)
        if group_str not in settings:
            await callback.answer("مجموعة غير مدعومة.")
            return

        current_mode = settings[group_str]['mode']
        current_duration = settings[group_str]['mute_duration']
        duration_value, duration_unit = seconds_to_value_unit(current_duration)
        night_enabled = settings[group_str]['night_mode_enabled']
        night_start = settings[group_str]['night_start']
        night_end = settings[group_str]['night_end']

        text = f"🛡️ <b>لوحة تحكم للمجموعة ID: {group_id}</b>\n\n"
        text += f"الوضع الحالي: {mode_to_text(current_mode)}\n"
        text += f"مدة الكتم: {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n"
        text += f"الوضع الليلي: {'مفعل' if night_enabled else 'معطل'}\n"
        if night_enabled:
            text += f"وقت الإغلاق: {night_start}\n"
            text += f"وقت الفتح: {night_end}\n\n"

        text += "اختر الإجراء:"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ كتم عند المخالفة الأولى" if current_mode == 'mute' else "كتم عند المخالفة الأولى", callback_data=f"set_mode_{group_id}_mute")],
            [InlineKeyboardButton(text="✅ حظر عند المخالفة الأولى" if current_mode == 'ban' else "حظر عند المخالفة الأولى", callback_data=f"set_mode_{group_id}_ban")],
            [InlineKeyboardButton(text="✅ كتم الأولى + حظر الثانية" if current_mode == 'mute_then_ban' else "كتم الأولى + حظر الثانية", callback_data=f"set_mode_{group_id}_mute_then_ban")],
            [InlineKeyboardButton(text="تحديد مدة الكتم", callback_data=f"set_duration_{group_id}")],
            [InlineKeyboardButton(text=f"{'✅' if night_enabled else ''} تفعيل/تعطيل الوضع الليلي", callback_data=f"toggle_night_{group_id}")],
            [InlineKeyboardButton(text="تحديد توقيت الوضع الليلي", callback_data=f"set_night_time_{group_id}")]
        ])

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    elif data.startswith("toggle_night_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        if group_str in settings:
            settings[group_str]['night_mode_enabled'] = not settings[group_str]['night_mode_enabled']
            await save_settings_to_tg()
            await callback.answer("تم تبديل حالة الوضع الليلي بنجاح.")
            await handle_callback_query(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data=f"manage_{group_id}"))

    elif data.startswith("set_night_time_"):
        group_id = int(data.split("_")[3])
        group_str = str(group_id)
        if group_str not in settings:
            await callback.answer("خطأ.")
            return

        start = settings[group_str]['night_start']
        end = settings[group_str]['night_end']
        temp_night[group_id] = {'start': start, 'end': end}

        text, keyboard = get_night_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    elif data.startswith("night_"):
        parts = data.split("_")
        group_id = int(parts[1])
        action = parts[2]
        param = parts[3] if len(parts) > 3 else None

        if group_id not in temp_night:
            await callback.answer("انتهت الجلسة، ابدأ من جديد.")
            return

        if action == "start" or action == "end":
            temp_night[group_id][action] = param

        elif action == "save":
            group_str = str(group_id)
            settings[group_str]['night_start'] = temp_night[group_id]['start']
            settings[group_str]['night_end'] = temp_night[group_id]['end']
            await save_settings_to_tg()
            del temp_night[group_id]
            await callback.answer("تم حفظ توقيت الوضع الليلي بنجاح.")
            await handle_callback_query(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data=f"manage_{group_id}"))
            return

        elif action == "cancel":
            del temp_night[group_id]
            await handle_callback_query(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data=f"manage_{group_id}"))
            return

        text, keyboard = get_night_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

def get_night_editor(group_id):
    start = temp_night[group_id]['start']
    end = temp_night[group_id]['end']
    text = f"🕒 <b>تحرير توقيت الوضع الليلي</b>\n\nوقت الإغلاق الحالي: {start}\nوقت الفتح الحالي: {end}\n\nحدد الوقت الجديد (HH:MM):"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for hour in range(0, 24):
        for minute in ['00', '30']:
            time_str = f"{hour:02d}:{minute}"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=time_str, callback_data=f"night_{group_id}_start_{time_str}"),
                InlineKeyboardButton(text=time_str, callback_data=f"night_{group_id}_end_{time_str}")
            ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="💾 حفظ", callback_data=f"night_{group_id}_save"),
        InlineKeyboardButton(text="❌ إلغاء", callback_data=f"night_{group_id}_cancel")
    ])
    return text, keyboard

# ================== handler العام لكل الرسائل الأخرى ==================
@dp.message()
async def check_message(message: types.Message):
    # الخاص: رد على أي رسالة (غير /start)
    if message.chat.type == 'private':
        contact_text = (
            "🛡️ <b>شكرًا لاهتمامك ببوت الحارس الأمني!</b>\n\n"
            "🔒 نحن نقدم أقوى حماية لمجموعات التيليجرام من السبام، الأرقام، والروابط المشبوهة.\n\n"
            "📩 <b>للاستفسار أو تسجيل مجموعتك أو طلب النسخة المدفوعة:</b>\n"
            "تواصل معنا مباشرة من هنا 👇"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📞 تواصل معنا الآن", url="https://t.me/ql_om")],
            [InlineKeyboardButton(text="🌟 معلومات إضافية", callback_data="more_info")]
        ])

        await message.answer(contact_text, reply_markup=keyboard, disable_web_page_preview=True)
        return

    # المجموعات
    chat_id = message.chat.id
    if chat_id not in ALLOWED_GROUP_IDS:
        return

    user_id = message.from_user.id

    group_str = str(chat_id)
    # تحقق من الوضع الليلي أولاً
    if group_str in settings and settings[group_str]['night_mode_enabled']:
        start_time = datetime.strptime(settings[group_str]['night_start'], '%H:%M').time()
        end_time = datetime.strptime(settings[group_str]['night_end'], '%H:%M').time()
        now = datetime.now().time()
        is_night = False
        if start_time < end_time:
            is_night = start_time <= now < end_time
        else:
            is_night = start_time <= now or now < end_time

        if is_night and not await is_admin(chat_id, user_id):
            try:
                await message.delete()
            except Exception:
                pass
            return  # منع الرسائل غير الإدارية

    if await is_admin(chat_id, user_id):
        return

    text = (message.text or message.caption or "").strip()
    if not contains_spam(text):
        return

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"فشل حذف الرسالة {message.message_id}: {e}")

    mode = settings.get(group_str, {'mode': 'ban', 'mute_duration': 86400})['mode']
    mute_duration = settings.get(group_str, {'mode': 'ban', 'mute_duration': 86400})['mute_duration']
    full_name = message.from_user.full_name
    notification = ""
    action_taken = False

    if mode == 'ban':
        if not await is_banned(chat_id, user_id):
            try:
                await bot.ban_chat_member(chat_id, user_id)
                action_taken = True
                notification = f"🚫 <b>تم حظر العضو نهائيًا</b>\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: نشر سبام\n🛡️ المجموعة محمية"
            except Exception as e:
                logger.warning(f"فشل حظر {user_id}: {e}")
    elif mode == 'mute':
        try:
            until_date = int(time.time()) + mute_duration if mute_duration > 30 else 0  # إذا أقل من 30 ثانية، اجعله دائمًا
            await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
            action_taken = True
            duration_value, duration_unit = seconds_to_value_unit(mute_duration)
            notification = f"🔇 <b>تم كتم العضو</b> لمدة {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: نشر سبام\n🛡️ المجموعة محمية"
        except Exception as e:
            logger.warning(f"فشل كتم {user_id}: {e}")
    elif mode == 'mute_then_ban':
        if 'violations' not in settings[group_str]:
            settings[group_str]['violations'] = {}

        user_violations = settings[group_str]['violations']
        current_count = user_violations.get(user_id, 0)
        current_count += 1
        user_violations[user_id] = current_count
        await save_settings_to_tg()  # حفظ فوري

        if current_count == 1:
            try:
                until_date = int(time.time()) + mute_duration if mute_duration > 30 else 0
                await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
                action_taken = True
                duration_value, duration_unit = seconds_to_value_unit(mute_duration)
                notification = f"🔇 <b>تم كتم العضو (مخالفة أولى)</b> لمدة {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: نشر سبام\n🛡️ المجموعة محمية"
            except Exception as e:
                logger.warning(f"فشل كتم {user_id}: {e}")
        else:
            if not await is_banned(chat_id, user_id):
                try:
                    await bot.ban_chat_member(chat_id, user_id)
                    action_taken = True
                    notification = f"🚫 <b>تم حظر العضو نهائيًا (مخالفة ثانية)</b>\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: نشر سبام\n🛡️ المجموعة محمية"
                except Exception as e:
                    logger.warning(f"فشل حظر {user_id}: {e}")

    if notification:
        try:
            notify_msg = await bot.send_message(chat_id, notification)
            asyncio.create_task(delete_after_delay(notify_msg, 120))
        except Exception as e:
            logger.warning(f"فشل إرسال الإشعار: {e}")
    elif not action_taken:
        notification = f"🗑️ <b>تم حذف رسالة سبام</b>\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n⚠️ العضو محظور مسبقًا"
        try:
            notify_msg = await bot.send_message(chat_id, notification)
            asyncio.create_task(delete_after_delay(notify_msg, 120))
        except Exception as e:
            logger.warning(f"فشل إرسال الإشعار: {e}")

async def delete_after_delay(message: types.Message, delay: int = 120):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

# ================== FastAPI Webhook ==================
app = FastAPI()

WEBHOOK_PATH = f"/bot/{TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    await load_settings_from_tg()
    asyncio.create_task(night_mode_checker())  # بدء التحقق الدوري للوضع الليلي
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook تم تفعيله بنجاح: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"فشل تفعيل الـ webhook: {e}")

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
        logger.error(f"خطأ في معالجة التحديث: {e}")
    return Response(content="OK", status_code=200)

@app.get("/")
async def root():
    return {"status": "البوت يعمل بنجاح! 🟢"}