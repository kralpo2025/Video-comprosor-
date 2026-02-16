import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.errors import SessionPasswordNeeded
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات (اطلاعات رو وارد کن)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")

# پورت رندر
PORT = int(os.environ.get("PORT", 8080))

# متغیرهای حافظه
login_data = {}
active_files = {}

# ==========================================
# 🛠 نصب‌کننده اتوماتیک FFmpeg (جادوی کار)
# ==========================================
def install_ffmpeg():
    if os.path.exists("ffmpeg"):
        logger.info("✅ FFmpeg از قبل نصب است.")
        # اضافه کردن به PATH
        os.environ["PATH"] += os.pathsep + os.getcwd()
        return

    logger.info("⏳ در حال دانلود و نصب FFmpeg...")
    try:
        # دانلود نسخه استاتیک لینوکس
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        print()
        
        # استخراج
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        # پیدا کردن فایل و انتقال به ریشه
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                source = os.path.join(root, "ffmpeg")
                shutil.move(source, "./ffmpeg")
                os.chmod("./ffmpeg", 0o755) # دسترسی اجرا
                break
        
        # پاکسازی
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        
        # اضافه کردن به PATH
        os.environ["PATH"] += os.pathsep + os.getcwd()
        logger.info("✅ نصب FFmpeg تمام شد!")
        
    except Exception as e:
        logger.error(f"❌ خطا در نصب FFmpeg: {e}")

# اجرای نصب همین ابتدای کار
install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# ربات برای مدیریت
bot = Client("BotSession", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# یوزربات برای پخش (In Memory)
user = Client("UserSession", api_id=API_ID, api_hash=API_HASH, in_memory=True)

# کلاینت تماس
call_py = PyTgCalls(user)

# ==========================================
# 🗑 توابع کمکی
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"🗑 فایل حذف شد: {path}")
            except: pass
        del active_files[chat_id]

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🎮 دستورات یوزربات
# ==========================================

@user.on_message(filters.command("ply") & filters.user(ADMIN_ID))
async def play_handler(c, m):
    chat_id = m.chat.id
    replied = m.reply_to_message

    if not replied or not (replied.audio or replied.video):
        return await m.reply("❌ **روی فایل ریپلای کن!**")

    msg = await m.reply("📥 **دانلود...**")

    try:
        await cleanup(chat_id)
        
        # دانلود فایل
        path = await replied.download(f"{DOWNLOAD_DIR}/{chat_id}_{int(time.time())}.mp4")
        active_files[chat_id] = path

        await msg.edit("🎧 **اتصال...**")
        
        await call_py.play(
            chat_id,
            AudioVideoPiped(path)
        )
        await msg.edit("✅ **پخش شد!**")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user.on_message(filters.command("live") & filters.user(ADMIN_ID))
async def live_handler(c, m):
    chat_id = m.chat.id
    msg = await m.reply("📡 **اتصال به لایو...**")
    try:
        await cleanup(chat_id)
        await call_py.play(
            chat_id,
            AudioVideoPiped(LIVE_URL)
        )
        await msg.edit("🔴 **لایو شروع شد!**")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_handler(c, m):
    try:
        await call_py.leave_call(m.chat.id)
        await cleanup(m.chat.id)
        await m.reply("⏹ **قطع شد.**")
    except: pass

# ==========================================
# 🔐 لاگین (مدیریت)
# ==========================================
@bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_cmd(c, m):
    st = "وصل" if user.is_connected else "قطع"
    await m.reply(f"وضعیت: {st}\n1. `/phone +98...`\n2. `/code ...`\n3. `/password ...`")

@bot.on_message(filters.command("phone") & filters.user(ADMIN_ID))
async def ph_cmd(c, m):
    try:
        p = m.text.split()[1]
        if not user.is_connected: await user.connect()
        s = await user.send_code(p)
        login_data.update({'p': p, 'h': s.phone_code_hash})
        await m.reply("کد رو بزن.")
    except Exception as e: await m.reply(f"❌ {e}")

@bot.on_message(filters.command("code") & filters.user(ADMIN_ID))
async def co_cmd(c, m):
    try:
        await user.sign_in(login_data['p'], login_data['h'], m.text.split()[1])
        await m.reply("✅ وصل شد.")
    except SessionPasswordNeeded:
        await m.reply("رمز دوم: `/password ...`")
    except Exception as e: await m.reply(f"❌ {e}")

@bot.on_message(filters.command("password") & filters.user(ADMIN_ID))
async def pa_cmd(c, m):
    try:
        await user.check_password(m.text.split()[1])
        await m.reply("✅ وصل شد.")
    except Exception as e: await m.reply(f"❌ {e}")

# ==========================================
# 🌐 اجرا (بدون داکر)
# ==========================================
async def web_handler(r): return web.Response(text="Running")

async def main():
    # وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    # ربات‌ها
    await bot.start()
    await call_py.start()
    
    # ریکانکت
    try:
        if not user.is_connected: await user.connect()
    except: pass
    
    print("✅ ربات روشن شد")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())