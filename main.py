import os
import sys
import logging
import asyncio
import shutil
import tarfile
import subprocess

# ==========================================
# 🛠 نصب اضطراری FFmpeg (قبل از هر ایمپورت دیگر)
# ==========================================
# تنظیم لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

def setup_environment():
    """دانلود و تنظیم FFmpeg قبل از اجرای برنامه"""
    cwd = os.getcwd()
    ffmpeg_path = os.path.join(cwd, "ffmpeg")
    
    # 1. اضافه کردن مسیر جاری به PATH سیستم
    # این خط باعث می‌شود py-tgcalls بتواند ffmpeg را ببیند
    os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    # 2. چک کردن وجود فایل
    if shutil.which("ffmpeg"):
        logger.info(f"✅ FFmpeg detected at: {shutil.which('ffmpeg')}")
        return

    logger.info("⏳ FFmpeg not found. Downloading static build...")
    try:
        import wget
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        print() # خط جدید
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        # پیدا کردن فایل باینری و انتقال به ریشه
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                src = os.path.join(root, "ffmpeg")
                if os.path.exists(ffmpeg_path): os.remove(ffmpeg_path)
                shutil.move(src, ffmpeg_path)
                os.chmod(ffmpeg_path, 0o755) # دسترسی اجرا
                break
        
        # پاکسازی
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        
        # تست نهایی
        if os.path.exists(ffmpeg_path):
            logger.info("✅ FFmpeg downloaded and installed successfully.")
        else:
            logger.error("❌ Failed to install FFmpeg.")
            
    except Exception as e:
        logger.error(f"❌ Critical Error in Setup: {e}")

# اجرای ستاپ قبل از ایمپورت‌های سنگین
setup_environment()

# ==========================================
# 📦 ایمپورت‌های اصلی
# ==========================================
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
# توکن ربات شما
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
# آیدی عددی ادمین
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

# متغیرهای سراسری
login_state = {}
active_files = {}

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# 1. ربات مدیریت (MemorySession برای سرعت بالا و عدم فریز)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# 2. یوزربات (Session File برای ماندگاری لاگین)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# 3. موزیک پلیر
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع پخش (کاملاً اصلاح شده)
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def start_engine():
    """روشن کردن موتور پخش"""
    if not call_py.active_calls:
        try:
            await call_py.start()
            logger.info("✅ Player Engine Started.")
        except Exception as e:
            logger.error(f"Engine Start Error: {e}")

async def smart_play(chat_id, source):
    """
    تابع هوشمند پخش:
    1. اول سعی میکنه استریم رو عوض کنه (Change).
    2. اگه نشد، سعی میکنه جوین بده (Join).
    3. اگه بازم نشد، لفت میده و دوباره جوین میده.
    """
    try:
        # حالت 1: تغییر موزیک
        await call_py.change_stream_call(chat_id, source)
    except Exception:
        try:
            # حالت 2: ورود به کال
            await call_py.join_group_call(chat_id, source)
        except Exception as e:
            err = str(e).lower()
            if "no group call" in err:
                raise Exception("⚠️ **ویس‌کال گروه خاموش است!**\nلطفا ویس‌کال را روشن کنید.")
            
            # حالت 3: ریستارت اتصال
            try:
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, source)
            except Exception as final_e:
                raise final_e

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_group_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 پنل مدیریت ربات
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    # لاگ برای اطمینان از زنده بودن ربات
    logger.info(f"Start from: {event.sender_id}")
    
    # برداشتن فیلتر برای تست اولیه
    # اگر ادمین نباشد هشدار می‌دهد ولی جواب می‌دهد
    msg = f"👋 **ربات موزیک پلیر**\n🆔 آیدی شما: `{event.sender_id}`"
    
    if event.sender_id == ADMIN_ID:
        status = "🔴 قطع"
        try:
            if user_client.is_connected() and await user_client.is_user_authorized():
                status = "🟢 آنلاین"
        except: pass
        
        msg += f"\nوضعیت یوزربات: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`\n3️⃣ `/password ...`"
    else:
        msg += "\n⛔️ شما ادمین نیستید."
        
    await event.reply(msg)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ ...")
        if not user_client.is_connected(): await user_client.connect()
        
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد را بفرستید: `/code 12345`")
    except FloodWaitError as e:
        await msg.edit(f"❌ محدودیت تلگرام: {e.seconds} ثانیه صبر کنید.")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await start_engine()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await start_engine()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 یوزربات (دستورات پخش)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await start_engine()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        
        # استفاده از مسیر مطلق (Absolute Path) برای رفع ارور No Source
        file_name = f"{chat_id}.mp4"
        abs_path = os.path.join(os.getcwd(), DOWNLOAD_DIR, file_name)
        
        path = await reply.download_media(file=abs_path)
        active_files[chat_id] = path
        
        if not os.path.exists(path):
            return await msg.edit("❌ فایل دانلود نشد.")

        await msg.edit("🎧 اتصال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
        # پخش فایل با مسیر مطلق
        await smart_play(chat_id, AudioVideoPiped(path))
        
        await msg.edit("▶️ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_engine()
    msg = await event.reply("📡 اتصال به لایو...")
    try:
        await cleanup(event.chat_id)
        await smart_play(event.chat_id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 **لایو شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e: await msg.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_cmd(event):
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ تمام.")
    except: pass

@bot.on(events.CallbackQuery(data=b'stop'))
async def stop_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.edit("⏹ متوقف شد.")
    except: await event.answer("خطا", alert=True)

# ==========================================
# 🌐 سرور (جداگانه)
# ==========================================
async def start_web():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌍 Web Server Started")

async def main():
    # 1. وب سرور (تسک جداگانه)
    asyncio.create_task(start_web())

    # 2. ربات (اتصال دستی و مطمئن)
    logger.info("🤖 Bot Connecting...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started! Waiting for /start")

    # 3. یوزربات (بدون بلاک)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_engine()
        else:
            logger.info("⚠️ Userbot needs login")
    except Exception as e:
        logger.error(f"Userbot Check: {e}")

    # 4. لوپ اصلی
    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass