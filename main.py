import os
import asyncio
import logging
import json
import time
import psutil
import gc
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel

# کتابخانه‌های نسخه 1.2.9 (لگاسی)
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality
import yt_dlp

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("LiveStreamer")

login_state = {}

# ==========================================
# 🔐 مدیریت لیست سفید
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return []
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            return [int(i) for i in data]
    except: return []

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(list(set(chat_list)), f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent()
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n🖥 CPU: {cpu}%"

async def force_cleanup():
    gc.collect()

# ==========================================
# 📡 هسته استریم (بدون لگ)
# ==========================================
async def get_stream_link(url):
    ydl_opts = {
        'format': 'best[height<=360]/worst', 
        'noplaylist': True, 
        'quiet': True,
        'no_warnings': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except: return url, "Live Stream"

async def start_stream_v1(chat_id, source):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات اختصاصی FFmpeg برای حذف لگ
    ffmpeg_args = "-re -vcodec libx264 -preset ultrafast -tune zerolatency -max_delay 0 -bf 0"
    
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.LOW,
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=ffmpeg_args
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(0.5)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال در این چت باز نیست!")
        raise e

# ==========================================
# 👮‍♂️ سیستم امنیتی (فقط لیست سفید)
# ==========================================
async def security_check(event):
    chat_id = event.chat_id
    if chat_id in ALLOWED_CHATS:
        return True
    
    # اگر چت مجاز نبود، فوش بده و لفت بده
    try:
        await event.reply("💢 این چت توی لیست سفید من نیست! ادمینت غلط کرده منو اینجا ادد کرده. لفت میدم سیکتیر!")
        await user_client.delete_dialog(chat_id) 
    except: pass
    return False

# ==========================================
# 🤖 ربات لاگین (Bot API)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    status = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(f"🤖 **ربات مدیریت استریم**\nوضعیت یوزربات: {status}\n\n🔐 راهنمای لاگین:\n1. `/phone +989...` \n2. `/code 12345` \n3. `/password abc...` (اگر رمز دارید)")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    phone = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        res = await user_client.send_code_request(phone)
        login_state.update({'phone': phone, 'hash': res.phone_code_hash})
        await event.reply("✅ کد تایید ارسال شد.\nحالا دستور رو بزنید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ یوزربات با موفقیت لاگین شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError:
        await event.reply("⚠️ اکانت شما تایید دو مرحله‌ای دارد.\nدستور رو بزنید: `/password رمز_شما`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    pwd = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(password=pwd)
        await event.reply("✅ ورود با رمز عبور موفقیت‌آمیز بود.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 👤 دستورات یوزربات (Userbot)
# ==========================================

@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?:\s+(.+))?'))
async def add_chat(event):
    if event.sender_id != ADMIN_ID: return
    target = event.pattern_match.group(1)
    chat_id = event.chat_id
    if target:
        try:
            e = await user_client.get_entity(target)
            chat_id = e.id
        except: return await event.reply("❌ چت پیدا نشد.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{chat_id}` به لیست مجاز اضافه شد.")
    else:
        await event.reply("⚠️ این چت قبلاً اضافه شده بود.")

@user_client.on(events.NewMessage(pattern=r'(?i)^/del'))
async def del_chat(event):
    if event.sender_id != ADMIN_ID: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 چت از لیست سفید حذف شد.")
    else:
        await event.reply("⚠️ این چت در لیست نبود.")

@user_client.on(events.NewMessage(pattern=r'(?i)^/ping'))
async def ping_cmd(event):
    if not await security_check(event): return
    start = time.time()
    info = await get_system_info()
    ping = round((time.time() - start) * 1000)
    await event.reply(f"📶 **وضعیت اتصال**\nتأخیر: `{ping}ms`\n{info}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_cmd(event):
    if not await security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    status = await event.reply("📡 در حال استخراج و بهینه‌سازی لایو...")
    
    try:
        if url_arg:
            final_url, title = await get_stream_link(url_arg)
        else:
            title = "Default TV"

        await start_stream_v1(event.chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده فعال شد**\n📺 `{title}`\n⚡️ حالت: No-Lag Zerolatency")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_cmd(event):
    if not await security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup()
        await event.reply("⏹ استریم متوقف شد.")
    except: pass

@call_py.on_stream_end()
async def on_end(client, update):
    try: await client.leave_group_call(update.chat_id)
    except: pass
    await force_cleanup()

# ==========================================
# 🌐 سرور و اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is Active"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    print("🚀 Starting Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            await call_py.start()
    except: pass
    
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())