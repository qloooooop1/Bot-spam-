import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.types import ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

# ================== الإعدادات ==================
TOKEN = os.getenv("TOKEN")  # سيتم أخذه من Environment Variables في Render
GROUP_ID = -1001224326322
GROUP_USERNAME = None  # إذا كان لمجموعتك يوزرنيم، ضعه هنا مثل "mygroup"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# التصحيح الرئيسي هنا: استخدام DefaultBotProperties
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# تحويل الأرقام العربية/الفارسية/الهندية
def normalize_digits(text: str) -> str:
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹०۱۲３४۵۶۷۸९', '012345678901234567890123456789')
    return text.translate(trans)

# أنماط الكشف الذكية
PHONE_PATTERN = re.compile(r'(?:\+?\d{1,4}[\W_*/.-]?)?(?:\(\d{1,4}\)[\W_*/.-]?)?\d{3,4}[\W_*/.-]?\d{3,4}[\W_*/.-]?\d{3,9}(?!\d)')
PHONE_CONTEXT_PATTERN = re.compile(
    r'(?:اتصل|رقمي|واتس|هاتف|mobile|phone|call|contact|whatsapp|📞|☎️|اسمي|فلان|[\w\u0600-\u06FF]{2,})'
    r'[\s\W_*/]{0,10}'
    r'(?:\+?\d{1,4}[\W_*/.-]?\d{3,4}[\W_*/.-]?\d{3,4}[\W_*/.-]?\d{3,9})',
    re.IGNORECASE | re.UNICODE
)
WHATSAPP_INVITE_PATTERN = re.compile(r'(?:h\s*t\s*t\s*p\s*s?://)?(?:chat\.\s*whatsapp\.\s*com|wa\.\s*me|whatsapp\.\s*com)/[^\s]*|\+\w{8,}', re.IGNORECASE)
TELEGRAM_INVITE_PATTERN = re.compile(r'(?:h\s*t\s*t\s*p\s*s?://)?t\.\s*me/(?:joinchat/|[+])[\w-]{10,}|(?:h\s*t\s*t\s*p\s*s?://)?t\.\s*me/(?!'+(GROUP_USERNAME or '')+r'$)[^\s/]+', re.IGNORECASE)
TIKTOK_PATTERN = re.compile(r'(?:h\s*t\s*t\s*p\s*s?://)?(?:vm\.|www\.)?tiktok\.\s*com/[^\s]*|(?:h\s*t\s*t\s*p\s*s?://)?tiktok\.\s*com/@[^\s/]+/video/[^\s]*', re.IGNORECASE)
SHORT_LINK_PATTERN = re.compile(r'(?:h\s*t\s*t\s*p\s*s?://)?(?:bit\.ly|tinyurl\.com|goo\.gl|t\.co)/[^\s]*', re.IGNORECASE)

ALLOWED_DOMAINS = ["youtube.com", "youtu.be", "instagram.com", "instagr.am", "x.com", "twitter.com"]

violations = {}
last_violation = {}

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False

def contains_spam(text: str) -> bool:
    if not text:
        return False
    normalized = normalize_digits(text)

    phones = PHONE_PATTERN.findall(normalized)
    if phones:
        clean_phones = [''.join(re.findall(r'\d', p)) for p in phones]
        if any(len(p) >= 9 for p in clean_phones):
            return True

    if PHONE_CONTEXT_PATTERN.search(normalized):
        return True

    if (WHATSAPP_INVITE_PATTERN.search(text) or
        TELEGRAM_INVITE_PATTERN.search(text) or
        TIKTOK_PATTERN.search(text) or
        SHORT_LINK_PATTERN.search(text)):
        return True

    urls = re.findall(r'(?:h\s*t\s*t\s*p\s*s?://)?[^\s/]+\.[^\s/]+', text, re.IGNORECASE)
    for url in urls:
        clean_url = url.replace(' ', '').lower()
        if not any(domain in clean_url for domain in ALLOWED_DOMAINS):
            return True

    has_phone = bool(PHONE_PATTERN.search(normalized))
    has_link = bool(re.search(r'(?:h\s*t\s*t\s*p\s*s?://)?[^\s/]+\.[^\s/]+', text, re.IGNORECASE))
    if has_phone and has_link:
        return True

    return False

@dp.message()
async def check_message(message: types.Message):
    if message.chat.id != GROUP_ID:
        return

    user_id = message.from_user.id
    if await is_admin(GROUP_ID, user_id):
        return

    text = message.text or message.caption or ""
    if not contains_spam(text):
        return

    await message.delete()

    now = datetime.now()
    if user_id in last_violation and now - last_violation[user_id] > timedelta(days=7):
        violations[user_id] = 0

    violations[user_id] = violations.get(user_id, 0) + 1
    last_violation[user_id] = now
    count = violations[user_id]
    full_name = message.from_user.full_name

    if count == 1:
        await bot.restrict_chat_member(GROUP_ID, user_id, ChatPermissions(can_send_messages=False),
                                       until_date=int(asyncio.time() + 86400))
        notification = (
            f"⚠️ <b>تم كتم العضو مؤقتاً</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 السبب: نشر رقم هاتف أو رابط مشبوه\n"
            f"⏳ المدة: 24 ساعة\n"
            f"🔄 التكرار يؤدي إلى الحظر الدائم"
        )
    else:
        await bot.ban_chat_member(GROUP_ID, user_id)
        violations.pop(user_id, None)
        notification = (
            f"🚫 <b>تم حظر العضو نهائياً</b>\n\n"
            f"👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n"
            f"📛 السبب: تكرار نشر سبام\n"
            f"🛡️ المجموعة محمية"
        )

    notify_msg = await bot.send_message(GROUP_ID, notification)
    await asyncio.sleep(120)
    try:
        await notify_msg.delete()
    except:
        pass

# ================== معالج أمر /start مع مقدمة احترافية ==================
@dp.message(Command("start"))
async def start_command(message: types.Message):
    if message.chat.type != "private":
        return  # يعمل فقط في المحادثات الخاصة

    intro_text = (
        "🛡️ <b>مرحباً بك في بوت الحارس الأمني الذكي!</b>\n\n"
        "🔒 <i>هذا البوت مصمم خصيصًا للحفاظ على أمان مجموعاتك من السبام، الأرقام، والروابط المشبوهة. يعمل بذكاء عالي لكشف المخالفات تلقائيًا، مع كتم أو حظر المخالفين بطريقة احترافية وسريعة.</i>\n\n"
        "📌 <b>ملاحظة مهمة:</b> البوت يعمل فقط في المجموعات الخاصة المسجلة لدينا. لتسجيل مجموعتك أو الحصول على مزيد من المعلومات، اضغط على الزر أدناه لبدء العملية.\n\n"
        "🌟 <b>ابدأ الآن واستمتع بحماية فائقة!</b>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 تسجيل مجموعتك الآن", url="https://t.me/ql_om")],
        [InlineKeyboardButton(text="❓ استفسار أو مساعدة", url="https://t.me/ql_om")]
    ])

    await message.answer(intro_text, reply_markup=keyboard, disable_web_page_preview=True)

# ================== FastAPI + Webhook ==================
app = FastAPI()

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook تم تفعيله: {WEBHOOK_URL}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json(), from_attributes=True)
    asyncio.create_task(dp.feed_update(bot=bot, update=update))
    return Response(content="OK", status_code=200)

@app.get("/")
async def root():
    return {"status": "البوت يعمل بنجاح! 🟢"}