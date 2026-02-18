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

logging.basicConfig(level=logging.WARNING) # کاهش لاگ برای سرعت بیشتر
logger = logging.getLogger("LiveStreamer")

# ==========================================
# 🔐 مدیریت لیست سفید (Strict Policy)
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return [] # شروع با لیست خالی
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
# 🧹 مدیریت حافظه
# ==========================================
async def force_cleanup():
    gc.collect()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 آمار سیستم
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent()
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n🖥 CPU: {cpu}%"

# ==========================================
# 📡 هسته استریم (ضد لگ)
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

    # پارامترهای اختصاصی FFmpeg برای حذف لگ و تاخیر در نسخه 1.2.9
    # -re: خواندن با سرعت واقعی | -preset ultrafast: کمترین فشار به CPU
    # -tune zerolatency: بهینه‌سازی برای پخش زنده
    ffmpeg_args = "-re -vcodec libx264 -preset ultrafast -tune zerolatency -max_delay 0 -bf 0"
    
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.LOW, # کیفیت پایین‌تر صوت برای پایداری بیشتر
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
            raise Exception("⚠️ ویس‌کال خاموش است!")
        raise e

# ==========================================
# 👮‍♂️ سیستم امنیتی سخت‌گیرانه (فقط لیست سفید)
# ==========================================
async def security_check(event):
    chat_id = event.chat_id
    
    # قانون جدید: حتی اگر ADMIN_ID باشد، چت باید حتماً در لیست سفید باشد
    if chat_id in ALLOWED_CHATS:
        return True
    
    # اگر چت مجاز نبود (حتی برای ادمین اصلی)
    try:
        await event.reply("💢 این چت توی لیست سفید من نیست! ادمینت غلط کرده منو ادد کرده. لفت میدم سیکتیر!")
        await user_client.delete_dialog(chat_id) 
    except: pass
    return False

# ==========================================
# 🤖 ربات مدیریت (لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    await event.reply("✅ ربات آنلاین است.\n\nپنل مدیریت یوزربات فعال است.")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        await event.reply("✅ کد ارسالی: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 دستورات یوزربات (Userbot Commands)
# ==========================================

# افزودن چت (فقط از طریق پیام مستقیم ادمین به یوزربات یا دستور در چت فعلی)
@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?:\s+(.+))?'))
async def add_chat(event):
    if event.sender_id != ADMIN_ID: return # فقط مالک می‌تواند چت اضافه کند
    target = event.pattern_match.group(1)
    chat_id = event.chat_id
    if target:
        try:
            e = await user_client.get_entity(target)
            chat_id = e.id
        except: return await event.reply("❌ پیدا نشد.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{chat_id}` با موفقیت مجاز شد.")
    else:
        await event.reply("⚠️ این چت از قبل مجاز بود.")

# حذف چت از لیست سفید
@user_client.on(events.NewMessage(pattern=r'(?i)^/del'))
async def del_chat(event):
    if event.sender_id != ADMIN_ID: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 چت از لیست سفید حذف شد.")
    else:
        await event.reply("⚠️ این چت در لیست نبود.")

# پینگ و وضعیت سیستم
@user_client.on(events.NewMessage(pattern=r'(?i)^/ping'))
async def ping_cmd(event):
    if not await security_check(event): return
    start = time.time()
    info = await get_system_info()
    ping = round((time.time() - start) * 1000)
    await event.reply(f"🚀 **وضعیت سیستم روان**\n📶 Ping: `{ping}ms`\n{info}")

# شروع لایو (بدون لگ)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_cmd(event):
    # اول چک میکند چت مجاز است یا نه (حتی برای ادمین)
    if not await security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    
    status = await event.reply("📡 در حال استخراج لینک و بهینه‌سازی...")
    
    try:
        if url_arg:
            final_url, title = await get_stream_link(url_arg)
        else:
            title = "Default Live TV"

        await start_stream_v1(event.chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده پایدار**\n📺 `{title}`\n⚡️ بهینه‌سازی: Zerolatency Mode")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")

# قطع پخش
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_cmd(event):
    if not await security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup()
        await event.reply("⏹ پخش متوقف و حافظه تخلیه شد.")
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
    app.router.add_get("/", lambda r: web.Response(text="Stable Streamer Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    print("🚀 Starting Stable Streamer...")
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