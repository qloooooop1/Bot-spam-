import asyncio
import logging
import os
import re
from datetime import datetime

from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

# ================== الإعدادات ==================
TOKEN = os.getenv("TOKEN")  # تأكد من وضعه في Environment Variables على Render

# قائمة المجموعات التي يعمل فيها البوت (أضف هنا أي مجموعة جديدة)
ALLOWED_GROUP_IDS = [-1001224326322, -1002370282238]

GROUP_USERNAME = None  # اختياري: يوزرنيم المجموعة إذا كان موجودًا

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# تحويل الأرقام العربية/فارسية/هندية إلى لاتينية
def normalize_digits(text: str) -> str:
    trans = str.maketrans(
        '٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٠١٢٣۴۵۶۷۸۹',
        '012345678901234567890123456789'
    )
    return text.translate(trans)

# أنماط الكشف عن السبام (محسنة لكشف الحيل المخفية)
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
        return True  # إذا حصل خطأ (مثل العضو محظور بالفعل) نفترض أنه محظور

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

    # روابط غير مسموحة
    urls = re.findall(r'https?://[^\s]+|www\.[^\s]+|[^\s]+\.[^\s]{2,}', text, re.IGNORECASE)
    for url in urls:
        clean_url = url.replace(' ', '').lower()
        if not any(domain in clean_url for domain in ALLOWED_DOMAINS):
            return True

    # رقم + رابط معًا
    has_phone = bool(PHONE_PATTERN.search(normalized))
    has_link = bool(re.search(r'https?://|www\.|[^\s]+\.[^\s/]+', text, re.IGNORECASE))
    if has_phone and has_link:
        return True

    return False

# فحص الرسائل في المجموعات المسموحة
@dp.message()
async def check_message(message: types.Message):
    if message.chat.id not in ALLOWED_GROUP_IDS:
        # إذا كانت رسالة خاصة غير /start، رد اختباري
        if message.chat.type == 'private' and not message.text.startswith('/start'):
            await message.answer("مرحبا! استخدم /start للبدء.")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    if await is_admin(chat_id, user_id):
        return

    text = (message.text or message.caption or "").strip()
    if not contains_spam(text):
        return

    # حذف الرسالة المخالفة (دائمًا)
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"فشل حذف الرسالة {message.message_id}: {e}")

    # حظر فقط إذا لم يكن محظورًا بالفعل
    if not await is_banned(chat_id, user_id):
        try:
            await bot.ban_chat_member(chat_id, user_id)
            banned = True
        except Exception as e:
            logger.warning(f"فشل حظر العضو {user_id}: {e}")
            banned = False
    else:
        banned = False  # محظور مسبقًا

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
            f"⚠️ العضو محظور مسبقًا أو تم حظره"
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

# أمر /start في المحادثة الخاصة
@dp.message(CommandStart())
async def start_command(message: types.Message):
    logger.info(f"Received /start from user {message.from_user.id}")  # logging للتتبع
    intro_text = (
        "🛡️ <b>مرحباً بك في بوت الحارس الأمني الذكي!</b>\n\n"
        "🔒 <i>هذا البوت مصمم خصيصًا للحفاظ على أمان مجموعاتك من السبام، الأرقام، والروابط المشبوهة. يعمل بذكاء عالي لكشف المخالفات تلقائيًا، مع كتم أو حظر المخالفين بطريقة احترافية وسريعة.</i>\n\n"
        "📌 <b>ملاحظة مهمة:</b> البوت يعمل فقط في المجموعات الخاصة المسجلة لدينا. لتسجيل مجموعتك أو الحصول على مزيد من المعلومات، اضغط على الزر أدناه.\n\n"
        "🌟 <b>ابدأ الآن واستمتع بحماية فائقة!</b>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 تسجيل مجموعتك الآن", url="https://t.me/ql_om")],
        [InlineKeyboardButton(text="❓ استفسار أو مساعدة", url="https://t.me/ql_om")]
    ])

    await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)

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

# إذا أردت استخدام polling بدلاً من webhook للاختبار (علق الـ webhook واستخدم هذا):
# async def on_startup():
#     dp.start_polling(bot)

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