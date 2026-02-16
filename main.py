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
# ⚙️ تنظیمات (اطلاعات را وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

# لینک پخش زنده (شبکه خبر)
LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"

# پوشه دانلود
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")

# پورت رندر
PORT = int(os.environ.get("PORT", 8080))

# متغیرهای سراسری
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب‌کننده هوشمند FFmpeg (مخصوص Render)
# ==========================================
def setup_ffmpeg():
    # چک می‌کنیم اگر ffmpeg در سیستم نیست دانلودش کنیم
    if not os.path.exists("ffmpeg"):
        logger.info("⏳ در حال دانلود FFmpeg (نسخه استاتیک)...")
        try:
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            wget.download(url, "ffmpeg.tar.xz")
            print() # خط جدید
            
            logger.info("📦 در حال استخراج فایل...")
            with tarfile.open("ffmpeg.tar.xz") as f:
                f.extractall(".")
            
            # پیدا کردن فایل اجرایی و آوردن به روت
            for root, dirs, files in os.walk("."):
                if "ffmpeg" in files:
                    src = os.path.join(root, "ffmpeg")
                    shutil.move(src, "./ffmpeg")
                    os.chmod("./ffmpeg", 0o755) # دسترسی اجرا
                    break
            
            # پاکسازی
            if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
            logger.info("✅ FFmpeg نصب شد!")
        except Exception as e:
            logger.error(f"❌ خطا در نصب FFmpeg: {e}")

    # اضافه کردن پوشه جاری به PATH سیستم تا کتابخانه آن را پیدا کند
    os.environ["PATH"] += os.pathsep + os.getcwd()

# اجرای نصب قبل از هر چیز
setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = Client("BotSession", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("UserSession", api_id=API_ID, api_hash=API_HASH, in_memory=True)
call_py = PyTgCalls(user)

# ==========================================
# 🗑 توابع کمکی
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        try:
            if os.path.exists(active_files[chat_id]):
                os.remove(active_files[chat_id])
                logger.info("🗑 فایل حذف شد.")
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
async def play_handler(client, message):
    chat_id = message.chat.id
    replied = message.reply_to_message

    if not replied or not (replied.audio or replied.video):
        return await message.reply("❌ **روی فایل ریپلای کن!**")

    status = await message.reply("📥 **در حال دانلود...**")

    try:
        await cleanup(chat_id)
        
        # دانلود فایل
        file_path = await replied.download(f"downloads/{chat_id}_{int(time.time())}.mp4")
        active_files[chat_id] = file_path

        await status.edit("🎧 **اتصال به ویس‌کال...**")
        
        await call_py.play(
            chat_id,
            AudioVideoPiped(
                file_path,
            )
        )
        await status.edit("✅ **پخش شروع شد!**")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user.on_message(filters.command("live") & filters.user(ADMIN_ID))
async def live_handler(client, message):
    chat_id = message.chat.id
    status = await message.reply("📡 **در حال اتصال...**")
    try:
        await cleanup(chat_id)
        await call_py.play(
            chat_id,
            AudioVideoPiped(
                LIVE_URL,
            )
        )
        await status.edit("🔴 **پخش زنده!**")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")

@user.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_handler(client, message):
    try:
        await call_py.leave_call(message.chat.id)
        await cleanup(message.chat.id)
        await message.reply("⏹ **قطع شد.**")
    except: pass

# ==========================================
# 🔐 پنل لاگین
# ==========================================

@bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_cmd(client, message):
    st = "🟢 متصل" if user.is_connected else "🔴 قطع"
    await message.reply(f"وضعیت: {st}\n\n1. `/phone +98...`\n2. `/code 12345`\n3. `/password ...`")

@bot.on_message(filters.command("phone") & filters.user(ADMIN_ID))
async def phone_cmd(client, message):
    try:
        ph = message.text.split()[1]
        if not user.is_connected: await user.connect()
        s = await user.send_code(ph)
        login_state.update({'ph': ph, 'h': s.phone_code_hash})
        await message.reply("✅ کد بفرست: `/code 12345`")
    except Exception as e: await message.reply(f"❌ {e}")

@bot.on_message(filters.command("code") & filters.user(ADMIN_ID))
async def code_cmd(client, message):
    try:
        c = message.text.split()[1]
        await user.sign_in(login_state['ph'], login_state['h'], c)
        await message.reply("✅ **متصل شد!**")
    except SessionPasswordNeeded:
        await message.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await message.reply(f"❌ {e}")

@bot.on_message(filters.command("password") & filters.user(ADMIN_ID))
async def pass_cmd(client, message):
    try:
        p = message.text.split()[1]
        await user.check_password(password=p)
        await message.reply("✅ **متصل شد!**")
    except Exception as e: await message.reply(f"❌ {e}")

# ==========================================
# 🌐 اجرا
# ==========================================
async def web_srv(r): return web.Response(text="Running")

async def main():
    # وب سرور
    app = web.Application()
    app.router.add_get("/", web_srv)
    run = web.AppRunner(app)
    await run.setup()
    await web.TCPSite(run, "0.0.0.0", PORT).start()

    # ربات‌ها
    await bot.start()
    await call_py.start()
    
    # اتصال یوزربات اگر سشن داشت
    try:
        if not user.is_connected: await user.connect()
    except: pass
    
    print("✅ ربات روشن شد")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())