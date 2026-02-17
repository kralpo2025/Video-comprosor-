import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
import time
import psutil
import re
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Chat
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

# لینک پیش‌فرض (ایران اینترنشنال)
DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UserBotStreamer")

login_state = {}
active_calls_data = {}

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🔐 سیستم لیست سفید (Whitelist)
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE):
        return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            # اطمینان از اینکه ادمین همیشه هست
            if ADMIN_ID not in data:
                data.append(ADMIN_ID)
            return data
    except:
        return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(chat_list, f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg (برای سرورهای خام)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"):
        return

    logger.info("⏳ در حال نصب FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
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
                # افزودن به Path
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except Exception as e:
        logger.error(f"FFmpeg Install Error: {e}")

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

async def get_system_status(client):
    """دریافت پینگ، رم و دیسک"""
    start = time.time()
    await client.get_me()
    end = time.time()
    ping_ms = round((end - start) * 1000)
    
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return (
        f"📊 **وضعیت سرور:**\n\n"
        f"🧠 **رم:** `{mem.percent}%`\n"
        f"💾 **دیسک:** `{disk.percent}%`\n"
        f"📶 **پینگ:** `{ping_ms}ms`"
    )

async def cleanup(chat_id):
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def get_stream_link(url):
    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except:
        return None, None

async def start_stream_engine(chat_id, source):
    """اجرای استریم با تنظیمات بهینه"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, # کیفیت صدا متوسط برای کاهش فشار
        video_parameters=VideoQuality.SD_480p # کیفیت تصویر 480 برای جلوگیری از لگ
    )

    try:
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است! لطفاً اول ویس‌کال را روشن کنید.")
        raise e

# ==========================================
# 🤖 بخش ربات (فقط برای لاگین و راهنما)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    # فقط ادمین در پیوی
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    conn = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    msg = (
        f"👋 **سلام رئیس!**\n\n"
        f"وضعیت یوزربات: {conn}\n\n"
        f"🛠 **راهنمای لاگین (همینجا بزن):**\n"
        f"1️⃣ `/phone +98912...` (ارسال شماره)\n"
        f"2️⃣ `/code 12345` (ارسال کد)\n"
        f"3️⃣ `/password mysuperpass` (اگر تایید دو مرحله‌ای داری)\n\n"
        f"🎮 **دستورات یوزربات (توی گروه/کانال بنویس):**\n\n"
        f"➕ **افزودن به لیست مجاز:**\n"
        f"`/add` یا `افزودن` (در خود گروه)\n"
        f"`/add @username` یا `افزودن لینک` (برای افزودن از راه دور)\n\n"
        f"➖ **حذف از لیست:**\n"
        f"`/del` یا `حذف`\n\n"
        f"📡 **پخش زنده:**\n"
        f"`/live` یا `لایو` (پخش شبکه پیش‌فرض)\n"
        f"`/live Link` یا `لایو لینک` (پخش لینک دلخواه)\n\n"
        f"▶️ **پخش فایل:** ریپلای روی آهنگ/فیلم و ارسال `/play` یا `پخش`\n\n"
        f"❌ **توقف:** `/stop` یا `قطع`\n\n"
        f"📶 **وضعیت:** `/ping` یا `پینگ`"
    )
    await event.reply(msg)

# --- هندلرهای لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("📩 کد ارسال شد! بفرست: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین با موفقیت انجام شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ تایید دو مرحله‌ای داری. بفرست: `/password رمز`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود تکمیل شد!** حالا می‌تونی توی گروه‌ها دستور بدی.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")


# ==========================================
# 👤 دستورات یوزربات (اجرا در گروه/کانال)
# ==========================================

# فیلتر: فقط پیام‌های ادمین (چه خروجی از خودت، چه ورودی از اکانت دومت اگه ادمین باشه)
def is_admin(event):
    return event.sender_id == ADMIN_ID or event.is_private # در حالت Private همیشه چک میشه ولی لاجیک اصلی پایینه

# --- 1. افزودن به لیست (Add) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_chat_handler(event):
    if event.sender_id != ADMIN_ID: return
    
    target_arg = event.pattern_match.group(2)
    target_id = event.chat_id
    chat_name = "این چت"

    if target_arg:
        try:
            entity = await user_client.get_entity(target_arg)
            target_id = entity.id
            chat_name = f"`{target_arg}`"
        except:
            return await event.reply("❌ لینک یا آیدی نامعتبر است.")
    
    if target_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(target_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ {chat_name} به لیست مجاز اضافه شد.")
    else:
        await event.reply(f"⚠️ {chat_name} قبلاً در لیست بود.")

# --- 2. حذف از لیست (Del) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_chat_handler(event):
    if event.sender_id != ADMIN_ID: return
    
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 این چت از لیست سفید حذف شد.")
    else:
        await event.reply("⚠️ اینجا در لیست نبود.")

# --- 3. پینگ و وضعیت (Ping) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_handler(event):
    if event.sender_id != ADMIN_ID: return
    
    # پیام اولیه
    msg = await event.reply("🔄 ...")
    stats = await get_system_status(user_client)
    await msg.edit(stats)

# --- 4. پخش فایل (Play) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_handler(event):
    if event.sender_id != ADMIN_ID: return
    
    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        return await event.reply("⛔️ اینجا مجاز نیست. از دستور `/add` استفاده کن.")

    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ روی یک آهنگ یا فیلم ریپلای کن.")

    await cleanup(chat_id)
    msg = await event.reply("📥 **در حال دانلود فایل...**")

    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        
        if not path:
            return await msg.edit("❌ دانلود ناموفق بود.")

        active_calls_data[chat_id] = {"path": path, "type": "file"}
        
        await msg.edit("🚀 **در حال اتصال به ویس‌کال...**")
        await start_stream_engine(chat_id, path)
        await msg.edit("▶️ **پخش فایل شروع شد!**")

    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

# --- 5. پخش زنده (Live) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_handler(event):
    if event.sender_id != ADMIN_ID: return

    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        return await event.reply("⛔️ اینجا مجاز نیست. از دستور `/add` استفاده کن.")

    input_url = event.pattern_match.group(2)
    
    # تعیین لینک
    if input_url:
        target_url = input_url.strip()
        display_name = "لینک درخواستی"
    else:
        target_url = DEFAULT_LIVE_URL
        display_name = "ایران اینترنشنال"

    await cleanup(chat_id)
    msg = await event.reply(f"📡 **در حال پردازش {display_name}...**")

    try:
        # اگر لینک مستقیم نیست، سعی کن لینک اصلی رو پیدا کنی (مگر اینکه دیفالت باشه)
        final_url = target_url
        if target_url != DEFAULT_LIVE_URL:
            extracted_url, title = await get_stream_link(target_url)
            if extracted_url:
                final_url = extracted_url
                display_name = title

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        
        await start_stream_engine(chat_id, final_url)
        await msg.edit(f"🔴 **پخش زنده شروع شد:**\n📺 `{display_name}`")

    except Exception as e:
        await msg.edit(f"❌ خطا در پخش زنده: {e}")

# --- 6. توقف (Stop) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_handler(event):
    if event.sender_id != ADMIN_ID: return
    
    chat_id = event.chat_id
    if chat_id in active_calls_data or chat_id in ALLOWED_CHATS:
        try:
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.reply("⏹ **پخش متوقف شد.**")
        except Exception as e:
            await event.reply(f"⚠️ {e}")
    else:
        await event.reply("⚠️ پخشی در جریان نیست.")

# ==========================================
# 🌐 ران کردن وب‌سرور و کلاینت‌ها
# ==========================================
async def main():
    # وب سرور برای زنده نگه داشتن در پلتفرم‌های ابری
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot & Userbot Running..."))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("Starting Clients...")
    
    # استارت ربات (مدیریت لاگین)
    await bot.start(bot_token=BOT_TOKEN)
    
    # استارت یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("Userbot Authorized. Starting PyTgCalls...")
            await call_py.start()
        else:
            logger.warning("Userbot NOT authorized. Use Bot to login.")
    except Exception as e:
        logger.error(f"UserClient Error: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())