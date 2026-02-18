import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
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

DEFAULT_LIVE_URL = "https://fo-live.iraninternational.com/out/v1/ad74279027874747805d7621c5484828/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("LegacyStreamer")

login_state = {}

# ==========================================
# 🔐 مدیریت لیست مجاز (Strict Security)
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
# 🛠 نصب FFmpeg (کد تضمینی شما)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return
    try:
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz", "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except: pass

setup_ffmpeg()

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

async def get_stream_link(url):
    ydl_opts = {
        'format': 'best', 
        'noplaylist': True, 
        'quiet': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live')
    except: return url, "Live Stream"

async def start_stream_v1(chat_id, source):
    """استریم مستقیم بدون بهینه‌سازی اضافی (طبق درخواست)"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # استفاده از تنظیمات مستقیم بدون فلگ‌های اضافی FFmpeg
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p 
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال بسته است!")
        raise e

# ==========================================
# 👮‍♂️ سیستم امنیتی (فقط لیست سفید - وگرنه فحش و لفت)
# ==========================================
async def strict_security_check(event):
    chat_id = event.chat_id
    # چک کردن لیست سفید (حتی برای ادمین اصلی)
    if chat_id in ALLOWED_CHATS:
        return True
    
    # اگر در لیست نبود: فحش و خروج
    try:
        await event.reply("💢 مرتیکه کسکش! این چت توی لیست سفید من نیست. ادمینت غلط کرده منو آورده اینجا. سیکتیر!")
        await user_client.delete_dialog(chat_id) 
    except: pass
    return False

# ==========================================
# 🤖 ربات لاگین (Bot)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    conn = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(f"🤖 **استریمر مستقیم (نسخه فیکس)**\nوضعیت: {conn}\n\n🔐 لاگین:\n`/phone +98...` | `/code 12345` | `/password ...` ")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد فرستاده شد. بزن: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین یوزربات انجام شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...` ")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود کامل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 هندلرهای یوزربات (Userbot)
# ==========================================

# افزودن چت (فقط مالک)
@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?:\s+(.+))?'))
async def add_h(event):
    if event.sender_id != ADMIN_ID: return
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
        await event.reply(f"✅ چت `{chat_id}` مجاز شد.")
    else:
        await event.reply("⚠️ در لیست بود.")

# حذف چت
@user_client.on(events.NewMessage(pattern=r'(?i)^/del'))
async def del_h(event):
    if event.sender_id != ADMIN_ID: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")

# پینگ
@user_client.on(events.NewMessage(pattern=r'(?i)^/ping'))
async def ping_h(event):
    if not await strict_security_check(event): return
    start = time.time()
    info = await get_system_info()
    ping = round((time.time() - start) * 1000)
    await event.reply(f"🚀 **استریمر آنلاین**\n📶 پینگ: `{ping}ms`\n{info}")

# پخش لایو مستقیم
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    # اولویت با امنیت: اگر مجاز نباشد، لفت می‌دهد
    if not await strict_security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    status = await event.reply("📡 در حال اتصال مستقیم به لایو...")

    try:
        if url_arg:
            final_url, title = await get_stream_link(url_arg)
        else:
            title = "Default Live TV"

        await start_stream_v1(event.chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده فعال شد**\n📺 `{title}`\n⚡️ متصل به لینک مستقیم")
    except Exception as e:
        await status.edit(f"❌ خطا در پخش: `{e}`")

# توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if not await strict_security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        gc.collect()
        await event.reply("⏹ قطع شد.")
    except: pass

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Stable Streamer Active"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            if not call_py.active_calls: await call_py.start()
    except: pass
    
    print("🚀 Bot is LIVE!")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())