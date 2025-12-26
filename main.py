import asyncio
import logging
import os
import re
import time
import json

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

# تحويل الأرقام العربية إلى لاتينية
def normalize_digits(text: str) -> str:
    trans = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣۴۵۶۷۸۹',
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

# إعدادات جديدة
SETTINGS_FILE = "settings.json"

settings = {}  # {group_id: {'mode': 'ban' | 'mute' | 'mute_then_ban', 'mute_duration': seconds}}
violations = {}  # {group_id: {user_id: count}}

temp_duration = {}  # {group_id: {'value': int, 'unit': 'minute'|'hour'|'day'|'month'|'year'}}

unit_seconds = {
    'minute': 60,
    'hour': 3600,
    'day': 86400,
    'month': 2592000,  # 30 days
    'year': 31536000   # 365 days
}

unit_to_text_dict = {'minute': 'دقيقة', 'hour': 'ساعة', 'day': 'يوم', 'month': 'شهر', 'year': 'سنة'}

def load_settings():
    global settings
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
            settings = {k: v for k, v in loaded.items()}
    # ضمان وجود الإعدادات الافتراضية
    for gid in ALLOWED_GROUP_IDS:
        group_str = str(gid)
        if group_str not in settings:
            settings[group_str] = {'mode': 'ban', 'mute_duration': 86400}

def save_settings():
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

# تهيئة violations
for gid in ALLOWED_GROUP_IDS:
    violations[gid] = {}

# دالة لتحويل الثواني إلى قيمة ووحدة للعرض (تحسين: اختيار أكبر وحدة مناسبة)
def seconds_to_value_unit(seconds: int):
    if seconds == 0:
        return 0, 'minute'
    for unit, secs in sorted(unit_seconds.items(), key=lambda x: x[1], reverse=True):
        if seconds >= secs:
            value = seconds // secs
            remainder = seconds % secs
            if remainder == 0:
                return value, unit
            # إذا لم يكن مضاعفاً تماماً، نستخدم الوحدة الأكبر مع الكسر، لكن للبساطة نستخدم أكبر ممكن
    # fallback إلى دقائق
    return seconds // 60, 'minute'

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
        # الرسالة القديمة لغير الأدمن
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

        text = f"🛡️ <b>لوحة تحكم للمجموعة ID: {group_id}</b>\n\n"
        text += f"الوضع الحالي: {mode_to_text(current_mode)}\n"
        text += f"مدة الكتم: {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n"

        text += "اختر الوضع:"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ كتم عند المخالفة الأولى" if current_mode == 'mute' else "كتم عند المخالفة الأولى", callback_data=f"set_mode_{group_id}_mute")],
            [InlineKeyboardButton(text="✅ حظر عند المخالفة الأولى" if current_mode == 'ban' else "حظر عند المخالفة الأولى", callback_data=f"set_mode_{group_id}_ban")],
            [InlineKeyboardButton(text="✅ كتم الأولى + حظر الثانية" if current_mode == 'mute_then_ban' else "كتم الأولى + حظر الثانية", callback_data=f"set_mode_{group_id}_mute_then_ban")],
            [InlineKeyboardButton(text="تحديد مدة الكتم", callback_data=f"set_duration_{group_id}")]
        ])

        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    elif data.startswith("set_mode_"):
        parts = data.split("_")
        group_id = int(parts[2])
        mode = "_".join(parts[3:])
        group_str = str(group_id)
        if group_str in settings:
            settings[group_str]['mode'] = mode
            save_settings()
            await callback.answer(f"تم تغيير الوضع إلى: {mode_to_text(mode)}")
            # إعادة عرض اللوحة
            await handle_callback_query(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data=f"manage_{group_id}"))
        else:
            await callback.answer("خطأ.")

    elif data.startswith("set_duration_"):
        group_id = int(data.split("_")[2])
        group_str = str(group_id)
        if group_str not in settings:
            await callback.answer("خطأ.")
            return

        current_duration = settings[group_str]['mute_duration']
        value, unit = seconds_to_value_unit(current_duration)
        temp_duration[group_id] = {'value': max(1, value), 'unit': unit}

        text, keyboard = get_duration_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

    elif data.startswith("duration_"):
        parts = data.split("_")
        group_id = int(parts[1])
        action = parts[2]
        param = "_".join(parts[3:]) if len(parts) > 3 else None

        if group_id not in temp_duration:
            await callback.answer("انتهت الجلسة، ابدأ من جديد.")
            return

        if action in ["plus", "minus"]:
            delta = int(param) if action == "plus" else -int(param)
            temp_duration[group_id]['value'] = max(1, temp_duration[group_id]['value'] + delta)
        elif action == "unit":
            if param in unit_seconds:
                temp_duration[group_id]['unit'] = param
        elif action == "save":
            seconds = temp_duration[group_id]['value'] * unit_seconds[temp_duration[group_id]['unit']]
            group_str = str(group_id)
            settings[group_str]['mute_duration'] = seconds
            save_settings()
            del temp_duration[group_id]
            await callback.answer("تم حفظ مدة الكتم بنجاح.")
            await handle_callback_query(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data=f"manage_{group_id}"))
            return
        elif action == "cancel":
            del temp_duration[group_id]
            await handle_callback_query(types.CallbackQuery(id=callback.id, from_user=callback.from_user, chat_instance=callback.chat_instance, message=callback.message, data=f"manage_{group_id}"))
            return

        text, keyboard = get_duration_editor(group_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()

def get_duration_editor(group_id):
    value = temp_duration[group_id]['value']
    unit = temp_duration[group_id]['unit']
    text = f"🕒 <b>تحرير مدة الكتم</b>\n\nالقيمة الحالية: {value} {unit_to_text_dict.get(unit, unit)}\n\nاستخدم الأزرار للتعديل:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="-10", callback_data=f"duration_{group_id}_minus_10"),
         InlineKeyboardButton(text="-1", callback_data=f"duration_{group_id}_minus_1"),
         InlineKeyboardButton(text=f"{value}", callback_data="dummy"),
         InlineKeyboardButton(text="+1", callback_data=f"duration_{group_id}_plus_1"),
         InlineKeyboardButton(text="+10", callback_data=f"duration_{group_id}_plus_10")],
        [InlineKeyboardButton(text=f"✅ دقيقة" if unit == 'minute' else "دقيقة", callback_data=f"duration_{group_id}_unit_minute"),
         InlineKeyboardButton(text=f"✅ ساعة" if unit == 'hour' else "ساعة", callback_data=f"duration_{group_id}_unit_hour"),
         InlineKeyboardButton(text=f"✅ يوم" if unit == 'day' else "يوم", callback_data=f"duration_{group_id}_unit_day")],
        [InlineKeyboardButton(text=f"✅ شهر" if unit == 'month' else "شهر", callback_data=f"duration_{group_id}_unit_month"),
         InlineKeyboardButton(text=f"✅ سنة" if unit == 'year' else "سنة", callback_data=f"duration_{group_id}_unit_year")],
        [InlineKeyboardButton(text="💾 حفظ", callback_data=f"duration_{group_id}_save"),
         InlineKeyboardButton(text="❌ إلغاء", callback_data=f"duration_{group_id}_cancel")]
    ])
    return text, keyboard

def mode_to_text(mode):
    if mode == 'mute':
        return 'كتم عند المخالفة الأولى'
    elif mode == 'ban':
        return 'حظر عند المخالفة الأولى'
    elif mode == 'mute_then_ban':
        return 'كتم الأولى + حظر الثانية'
    return mode

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

    if await is_admin(chat_id, user_id):
        return

    text = (message.text or message.caption or "").strip()
    if not contains_spam(text):
        return

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"فشل حذف الرسالة {message.message_id}: {e}")

    group_str = str(chat_id)
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
            until_date = int(time.time()) + mute_duration if mute_duration > 0 else 0
            await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
            action_taken = True
            duration_value, duration_unit = seconds_to_value_unit(mute_duration)
            notification = f"🔇 <b>تم كتم العضو</b> لمدة {duration_value} {unit_to_text_dict.get(duration_unit, duration_unit)}\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: نشر سبام\n🛡️ المجموعة محمية"
        except Exception as e:
            logger.warning(f"فشل كتم {user_id}: {e}")
    elif mode == 'mute_then_ban':
        if user_id not in violations[chat_id]:
            violations[chat_id][user_id] = 0
        violations[chat_id][user_id] += 1
        if violations[chat_id][user_id] == 1:
            try:
                until_date = int(time.time()) + mute_duration if mute_duration > 0 else 0
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
    load_settings()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook تم تفعيله بنجاح: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"فشل تفعيل الـ webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    save_settings()
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