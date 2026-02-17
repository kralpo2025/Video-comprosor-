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
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality
import yt_dlp

# ==========================================
# ⚙️ تنظیمات اصلی (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

# لینک پیش‌فرض (ایران اینترنشنال)
DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

# تنظیمات لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("StreamerBot")

# متغیرهای حافظه
login_state = {}
active_calls_data = {}

# ==========================================
# 🧹 سیستم پاکسازی پیشرفته (Memory & Disk)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)
else:
    # پاکسازی فایل‌های قدیمی هنگام شروع مجدد
    for f in os.listdir(DOWNLOAD_DIR):
        try: os.remove(os.path.join(DOWNLOAD_DIR, f))
        except: pass

async def force_cleanup(chat_id):
    """پاکسازی تهاجمی رم و دیسک برای جلوگیری از پر شدن حافظه"""
    try:
        if chat_id in active_calls_data:
            data = active_calls_data[chat_id]
            path = data.get("path")
            
            # 1. حذف فایل فیزیکی
            if data.get("type") == "file" and path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"🗑 فایل حذف شد: {path}")
                except Exception as e:
                    logger.error(f"خطا در حذف فایل: {e}")
            
            # 2. حذف از حافظه برنامه
            del active_calls_data[chat_id]
        
        # 3. اجرای زباله‌روب پایتون (Garbage Collector)
        n = gc.collect()
        logger.info(f"🧹 حافظه پاکسازی شد: {n} آبجکت حذف شدند.")
        
    except Exception as e:
        logger.error(f"Cleanup Error: {e}")

# ==========================================
# 🔐 مدیریت لیست سفید
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE):
        return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            if ADMIN_ID not in data: data.append(ADMIN_ID)
            return data
    except:
        return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(chat_list, f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except Exception as e: logger.error(f"FFmpeg Error: {e}")

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
    ydl_opts = {'format': 'best', 'noplaylist': True, 'quiet': True, 'geo_bypass': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except: return None, None

async def start_stream(chat_id, source):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت متوسط برای جلوگیری از فشار به سرور
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1) # وقفه کوتاه برای اطمینان
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ **ویس‌کال خاموش است!**\nلطفا ابتدا در این کانال/گروه ویس‌کال را روشن کنید.")
        raise e

# ==========================================
# 🤖 بخش ربات (Bot API) - فقط لاگین
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    status = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(
        f"👋 **پنل مدیریت ربات**\nوضعیت یوزربات: {status}\n\n"
        f"🔐 **لاگین:** `/phone شماره` | `/code کد` | `/password رمز`\n"
        f"📝 **دستورات (در کانال/گروه):**\n"
        f"🔹 `/add` یا `افزودن` (فعالسازی چت)\n"
        f"🔹 `/live` یا `لایو` (پخش زنده)\n"
        f"🔹 `/play` یا `پخش` (ریپلای روی مدیا)\n"
        f"🔹 `/stop` یا `قطع`\n"
        f"🔹 `/ping` یا `پینگ`"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def login_phone(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد ارسال شد. بفرست: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def login_code(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین موفق!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ تایید دو مرحله‌ای: `/password رمز`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def login_pass(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود کامل شد.**")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 👤 بخش یوزربات (Userbot) - کانال و گروه
# ==========================================

# چک کردن اینکه پیام از طرف ادمین هست یا خیر
# نکته مهم: در کانال، پیام‌های ارسالی توسط ادمین outgoing=True هستند.
def is_authorized(event):
    # 1. اگر پیام خروجی بود (یعنی یوزربات فرستاده) -> مجاز
    if event.out:
        return True
    # 2. اگر پیام ورودی بود (در گروه) و فرستنده ادمین بود -> مجاز
    if event.sender_id == ADMIN_ID:
        return True
    return False

# --- 1. افزودن (Add) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_handler(event):
    if not is_authorized(event): return
    
    target = event.pattern_match.group(2)
    chat_id = event.chat_id
    
    if target:
        try:
            entity = await user_client.get_entity(target)
            chat_id = entity.id
        except: return await event.reply("❌ لینک نامعتبر.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{chat_id}` مجاز شد.")
    else:
        await event.reply("⚠️ قبلاً مجاز شده بود.")

# --- 2. حذف (Del) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_handler(event):
    if not is_authorized(event): return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")
    else:
        await event.reply("⚠️ در لیست نبود.")

# --- 3. پینگ (Ping) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_handler(event):
    if not is_authorized(event): return
    start = time.time()
    msg = await event.reply("🔄 ...")
    await user_client.get_me()
    ping = round((time.time() - start) * 1000)
    sys_info = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n{sys_info}")

# --- 4. پخش فایل (Play) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_handler(event):
    if not is_authorized(event): return
    
    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        return await event.reply("⛔️ غیرمجاز. دستور `/add` را بزنید.")

    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ روی فایل ریپلای کنید.")

    # پاکسازی قبلی
    await force_cleanup(chat_id)
    
    status = await event.reply("📥 **دانلود...**")
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        if not path: return await status.edit("❌ خطا در دانلود.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        await status.edit("🚀 **اتصال...**")
        
        await start_stream(chat_id, path)
        await status.edit("▶️ **پخش شروع شد.**")
        
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# --- 5. پخش زنده (Live) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_handler(event):
    if not is_authorized(event): return

    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        return await event.reply("⛔️ غیرمجاز. دستور `/add` را بزنید.")

    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    title = "ایران اینترنشنال"

    # پاکسازی قبلی
    await force_cleanup(chat_id)
    status = await event.reply("📡 **دریافت لینک...**")

    try:
        if url_arg:
            u, t = await get_stream_link(url_arg)
            if u:
                final_url = u
                title = t or "Live"
            else:
                final_url = url_arg # شاید لینک مستقیم باشه
                title = "لینک مستقیم"

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        
        await start_stream(chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده:**\n📺 `{title}`")

    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# --- 6. توقف (Stop) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_handler(event):
    if not is_authorized(event): return
    
    chat_id = event.chat_id
    try:
        await call_py.leave_group_call(chat_id)
        await force_cleanup(chat_id)
        await event.reply("⏹ **قطع شد و حافظه پاکسازی گردید.**")
    except Exception as e:
        await event.reply(f"⚠️ {e}")

# --- ایونت پایان خودکار ---
@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    logger.info(f"Stream ended for {chat_id}")
    try: await client.leave_group_call(chat_id)
    except: pass
    await force_cleanup(chat_id)

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    # وب‌سرور (جهت جلوگیری از اسلیپ شدن در پلتفرم‌ها)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is Running High Performance!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    logger.info("🚀 Starting...")
    await bot.start(bot_token=BOT_TOKEN)
    
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            await call_py.start()
            # ارسال پیام به Saved Messages برای اطمینان از روشن شدن
            try: await user_client.send_message('me', "✅ **ربات موزیک با موفقیت روشن شد!**")
            except: pass
    except Exception as e:
        logger.error(f"Error: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())