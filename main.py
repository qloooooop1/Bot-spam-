import asyncio
import logging
import os
import re

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

# ================== handler /start أولاً (الحل النهائي) ==================
@dp.message(Command(commands=["start"]))
async def start_command(message: types.Message):
    logger.info(f"تم استلام /start من {message.from_user.id}")

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
    if callback.data == "more_info":
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

# ================== handler العام لكل الرسائل الأخرى (آخر شيء) ==================
@dp.message()
async def check_message(message: types.Message):
    # الخاص: رد على أي رسالة (غير /start لأنه معالج بالفعل فوق)
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
    if message.chat.id not in ALLOWED_GROUP_IDS:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    if await is_admin(chat_id, user_id):
        return

    text = (message.text or message.caption or "").strip()
    if not contains_spam(text):
        return

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"فشل حذف الرسالة {message.message_id}: {e}")

    if not await is_banned(chat_id, user_id):
        try:
            await bot.ban_chat_member(chat_id, user_id)
            banned = True
        except Exception as e:
            logger.warning(f"فشل حظر العضو {user_id}: {e}")
            banned = False
    else:
        banned = False

    full_name = message.from_user.full_name

    if banned:
        notification = (
            f"🚫 <b>تم حظر العضو نهائيًا</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 السبب: نشر سبام (رقم هاتف أو رابط مشبوه)\n"
            f"🛡️ المجموعة محمية"
        )
    else:
        notification = (
            f"🗑️ <b>تم حذف رسالة سبام</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"⚠️ العضو محظور مسبقًا"
        )

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
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook تم تفعيله بنجاح: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"فشل تفعيل الـ webhook: {e}")

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
        logger.error(f"خطأ في معالجة التحديث: {e}")
    return Response(content="OK", status_code=200)

@app.get("/")
async def root():
    return {"status": "البوت يعمل بنجاح! 🟢"}