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

# لینک تست شده و پایدار ایران اینترنشنال
DEFAULT_LIVE_URL = "https://fo-live.iraninternational.com/out/v1/ad74279027874747805d7621c5484828/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("LiveStreamer")

login_state = {}

# ==========================================
# 🔐 مدیریت لیست سفید (Strict Policy)
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
# 📡 هسته استریم (رفع صفحه سبز و نبود صدا)
# ==========================================
async def get_stream_link(url):
    ydl_opts = {
        'format': 'best[height<=480]/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except: return url, "Live Stream"

async def start_stream_v1(chat_id, source):
    """پخش لایو با تنظیمات فوق پایداری"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # پارامترهای طلایی FFmpeg برای حذف لگ و رفع صفحه سبز
    # استفاده از libx264 با پروفایل baseline برای سازگاری کامل با موبایل
    # استفاده از opus برای صدا (کدک نیتیو تلگرام)
    ffmpeg_args = (
        "-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-vcodec libx264 -pix_fmt yuv420p -preset ultrafast -tune zerolatency "
        "-profile:v baseline -level 3.0 -maxrate 800k -bufsize 1600k "
        "-acodec libopus -b:a 48k -ac 2 -ar 48000"
    )
    
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=ffmpeg_args
    )

    try: await call_py.leave_group_call(chat_id)
    except: pass
    await asyncio.sleep(1)
    
    # تلاش برای پیوستن به تماس تصویری
    await call_py.join_group_call(chat_id, stream)

# ==========================================
# 👮‍♂️ سیستم امنیتی وحشی (Strict Mode)
# ==========================================
async def security_check(event):
    chat_id = event.chat_id
    if chat_id in ALLOWED_CHATS:
        return True
    
    # طبق دستور شما: حتی ادمین هم اگر مجاز نباشد، فوش و لفت!
    try:
        await event.reply("💢 مرتیکه اسکل! ادمینت غلط کرده منو آورده اینجا. این چت توی لیست سفید من نیست. لفت میدم سیکتیر!")
        await user_client.delete_dialog(chat_id) 
    except Exception as e:
        print(f"Error leaving: {e}")
    return False

# ==========================================
# 🤖 ربات لاگین (Bot API)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    status = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(f"🤖 **استریمر لایو (رفع باگ نهایی)**\nوضعیت: {status}\n\n🔐 لاگین:\n`/phone +98...` | `/code 12345` | `/password ...` ")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    phone = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        res = await user_client.send_code_request(phone)
        login_state.update({'phone': phone, 'hash': res.phone_code_hash})
        await event.reply("✅ کد فرستاده شد. حالا بزن: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ یوزربات متصل شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم رو بزن: `/password ...` ")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    pwd = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(password=pwd)
        await event.reply("✅ لاگین کامل شد.")
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
        except: return await event.reply("❌ یافت نشد.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{chat_id}` مجاز شد.")
    else:
        await event.reply("⚠️ قبلاً مجاز بود.")

@user_client.on(events.NewMessage(pattern=r'(?i)^/del'))
async def del_chat(event):
    if event.sender_id != ADMIN_ID: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 از لیست سفید حذف شد.")

@user_client.on(events.NewMessage(pattern=r'(?i)^/ping'))
async def ping_cmd(event):
    if not await security_check(event): return
    start = time.time()
    info = await get_system_info()
    ping = round((time.time() - start) * 1000)
    await event.reply(f"📶 **وضعیت استریم**\nتأخیر: `{ping}ms`\n{info}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_cmd(event):
    # اول چک کردن امنیت
    if not await security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    status = await event.reply("📡 در حال استقرار استریم فوق پایدار...")
    
    try:
        # استخراج لینک مستقیم
        if url_arg:
            final_url, title = await get_stream_link(url_arg)
        else:
            title = "Iran International Live"

        # شروع پخش (بخش حساس)
        await start_stream_v1(event.chat_id, final_url)
        
        await status.edit(f"🔴 **پخش زنده با موفقیت فعال شد**\n📺 `{title}`\n⚡️ حالت: Ultra Stable (Opus + YUV420p)")
    except Exception as e:
        await status.edit(f"❌ خطا در رندر استریم:\n`{e}`")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_cmd(event):
    if not await security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup()
        await event.reply("⏹ استریم متوقف شد.")
    except: pass

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Stable Streamer Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            if not call_py.active_calls: await call_py.start()
    except: pass
    
    print("🚀 Fixed Live Streamer Started!")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())