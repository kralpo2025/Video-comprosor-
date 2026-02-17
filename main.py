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
import sys
from aiohttp import web
from telethon import TelegramClient, events, functions, types
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
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

# لینک پیش‌فرض (شبکه خبری با کیفیت پایین برای تست)
DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
# دریافت پورت از محیط یا استفاده از پیش‌فرض (سازگار با پایتون 3.9)
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("StreamerBot")

login_state = {}
active_calls_data = {}

# ==========================================
# 🧹 پاکسازی حافظه (Memory & Disk Cleanup)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)
else:
    # پاکسازی فایل‌های باقی‌مانده از قبل
    for f in os.listdir(DOWNLOAD_DIR):
        try: os.remove(os.path.join(DOWNLOAD_DIR, f))
        except: pass

async def force_cleanup(chat_id):
    """
    این تابع فایل‌های دانلود شده را حذف کرده و رم را تخلیه می‌کند.
    """
    try:
        if chat_id in active_calls_data:
            data = active_calls_data[chat_id]
            path = data.get("path")
            
            # حذف فایل فیزیکی
            if data.get("type") == "file" and path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"Deleted file: {path}")
                except Exception as e:
                    logger.error(f"File delete error: {e}")
            
            # حذف از دیکشنری
            del active_calls_data[chat_id]
        
        # فورس کردن زباله‌روب پایتون (Garbage Collector)
        gc.collect()
        
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# ==========================================
# 🔐 مدیریت لیست مجاز (Whitelist)
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
# 🛠 نصب خودکار FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    # اگر ffmpeg نصب باشد، کاری نکن
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Downloading FFmpeg...")
    try:
        # حذف فایل‌های ناقص قبلی
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        wget.download(url, "ffmpeg.tar.xz")
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                source = os.path.join(root, "ffmpeg")
                dest = os.path.join(cwd, "ffmpeg")
                if not os.path.exists(dest):
                    shutil.move(source, dest)
                os.chmod(dest, 0o755)
                # اضافه کردن به PATH برای پایتون 3.9
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except Exception as e:
        logger.error(f"FFmpeg setup failed: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 راه‌اندازی کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================
async def get_system_info():
    """دریافت وضعیت سرور"""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%"

async def get_stream_link(url):
    """
    استخراج لینک پخش با کمترین کیفیت ممکن (Worst) برای کاهش پینگ
    """
    ydl_opts = {
        'format': 'worst',  # مهم: بدترین کیفیت برای سرعت بالا
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True,
        # جلوگیری از دانلود، فقط لینک
        'forceurl': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live')
    except Exception as e:
        logger.error(f"YTDLP Error: {e}")
        return None, None

async def start_stream_optimized(chat_id, source):
    """شروع استریم با تنظیمات فوق‌العاده سبک"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # پارامترهای FFmpeg برای کاهش فشار روی CPU
    # ultrafast: سریع‌ترین انکود (کمترین مصرف CPU)
    # crf 32: کیفیت پایین (بیت‌ریت کم = پینگ بهتر)
    ffmpeg_options = (
        "-preset ultrafast "
        "-tune zerolatency "
        "-crf 32 "
        "-fps_mode passthrough"
    )

    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.LOW,  # صدای کم‌حجم
        video_parameters=VideoQuality.LD_360p, # تصویر 360p (سبک)
        ffmpeg_parameters=ffmpeg_options
    )

    try:
        # اگر قبلاً در کال بود، خارج شو
        try: await call_py.leave_group_call(chat_id)
        except: pass
        
        await asyncio.sleep(0.5)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ **ویس‌کال خاموش است!**\nلطفاً Video Chat را در گروه/کانال روشن کنید.")
        raise e

# ==========================================
# 👮‍♂️ سیستم احراز هویت (ادمین‌ها + مالک)
# ==========================================
async def check_permission(event):
    """
    بررسی دسترسی:
    1. مالک اصلی (ADMIN_ID)
    2. خود یوزربات (پیام‌های خروجی)
    3. ادمین‌های گروه/کانال
    """
    # 1. مالک اصلی و پیام‌های خود یوزربات همیشه مجاز هستند
    if event.sender_id == ADMIN_ID or event.out:
        return True

    # در چت خصوصی، فقط ادمین اصلی مجاز است
    if event.is_private:
        return False

    # 2. بررسی لیست مجاز بودن چت
    if event.chat_id not in ALLOWED_CHATS:
        return False

    # 3. بررسی ادمین بودن کاربر در گروه/کانال
    try:
        perms = await user_client.get_permissions(event.chat_id, event.sender_id)
        if perms and (perms.is_admin or perms.is_creator):
            return True
    except:
        pass
        
    return False

# ==========================================
# 🤖 ربات (مدیریت لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    conn = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    await event.reply(
        f"🤖 **کنترل پنل استریمر**\n"
        f"وضعیت یوزربات: {conn}\n\n"
        f"🔐 **لاگین:** `/phone`, `/code`, `/password`\n"
        f"📡 **دستورات (در گروه/کانال):**\n"
        f"✅ `/add` (افزودن چت)\n"
        f"▶️ `/live` یا `لایو`\n"
        f"▶️ `/play` یا `پخش`\n"
        f"⏹ `/stop` یا `قطع`"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد را بفرستید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین موفقیت آمیز بود!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ تایید دو مرحله‌ای: `/password رمز`")
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
# 👤 دستورات یوزربات (اجرا در چت‌ها)
# ==========================================

# --- 1. افزودن به لیست (Add) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_chat_handler(event):
    # فقط ادمین اصلی یا خود یوزربات می‌تواند چت اضافه کند (برای امنیت)
    if event.sender_id != ADMIN_ID and not event.out: return
    
    target_arg = event.pattern_match.group(2)
    target_id = event.chat_id
    
    if target_arg:
        try:
            entity = await user_client.get_entity(target_arg)
            target_id = entity.id
        except: return await event.reply("❌ لینک نامعتبر.")
    
    if target_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(target_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{target_id}` مجاز شد.")
    else:
        await event.reply("⚠️ قبلاً مجاز شده بود.")

# --- 2. حذف از لیست (Del) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_chat_handler(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")

# --- 3. پینگ و وضعیت (Ping) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_handler(event):
    if not await check_permission(event): return
    
    start = time.time()
    msg = await event.reply("🔄")
    await user_client.get_me()
    ping_ms = round((time.time() - start) * 1000)
    sys_stats = await get_system_info()
    
    await msg.edit(f"📶 **Ping:** `{ping_ms}ms` (Optimized)\n{sys_stats}")

# --- 4. پخش فایل (Play) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_handler(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    reply = await event.get_reply_message()
    
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ لطفاً روی آهنگ یا ویدیو ریپلای کنید.")

    # اول پاکسازی کن که رم خالی باشه
    await force_cleanup(chat_id)
    
    status = await event.reply("📥 **در حال دانلود سبک...**")
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        
        if not path: return await status.edit("❌ دانلود نشد.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        await status.edit("🚀 **اتصال به ویس‌کال...**")
        
        await start_stream_optimized(chat_id, path)
        await status.edit("▶️ **پخش فایل شروع شد.**")

    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# --- 5. پخش زنده (Live) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_handler(event):
    if not await check_permission(event): return

    chat_id = event.chat_id
    
    # 🛡 حذف پیام حاوی لینک (برای امنیت و جلوگیری از کپی شدن لینک توسط اعضا)
    try: await event.delete()
    except: pass

    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    display_name = "ایران اینترنشنال"

    await force_cleanup(chat_id)
    status = await user_client.send_message(chat_id, "📡 **دریافت لینک...**")

    try:
        if url_arg:
            extracted_url, title = await get_stream_link(url_arg)
            if extracted_url:
                final_url = extracted_url
                display_name = title or "استریم زنده"
            else:
                final_url = url_arg
                display_name = "لینک مستقیم"

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        
        await start_stream_optimized(chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده فعال شد:**\n📺 `{display_name}`\n⚡️ حالت: Low Latency (ضد لگ)")

    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# --- 6. توقف (Stop) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_handler(event):
    if not await check_permission(event): return
    
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup(event.chat_id)
        await event.reply("⏹ **پخش متوقف و حافظه پاکسازی شد.**")
    except: pass

# --- پایان خودکار استریم ---
@call_py.on_stream_end()
async def on_stream_end(client, update):
    try: await client.leave_group_call(update.chat_id)
    except: pass
    await force_cleanup(update.chat_id)

# ==========================================
# 🌐 اجرای برنامه (Asyncio Loop)
# ==========================================
async def main():
    # وب سرور برای جلوگیری از اسلیپ شدن در پلتفرم‌های ابری
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is Running (Python 3.9)"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("🚀 Starting Clients...")
    await bot.start(bot_token=BOT_TOKEN)
    
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            await call_py.start()
    except Exception as e:
        logger.error(f"Client connection error: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    # روش استاندارد اجرای Asyncio در پایتون 3.9
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass