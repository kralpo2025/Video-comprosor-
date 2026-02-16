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
# ⚙️ تنظیمات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
# آیدی عددی خود را اینجا بگذارید. حتی اگر اشتباه باشد ربات به شما می‌گوید آیدی شما چیست.
ADMIN_ID = 7419222963 

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"

# تنظیم سطح لاگ روی DEBUG برای دیدن همه جزئیات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")
PORT = int(os.environ.get("PORT", 8080))

login_data = {}
active_files = {}

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def install_ffmpeg():
    os.environ["PATH"] += os.pathsep + os.getcwd()
    if os.path.exists("ffmpeg"):
        return
    logger.info("⏳ در حال دانلود FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), "./ffmpeg")
                os.chmod("./ffmpeg", 0o755)
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        logger.info("✅ نصب FFmpeg تمام شد.")
    except Exception as e:
        logger.error(f"❌ خطا در نصب: {e}")

install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# ربات اصلی
bot = Client("BotSession", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# یوزربات (ابتدا خاموش)
user = Client("UserSession", api_id=API_ID, api_hash=API_HASH, in_memory=True)
call_py = PyTgCalls(user)

# ==========================================
# 🗑 مدیریت فایل
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
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
# 🕵️‍♂️ دیباگ (مهمترین بخش برای حل مشکل شما)
# ==========================================
@bot.on_message(group=-1)
async def debug_logger(client, message):
    # این تابع هر پیامی به ربات برسد را در لاگ رندر چاپ می‌کند
    # اگر این را در لاگ دیدید یعنی ربات سالم است
    logger.info(f"📨 پیام جدید! از طرف: {message.from_user.id} | متن: {message.text}")

# ==========================================
# 🔐 پنل مدیریت (ربات)
# ==========================================

# فیلتر ادمین را برداشتیم تا ربات حتما جواب بدهد
@bot.on_message(filters.command("start"))
async def start_cmd(c, m):
    user_id = m.from_user.id
    
    # چک کردن دستی ادمین
    if user_id != ADMIN_ID:
        return await m.reply(f"⛔️ **شما ادمین نیستید!**\n\n🆔 آیدی شما: `{user_id}`\n⚙️ آیدی ادمین در کد: `{ADMIN_ID}`\n\nلطفاً آیدی خود را در کد اصلاح کنید.")
    
    status = "🟢 وصل" if user.is_connected else "🔴 قطع (نیاز به لاگین)"
    await m.reply(f"👋 **سلام قربان! ربات فعال شد.**\n\nوضعیت یوزربات: {status}\n\n1️⃣ ارسال شماره: `/phone +989...`\n2️⃣ ارسال کد: `/code 12345`")

@bot.on_message(filters.command("phone") & filters.user(ADMIN_ID))
async def ph_cmd(c, m):
    try:
        if len(m.command) < 2: return await m.reply("❌ شماره را وارد نکردید.\nمثال: `/phone +989123456789`")
        p = m.text.split()[1]
        
        await m.reply("⏳ در حال اتصال به سرور تلگرام...")
        if not user.is_connected: 
            await user.connect()
        
        s = await user.send_code(p)
        login_data.update({'p': p, 'h': s.phone_code_hash})
        await m.reply(f"✅ کد به شماره `{p}` ارسال شد.\nحالا کد را بفرستید: `/code 12345`")
    except Exception as e:
        await m.reply(f"❌ خطا: {e}")
        logger.error(f"Login Error: {e}")

@bot.on_message(filters.command("code") & filters.user(ADMIN_ID))
async def co_cmd(c, m):
    try:
        if len(m.command) < 2: return await m.reply("❌ کد را وارد نکردید.")
        code = m.text.split()[1]
        
        await user.sign_in(login_data['p'], login_data['h'], code)
        await m.reply("✅ **لاگین با موفقیت انجام شد!**\n🚀 در حال استارت سرویس پخش...")
        
        # استارت سرویس پخش
        if not call_py.active_calls:
            await call_py.start()
        
        await m.reply("🎧 **موزیک پلیر آماده است!**\nحالا در گروه دستور `/ply` را تست کنید.")
            
    except SessionPasswordNeeded:
        await m.reply("⚠️ **تایید دو مرحله‌ای دارید.**\nرمز را بفرستید: `/password رمزعبور`")
    except Exception as e: await m.reply(f"❌ خطا: {e}")

@bot.on_message(filters.command("password") & filters.user(ADMIN_ID))
async def pa_cmd(c, m):
    try:
        pwd = m.text.split()[1]
        await user.check_password(password=pwd)
        await m.reply("✅ **لاگین شد! در حال استارت...**")
        
        if not call_py.active_calls:
            await call_py.start()
        await m.reply("🎧 **موزیک پلیر آماده است!**")
            
    except Exception as e: await m.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 دستورات یوزربات
# ==========================================
@user.on_message(filters.command("ply") & filters.user(ADMIN_ID))
async def play_handler(c, m):
    # چک کردن اینکه آیا سرویس پخش ران شده یا نه
    try:
        if not call_py.active_calls and not user.is_connected:
             # تلاش برای استارت خودکار اگر قطع شده بود
            await call_py.start()
    except:
        pass

    chat_id = m.chat.id
    replied = m.reply_to_message
    if not replied or not (replied.audio or replied.video):
        return await m.reply("❌ روی فایل ریپلای کن!")

    msg = await m.reply("📥 دانلود...")
    try:
        await cleanup(chat_id)
        path = await replied.download(f"{DOWNLOAD_DIR}/{chat_id}_{int(time.time())}.mp4")
        active_files[chat_id] = path

        await msg.edit("🎧 پخش...")
        await call_py.play(chat_id, AudioVideoPiped(path))
        await msg.edit("✅ پخش شد!")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user.on_message(filters.command("live") & filters.user(ADMIN_ID))
async def live_handler(c, m):
    try:
        if not call_py.active_calls: await call_py.start()
    except: pass
    
    msg = await m.reply("📡 اتصال...")
    try:
        await cleanup(m.chat.id)
        await call_py.play(m.chat.id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 لایو!")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_handler(c, m):
    try:
        await call_py.leave_call(m.chat.id)
        await cleanup(m.chat.id)
        await m.reply("⏹ قطع شد.")
    except: pass

# ==========================================
# 🌐 اجرا (Main)
# ==========================================
async def web_handler(r): return web.Response(text="Bot is ALIVE")

async def main():
    # 1. اجرای وب سرور (برای زنده ماندن در رندر)
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server Started")

    # 2. فقط ربات را روشن میکنیم (یوزربات خاموش میماند)
    logger.info("🤖 Starting Bot Client...")
    await bot.start()
    logger.info("✅ Bot Started! Send /start in Telegram.")

    # 3. نگه داشتن برنامه
    await idle()

if __name__ == "__main__":
    asyncio.run(main())