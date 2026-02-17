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
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import ChannelParticipantsAdmins, Channel

# کتابخانه‌های استریم (نسخه پایدار 2.2.10)
from pytgcalls import PyTgCalls
from pytgcalls import StreamType
from pytgcalls.types.input_stream import AudioVideoPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio, LowQualityVideo, MediumQualityVideo

import yt_dlp

# ==========================================
# ⚙️ تنظیمات اصلی (Configuration)
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

# تنظیمات لاگ (با جزئیات دقیق)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraStreamer")

# حافظه موقت
login_state = {}
active_calls_data = {}

# ==========================================
# 🛠 سیستم مدیریت فایل و حافظه (Cleanup Manager)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

async def initial_cleanup():
    """پاکسازی فایل‌های به جا مانده هنگام استارت ربات"""
    logger.info("Performing initial cleanup...")
    for f in os.listdir(DOWNLOAD_DIR):
        try:
            os.remove(os.path.join(DOWNLOAD_DIR, f))
        except: pass

async def force_cleanup(chat_id):
    """
    پاکسازی هوشمند:
    1. حذف فایل مربوط به چت خاص
    2. حذف داده‌ها از دیکشنری
    3. اجرای Garbage Collector برای آزادسازی رم
    """
    try:
        if chat_id in active_calls_data:
            data = active_calls_data[chat_id]
            path = data.get("path")
            
            # اگر فایل فیزیکی وجود دارد پاک کن
            if data.get("type") == "file" and path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"🗑 File deleted for chat {chat_id}: {path}")
                except Exception as e:
                    logger.error(f"Failed to delete file: {e}")
            
            # حذف از حافظه برنامه
            del active_calls_data[chat_id]
        
        # پاکسازی رم (بسیار مهم برای سرورهای ضعیف)
        collected = gc.collect()
        logger.info(f"🧹 Garbage Collector: Freed {collected} objects.")
        
    except Exception as e:
        logger.error(f"Cleanup Critical Error: {e}")

# ==========================================
# 🔐 مدیریت لیست سفید (Access Control)
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
# 🛠 نصب‌کننده خودکار FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"):
        logger.info("✅ FFmpeg is already installed.")
        return

    logger.info("⏳ FFmpeg not found. Downloading...")
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
        logger.info("✅ FFmpeg installed successfully.")
    except Exception as e:
        logger.error(f"❌ FFmpeg installation failed: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 راه‌اندازی کلاینت‌ها (Clients Setup)
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع سیستم و لینک (Utilities)
# ==========================================
async def get_system_info():
    """دریافت اطلاعات دقیق سرور"""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # بررسی فعال بودن Cryptg
    try:
        import cryptg
        speed_mode = "🚀 Ultra Speed (Cryptg ON)"
    except:
        speed_mode = "⚠️ Normal Speed (Cryptg OFF)"

    return (
        f"📊 **System Status:**\n\n"
        f"🧠 **RAM:** `{mem.percent}%` (Used)\n"
        f"💾 **Disk:** `{disk.percent}%` (Used)\n"
        f"⚡️ **Mode:** `{speed_mode}`"
    )

async def get_stream_link(url):
    """
    استخراج لینک هوشمند:
    اگر لایو باشد، کیفیت مناسب را انتخاب می‌کند.
    """
    # تنظیمات yt-dlp برای دریافت لینکی که لگ نزند
    ydl_opts = {
        'format': 'best[height<=480]', # کیفیت 480 یا کمتر (تعادل بین کیفیت و سرعت)
        'noplaylist': True, 
        'quiet': True, 
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"YTDLP Extraction Error: {e}")
        return None, None

# ==========================================
# 🎧 موتور استریم (Stream Engine)
# ==========================================
async def start_stream_engine(chat_id, source, is_live=False):
    """
    موتور اصلی پخش با قابلیت مدیریت بافر و فایل‌های طولانی
    """
    
    # اگر لایو باشد، تنظیمات ویدیو را کاهش می‌دهیم تا لگ نزند
    # اگر فایل باشد، کیفیت صدا را بالا می‌بریم
    if is_live:
        video_quality = LowQualityVideo() # ویدیو سبک برای لایو
        audio_quality = HighQualityAudio()
    else:
        video_quality = LowQualityVideo() # ویدیو سبک برای فایل (برای جلوگیری از هنگ)
        audio_quality = HighQualityAudio() # صدای عالی برای موزیک

    # ساخت استریم پایپ
    stream = AudioVideoPiped(
        source,
        audio_quality,
        video_quality
    )

    try:
        # تلاش برای جوین شدن
        await call_py.join_group_call(
            chat_id,
            stream,
            stream_type=StreamType().pulse_stream # حالت Pulse پایدارتر است
        )
    except Exception as e:
        # اگر ارور داد (مثلاً قبلاً جوین بود)، اول خارج می‌شویم و دوباره وصل می‌شویم
        logger.warning(f"Join failed ({e}), retrying with Re-Join strategy...")
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1.5) # مکث برای اطمینان از خروج کامل
            await call_py.join_group_call(
                chat_id,
                stream,
                stream_type=StreamType().pulse_stream
            )
        except Exception as inner_e:
            if "no group call" in str(inner_e).lower():
                raise Exception("⚠️ **ویس‌کال خاموش است!**\nلطفاً Video Chat را در گروه/کانال روشن کنید.")
            raise inner_e

# ==========================================
# 👮‍♂️ سیستم بررسی دسترسی (Permission System)
# ==========================================
async def check_permission(event):
    """
    بررسی دقیق دسترسی برای گروه‌ها و کانال‌ها
    """
    # 1. مالک اصلی همیشه دسترسی دارد
    if event.sender_id == ADMIN_ID:
        return True
    
    # 2. اگر پیام خروجی (Outgoing) باشد (یعنی خود یوزربات در کانال/گروه فرستاده)
    if event.out:
        return True

    # 3. در چت خصوصی فقط مالک
    if event.is_private:
        return False

    # 4. بررسی لیست سفید
    if event.chat_id not in ALLOWED_CHATS:
        return False

    # 5. بررسی ادمین‌های دیگر در کانال/گروه
    try:
        # گرفتن سطح دسترسی فردی که دستور داده
        perm = await user_client.get_permissions(event.chat_id, event.sender_id)
        if perm.is_admin or perm.is_creator:
            return True
    except Exception as e:
        logger.warning(f"Permission check failed: {e}")
        pass
        
    return False

# ==========================================
# 🤖 بخش ربات (Bot API) - مدیریت
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    # بررسی اتصال یوزربات
    try:
        await user_client.connect()
        is_auth = await user_client.is_user_authorized()
    except: is_auth = False
    
    conn_status = "✅ متصل و آماده" if is_auth else "❌ نیاز به لاگین"
    
    await event.reply(
        f"🤖 **کنترل پنل استریمر Ultra**\n"
        f"وضعیت یوزربات: {conn_status}\n\n"
        f"🔐 **مدیریت اکانت:**\n"
        f"1️⃣ `/phone +98...`\n"
        f"2️⃣ `/code 12345`\n"
        f"3️⃣ `/password ...`\n\n"
        f"📡 **دستورات (قابل اجرا در گروه/کانال):**\n"
        f"➕ `/add` (افزودن چت)\n"
        f"➖ `/del` (حذف چت)\n"
        f"▶️ `/play` یا `پخش` (فایل)\n"
        f"🔴 `/live` یا `لایو` (زنده)\n"
        f"⏹ `/stop` یا `قطع`\n"
        f"📶 `/ping` یا `پینگ`"
    )

# --- هندلرهای لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد ارسال شد. بزن: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین با موفقیت انجام شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ تایید دو مرحله‌ای: `/password رمز`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 👤 بخش یوزربات (Userbot) - دستورات اصلی
# ==========================================

# --- 1. افزودن به لیست (Add) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_chat_handler(event):
    # فقط مالک یا پیام خروجی مجاز است (برای امنیت)
    if event.sender_id != ADMIN_ID and not event.out: return
    
    target_arg = event.pattern_match.group(2)
    target_id = event.chat_id
    
    if target_arg:
        try:
            entity = await user_client.get_entity(target_arg)
            target_id = entity.id
        except: return await event.reply("❌ آیدی/لینک نامعتبر.")
    
    if target_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(target_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{target_id}` به لیست مجاز اضافه شد.")
    else:
        await event.reply("⚠️ این چت قبلاً اضافه شده بود.")

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
    # بررسی دسترسی (همه ادمین‌ها)
    if not await check_permission(event): return
    
    start = time.time()
    msg = await event.reply("🔄 محاسبه...")
    await user_client.get_me()
    ping_ms = round((time.time() - start) * 1000)
    
    sys_info = await get_system_info()
    
    await msg.edit(f"📶 **Ping:** `{ping_ms}ms`\n{sys_info}")

# --- 4. پخش فایل و آهنگ طولانی (Play) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_handler(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    reply = await event.get_reply_message()
    
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ لطفاً روی فایل (آهنگ/فیلم) ریپلای کنید.")

    # 1. پاکسازی قبلی
    await force_cleanup(chat_id)
    
    status = await event.reply("📥 **در حال دانلود فایل...**\n(فایل‌های طولانی ممکن است کمی زمان ببرند)")
    
    try:
        # نام‌گذاری فایل بر اساس چت آیدی
        file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4")
        
        # دانلود فایل با پروگرس بار داخلی Telethon (بهینه شده با cryptg)
        dl_res = await reply.download_media(file=file_path)
        
        if not dl_res:
            return await status.edit("❌ دانلود ناموفق بود.")
        
        # ذخیره وضعیت برای مدیریت پاکسازی
        active_calls_data[chat_id] = {"path": dl_res, "type": "file"}
        
        await status.edit("🚀 **در حال اتصال به ویس‌کال...**")
        
        # شروع استریم
        await start_stream_engine(chat_id, dl_res, is_live=False)
        
        await status.edit("▶️ **پخش شروع شد.**\n✅ فایل با موفقیت بارگذاری شد.")

    except Exception as e:
        logger.error(f"Play Error: {e}")
        await status.edit(f"❌ خطا در پخش: {e}")
        await force_cleanup(chat_id)

# --- 5. پخش زنده (Live) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_handler(event):
    if not await check_permission(event): return
    
    # حذف پیام لینک برای امنیت
    try: await event.delete()
    except: pass

    chat_id = event.chat_id
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    display_name = "ایران اینترنشنال"

    # پاکسازی قبلی
    await force_cleanup(chat_id)
    
    status = await user_client.send_message(chat_id, "📡 **در حال پردازش لینک...**")

    try:
        # اگر لینک داده شده، آن را پردازش کن
        if url_arg:
            extracted_url, title = await get_stream_link(url_arg)
            if extracted_url:
                final_url = extracted_url
                display_name = title or "استریم درخواستی"
            else:
                # اگر yt-dlp نتوانست استخراج کند، لینک مستقیم را تست کن
                final_url = url_arg
                display_name = "لینک مستقیم"

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        
        await start_stream_engine(chat_id, final_url, is_live=True)
        
        await status.edit(f"🔴 **پخش زنده فعال شد:**\n📺 `{display_name}`\n⚡️ بهینه‌سازی شده برای جلوگیری از لگ")

    except Exception as e:
        logger.error(f"Live Error: {e}")
        await status.edit(f"❌ خطا در لایو: {e}")
        await force_cleanup(chat_id)

# --- 6. توقف (Stop) ---
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_handler(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    try:
        await call_py.leave_group_call(chat_id)
        await force_cleanup(chat_id)
        await event.reply("⏹ **پخش متوقف شد و حافظه پاکسازی گردید.**")
    except Exception as e:
        await event.reply("⚠️ مشکلی در توقف وجود ندارد یا قبلاً متوقف شده است.")

# --- رویداد پایان پخش (اتوماتیک) ---
@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    logger.info(f"Stream ended for chat {chat_id}")
    try:
        await client.leave_group_call(chat_id)
    except: pass
    
    # پاکسازی فوری بعد از اتمام آهنگ
    await force_cleanup(chat_id)

# ==========================================
# 🌐 اجرای برنامه (Main Loop)
# ==========================================
async def main():
    # وب سرور ساده برای جلوگیری از خوابیدن ربات در کلاد
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is Running with High Performance!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("🚀 Starting Bot & Userbot...")
    
    # پاکسازی اولیه
    await initial_cleanup()
    
    await bot.start(bot_token=BOT_TOKEN)
    
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("✅ Userbot authorized. Starting PyTgCalls...")
            await call_py.start()
        else:
            logger.warning("❌ Userbot is NOT authorized. Login via Bot.")
    except Exception as e:
        logger.error(f"Connection Error: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())