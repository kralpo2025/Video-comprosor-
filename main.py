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
from telethon import TelegramClient, events, functions
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel

# کتابخانه‌های نسخه 1.2.9
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

import yt_dlp

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
API_ID = int(os.environ.get("API_ID", 27868969))
API_HASH = os.environ.get("API_HASH", "bdd2e8fccf95c9d7f3beeeff045f8df4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 7419222963))

# لینک پیش‌فرض (ایران اینترنشنال یا هر لینک m3u8 دیگر)
DEFAULT_LIVE_URL = "https://live.iranintl.com/hls/live.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("LiveStreamerOnly")

login_state = {}

# ==========================================
# 🔐 لیست مجاز (Database)
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            if ADMIN_ID not in data: data.append(ADMIN_ID)
            return data
    except: return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(chat_list, f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg (مخصوص Render)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Downloading FFmpeg...")
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
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%"

async def get_stream_link(url):
    # تنظیمات اختصاصی برای لایو بدون لگ
    ydl_opts = {
        'format': 'best[height<=480]', # کیفیت 480 برای جلوگیری از بافرینگ
        'noplaylist': True, 
        'quiet': True, 
        'geo_bypass': True,
        'live_from_start': True,
        'hls_prefer_native': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live TV')
    except: return url, "Custom Stream" # اگر نتوانست استخراج کند، خود لینک را برمی‌گرداند

async def start_live_stream(chat_id, stream_url):
    """
    موتور پخش فقط مخصوص لایو
    """
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات حیاتی FFmpeg برای پخش زنده بدون تأخیر
    # -preset ultrafast: کمترین فشار روی CPU
    # -tune zerolatency: حذف بافر برای پخش زنده
    ffmpeg_params = "-preset ultrafast -tune zerolatency -fflags nobuffer"

    stream = MediaStream(
        stream_url,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است!")
        raise e

# ==========================================
# 👮‍♂️ سیستم امنیتی (Check Permission)
# ==========================================
async def is_allowed(event):
    chat_id = event.chat_id
    
    # لیست سفید را چک کن
    if chat_id in ALLOWED_CHATS:
        return True
    
    # هندل کردن آیدی‌های -100
    simple_id = int(str(chat_id).replace("-100", ""))
    if simple_id in ALLOWED_CHATS:
        return True

    # اگر کانال است و ادمین پیام داده (چون در کانال فقط ادمین پیام می‌دهد)
    if event.is_channel and not event.is_group:
        # اما باز هم باید در لیست باشد، اگر نیست یعنی اجازه ندارد
        return False

    return False

# ==========================================
# 🤖 ربات لاگین (مدیریت)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    conn = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    text = (
        f"📺 **ربات پخش زنده (نسخه لایت)**\n"
        f"وضعیت: {conn}\n\n"
        f"دستورات:\n"
        f"1. `/live` - پخش لینک پیش‌فرض\n"
        f"2. `/live [link]` - پخش لینک دلخواه\n"
        f"3. `/add` - افزودن گروه/کانال\n"
        f"4. `/del` - حذف گروه/کانال\n"
        f"5. `/stop` - قطع پخش\n\n"
        f"🔐 **لاگین:** `/phone`, `/code`, `/password`"
    )
    await event.reply(text)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد ارسال شد: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 هندلرها (Userbot)
# ==========================================

# 1. افزودن (فقط ادمین اصلی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    
    target_id = event.chat_id
    arg = event.pattern_match.group(2)
    
    if arg:
        try:
            if "joinchat" in arg:
                await event.reply("⚠️ برای لینک خصوصی، اول باید جوین بشم. خودت دستی جوین شو بعد دستور رو بزن.")
                return
            entity = await user_client.get_entity(arg)
            target_id = entity.id
        except:
            return await event.reply("❌ آیدی نامعتبر.")

    if target_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(target_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ **اینجا ({target_id}) مجاز شد.**")
    else:
        await event.reply("⚠️ قبلاً مجاز بود.")

# 2. حذف (فقط ادمین اصلی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 **حذف شد.**")
    else:
        await event.reply("⚠️ اینجا مجاز نبود.")

# 3. پخش لایو (هسته اصلی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    chat_id = event.chat_id

    # --- بررسی امنیتی (Rude Mode) ---
    if chat_id not in ALLOWED_CHATS:
        # اگر در لیست نبود (حتی اگه ادمین زده باشه)
        try:
            await event.reply("🖕 **گمشو بابا! این خراب شده مجاز نیست. من رفتم!** 👋")
            await user_client.delete_dialog(chat_id) # لفت دادن و پاک کردن چت
        except: pass
        return
    # --------------------------------

    try: await event.delete()
    except: pass

    url_arg = event.pattern_match.group(2)
    status = await user_client.send_message(chat_id, "📡 **در حال اتصال...**")

    try:
        if url_arg:
            # اگر کاربر لینک داده
            final_url, title = await get_stream_link(url_arg)
        else:
            # اگر لینک نداده (لینک پیش‌فرض)
            final_url = DEFAULT_LIVE_URL
            title = "Default TV"

        await start_live_stream(chat_id, final_url)
        
        await status.edit(
            f"🔴 **پخش زنده شروع شد!**\n\n"
            f"📺 **شبکه:** `{title}`\n"
            f"⚡️ **حالت:** بدون تأخیر (Zero Latency)\n"
            f"🛡 **سرور:** Render High Speed"
        )
        
    except Exception as e:
        await status.edit(f"❌ **خطا:** {e}")

# 4. توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if event.chat_id not in ALLOWED_CHATS: return
    try:
        await call_py.leave_group_call(event.chat_id)
        await event.reply("⏹ **پخش قطع شد.**")
        gc.collect() # آزادسازی رم
    except: pass

# 5. پینگ
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_h(event):
    if event.chat_id not in ALLOWED_CHATS: return
    start = time.time()
    msg = await event.reply("⏳")
    ping = round((time.time() - start) * 1000)
    sys = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n{sys}")

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Live Bot is Running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("🚀 Bot Started (Live Mode Only)")
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): await call_py.start()
    except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())