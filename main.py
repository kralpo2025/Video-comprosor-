import os
import asyncio
import logging
import wget
import tarfile
import shutil
import subprocess
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
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")

# متغیرهای سراسری
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب و پیکربندی FFmpeg (حیاتی)
# ==========================================
def setup_ffmpeg():
    # 1. مسیر فعلی
    cwd = os.getcwd()
    
    # 2. اضافه کردن مسیر فعلی به PATH سیستم (خیلی مهم)
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    # 3. چک کردن نصب بودن
    if shutil.which("ffmpeg"):
        logger.info(f"✅ FFmpeg found at: {shutil.which('ffmpeg')}")
        return

    logger.info("⏳ FFmpeg not found! Downloading static build...")
    try:
        # دانلود نسخه استاتیک
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        
        # استخراج
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        # جابجایی فایل باینری به ریشه پروژه
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                source = os.path.join(root, "ffmpeg")
                destination = os.path.join(cwd, "ffmpeg")
                if os.path.exists(destination): os.remove(destination)
                shutil.move(source, destination)
                # دادن دسترسی اجرا
                os.chmod(destination, 0o755)
                break
        
        # پاکسازی
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        
        logger.info("✅ FFmpeg Installed Successfully!")
        
        # تست نهایی
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("✅ FFmpeg test passed.")
        except Exception as e:
            logger.error(f"❌ FFmpeg is installed but check failed: {e}")
            
    except Exception as e:
        logger.error(f"❌ Critical Error installing FFmpeg: {e}")

# اجرای نصب در ابتدای برنامه
setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# ربات مدیریت
bot = TelegramClient('bot_session_mem', API_ID, API_HASH)

# یوزربات
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def start_player_engine():
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("✅ Player Engine Running")
    except Exception as e:
        logger.error(f"Engine Start Error: {e}")

async def safe_stream(chat_id, stream_source):
    """مدیریت هوشمند اتصال به کال"""
    try:
        # اگر از قبل وصل هستیم، فقط استریم رو عوض کن
        await call_py.change_stream_call(chat_id, stream_source)
    except:
        try:
            # اگر وصل نیستیم یا ارور داد، جوین شو
            await call_py.join_group_call(chat_id, stream_source)
        except Exception as e:
            error_msg = str(e).lower()
            if "already" in error_msg:
                 # اگر گفت قبلا هستی ولی چنج نشد، لفت بده دوباره بیا
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream_source)
            elif "no group call" in error_msg:
                raise Exception("⚠️ **ویس‌کال گروه خاموش است!**\nلطفاً ویس‌کال را روشن کنید.")
            else:
                raise e

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_group_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 ربات مدیریت
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.reply("⛔️ شما ادمین نیستید.")
    
    st = "🟢 آنلاین" if user_client.is_connected() and await user_client.is_user_authorized() else "🔴 قطع"
    await event.reply(f"👋 **پنل مدیریت**\nوضعیت: {st}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`")

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
        await msg.edit("✅ کد: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await start_player_engine()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await start_player_engine()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 یوزربات (اصلاح شده با مسیر مطلق)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await start_player_engine()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        
        # دانلود فایل و دریافت مسیر مطلق (Absolute Path)
        # این کلید حل مشکل شماست
        file_name = f"{chat_id}.mp4"
        download_location = os.path.join(os.getcwd(), DOWNLOAD_DIR, file_name)
        
        path = await reply.download_media(file=download_location)
        active_files[chat_id] = path
        
        if not os.path.exists(path):
            return await msg.edit("❌ خطا: فایل دانلود نشد.")

        await msg.edit(f"🎧 اتصال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
        # پخش با مسیر مطلق
        await safe_stream(chat_id, AudioVideoPiped(path))
        
        await msg.edit("▶️ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_player_engine()
    msg = await event.reply("📡 اتصال به لایو...")
    try:
        await cleanup(event.chat_id)
        await safe_stream(event.chat_id, AudioVideoPiped(LIVE_URL))
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
# 🌐 اجرا
# ==========================================
async def web_handler(r): return web.Response(text="Bot OK")

async def main():
    # اجرای وب سرور در بک گراند
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌍 Web Server Started")

    # اتصال ربات
    logger.info("🤖 Bot Connecting...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started!")

    # اتصال یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_player_engine()
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())