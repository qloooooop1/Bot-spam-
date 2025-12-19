import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.types import ChatPermissions
from aiogram.webhook import SimpleRequestHandler

# ================== الإعدادات ==================
TOKEN = os.getenv("TOKEN")  # سيأتي من Render Env Vars
GROUP_ID = -1001224326322
GROUP_USERNAME = None  # إذا كان لمجموعتك username، ضعه هنا مثل "mygroup"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# تحويل الأرقام العربية
def normalize_digits(text: str) -> str:
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹०१२३४५۶۷८९', '012345678901234567890123456789')
    return text.translate(trans)

# أنماط الكشف الذكية (نفس اللي كان عندنا سابقاً)
PHONE_PATTERN = re.compile(r'(?:\+?\d{1,4}[\W_*/.-]?)?(?:\(\d{1,4}\)[\W_*/.-]?)?\d{3,4}[\W_*/.-]?\d{3,4}[\W_*/.-]?\d{3,9}(?!\d)')
PHONE_CONTEXT_PATTERN = re.compile(r'(?:اتصل|رقمي|واتس|هاتف|mobile|phone|call|contact|whatsapp|📞|☎️|اسمي|فلان|[\w\u0600-\u06FF]{2,})[\s\W_*/]{0,10}(?:\+?\d{1,4}[\W_*/.-]?\d{3,4}[\W_*/.-]?\d{3,4}[\W_*/.-]?\d{3,9})', re.IGNORECASE | re.UNICODE)
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

    if (WHATSAPP_INVITE_PATTERN.search(text) or TELEGRAM_INVITE_PATTERN.search(text) or
        TIKTOK_PATTERN.search(text) or SHORT_LINK_PATTERN.search(text)):
        return True

    urls = re.findall(r'(?:h\s*t\s*t\s*p\s*s?://)?[^\s/]+\.[^\s/]+/[^\s]*', text, re.IGNORECASE)
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
        await bot.restrict_chat_member(GROUP_ID, user_id, ChatPermissions(can_send_messages=False), until_date=int(asyncio.time() + 86400))
        notification = f"⚠️ <b>تم كتم العضو مؤقتاً</b>\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: نشر رقم هاتف أو رابط مشبوه\n⏳ المدة: 24 ساعة\n🔄 التكرار = حظر دائم"
    else:
        await bot.ban_chat_member(GROUP_ID, user_id)
        violations.pop(user_id, None)
        notification = f"🚫 <b>تم حظر العضو نهائياً</b>\n\n👤 <a href='tg://user?id={user_id}'>{full_name}</a>\n📛 السبب: تكرار السبام\n🛡️ المجموعة محمية"

    notify_msg = await bot.send_message(GROUP_ID, notification)
    await asyncio.sleep(120)
    try:
        await notify_msg.delete()
    except:
        pass

# ================== FastAPI Webhook ==================
app = FastAPI()

WEBHOOK_PATH = f"/bot/{TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set: {WEBHOOK_URL}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = types.Update.model_validate(await request.json(), from_attributes=True)
    SimpleRequestHandler(dispatcher=dp, bot=bot).feed_update(bot=bot, update=update)
    return Response(content="OK")

@app.get("/")
async def root():
    return {"status": "Bot is running!"}