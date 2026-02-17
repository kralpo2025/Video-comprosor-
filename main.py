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
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError

# کتابخانه‌های پخش (نسخه پایدار 2.2.10)
from pytgcalls import PyTgCalls
from pytgcalls import StreamType
from pytgcalls.types.input_stream import AudioVideoPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio, LowQualityVideo

import yt_dlp

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraBot")

login_state = {}
active_calls_data = {}

# ==========================================
# 🛠 مدیریت فایل و حافظه
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

async def force_cleanup(chat_id):
    """پاکسازی قدرتمند برای جلوگیری از پر شدن حافظه"""
    try:
        if chat_id in active_calls_data:
            data = active_calls_data[chat_id]
            path = data.get("path")
            
            if data.get("type") == "file" and path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"Deleted: {path}")
                except: pass
            
            del active_calls_data[chat_id]
        
        # اجبار سیستم به آزادسازی رم
        gc.collect()
    except: pass

# ==========================================
# 🔐 لیست مجاز
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
# 🛠 نصب FFmpeg (حیاتی برای Render)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Installing FFmpeg...")
    try:
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz", "ffmpeg.tar.xz")
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except Exception as e:
        logger.error(f"FFmpeg Error: {e}")

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
    try:
        import cryptg
        speed = "🚀 Ultra (Cryptg ON)"
    except:
        speed = "⚠️ Normal"
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n⚡️ {speed}"

async def get_stream_link(url):
    # دریافت بهترین فرمت ممکن اما سبک (480p یا کمتر)
    ydl_opts = {
        'format': 'best[height<=480]', 
        'noplaylist': True, 
        'quiet': True, 
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live')
    except: return None, None

async def start_stream_engine(chat_id, source):
    """موتور پخش بهینه شده"""
    
    # تنظیمات: صدای با کیفیت بالا، تصویر با کیفیت پایین (برای جلوگیری از لگ)
    stream = AudioVideoPiped(
        source,
        HighQualityAudio(),
        LowQualityVideo()
    )

    try:
        await call_py.join_group_call(
            chat_id,
            stream,
            stream_type=StreamType().pulse_stream
        )
    except Exception as e:
        # اگر خطا داد (مثلاً قبلاً وصل بود)، ریکانکت کن
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(2)
            await call_py.join_group_call(
                chat_id,
                stream,
                stream_type=StreamType().pulse_stream
            )
        except Exception as inner_e:
            if "no group call" in str(inner_e).lower():
                raise Exception("⚠️ **ویس‌کال خاموش است!** لطفاً روشن کنید.")
            raise inner_e

# ==========================================
# 👮‍♂️ دسترسی‌ها
# ==========================================
async def check_permission(event):
    # 1. مالک اصلی و پیام‌های خروجی (یوزربات در کانال)
    if event.sender_id == ADMIN_ID or event.out:
        return True
    
    if event.is_private: return False
    if event.chat_id not in ALLOWED_CHATS: return False

    # 2. ادمین‌های کانال/گروه
    try:
        p = await user_client.get_permissions(event.chat_id, event.sender_id)
        if p.is_admin or p.is_creator:
            return True
    except: pass
    return False

# ==========================================
# 🤖 ربات لاگین
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    conn = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(f"🤖 **ربات نسخه نهایی**\nوضعیت: {conn}\n\n🔐 لاگین: `/phone`, `/code`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد: `/code 12345`")
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

# 1. افزودن
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target = event.pattern_match.group(2)
    chat_id = event.chat_id
    if target:
        try:
            entity = await user_client.get_entity(target)
            chat_id = entity.id
        except: return await event.reply("❌ نامعتبر.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت {chat_id} مجاز شد.")
    else:
        await event.reply("⚠️ قبلاً بود.")

# 2. حذف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")

# 3. پینگ
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_h(event):
    if not await check_permission(event): return
    start = time.time()
    msg = await event.reply("⏳")
    await user_client.get_me()
    ping = round((time.time() - start) * 1000)
    info = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n{info}")

# 4. پخش فایل (با پشتیبانی از فایل‌های حجیم)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_h(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ ریپلای کن.")

    await force_cleanup(chat_id)
    status = await event.reply("📥 **در حال دانلود فایل...**\n(برای فایل‌های طولانی صبر کنید)")
    
    try:
        # دانلود فایل در مسیر مشخص
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        
        if not path: return await status.edit("❌ دانلود نشد.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        await status.edit("🚀 **اتصال به ویس‌کال...**")
        
        await start_stream_engine(chat_id, path)
        await status.edit("▶️ **پخش شروع شد.**")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 5. پخش لایو (هوشمند)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    if not await check_permission(event): return
    try: await event.delete()
    except: pass

    chat_id = event.chat_id
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    title = "Live Stream"

    await force_cleanup(chat_id)
    status = await user_client.send_message(chat_id, "📡 **دریافت لینک...**")

    try:
        if url_arg:
            u, t = await get_stream_link(url_arg)
            if u:
                final_url = u
                title = t or "Stream"
            else:
                final_url = url_arg

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        await start_stream_engine(chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده:**\n📺 `{title}`\n⚡️ کیفیت: بهینه")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 6. توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if not await check_permission(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup(event.chat_id)
        await event.reply("⏹ قطع شد.")
    except: pass

@call_py.on_stream_end()
async def on_end(handler, update):
    try: await call_py.leave_group_call(update.chat_id)
    except: pass
    await force_cleanup(update.chat_id)

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Running (Final Fixed)"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("🚀 Starting...")
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): await call_py.start()
    except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())