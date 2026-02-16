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
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")
PORT = int(os.environ.get("PORT", 8080))

# متغیرهای سراسری
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

# کلاینت ربات (همیشه روشن میشود)
bot = Client("BotSession", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# کلاینت یوزربات (ابتدا فقط تعریف میشود، استارت نمیشود)
user = Client("UserSession", api_id=API_ID, api_hash=API_HASH, in_memory=True)
call_py = PyTgCalls(user)

# ==========================================
# 🗑 توابع کمکی
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
# 🎮 دستورات یوزربات (فقط وقتی لاگین باشد کار میکنند)
# ==========================================
@user.on_message(filters.command("ply") & filters.user(ADMIN_ID))
async def play_handler(c, m):
    if not call_py.active_calls and not user.is_connected:
        return await m.reply("❌ سرویس پخش فعال نیست.")
        
    chat_id = m.chat.id
    replied = m.reply_to_message
    if not replied or not (replied.audio or replied.video):
        return await m.reply("❌ ریپلای کن!")

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
# 🔐 پنل مدیریت (ربات) - کلید حل مشکل اینجاست
# ==========================================
async def start_music_service():
    """این تابع فقط وقتی لاگین موفق بود اجرا میشه"""
    try:
        if not call_py.active_calls: # چک میکنیم دوباره استارت نشه
            await call_py.start()
            logger.info("✅ سرویس موزیک استارت شد!")
    except Exception as e:
        logger.error(f"Error starting music: {e}")

@bot.on_message(filters.command("start"))
async def start_cmd(c, m):
    # ربات الان آزاده و باید همیشه جواب بده
    if m.from_user.id != ADMIN_ID:
        return await m.reply(f"⛔️ شما ادمین نیستید.\nآیدی شما: `{m.from_user.id}`")
    
    status = "🟢 وصل" if user.is_connected else "🔴 قطع"
    await m.reply(f"👋 سلام!\nوضعیت یوزربات: {status}\n\n1. `/phone +98...`\n2. `/code ...`")

@bot.on_message(filters.command("phone") & filters.user(ADMIN_ID))
async def ph_cmd(c, m):
    try:
        p = m.text.split()[1]
        # اینجا فقط کانکت میکنیم، استارت نمیزنیم که گیر نکنه
        if not user.is_connected: 
            await user.connect()
        
        s = await user.send_code(p)
        login_data.update({'p': p, 'h': s.phone_code_hash})
        await m.reply("✅ کد رو بفرست: `/code 12345`")
    except Exception as e: await m.reply(f"❌ {e}")

@bot.on_message(filters.command("code") & filters.user(ADMIN_ID))
async def co_cmd(c, m):
    try:
        code = m.text.split()[1]
        await user.sign_in(login_data['p'], login_data['h'], code)
        await m.reply("✅ **لاگین شد! در حال روشن کردن موتور پخش...**")
        
        # 🔥 اینجا یوزربات وصل شده، پس امنه که موزیک پلیر رو روشن کنیم
        await start_music_service()
        await m.reply("🚀 **موزیک پلیر آماده است!**")
            
    except SessionPasswordNeeded:
        await m.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await m.reply(f"❌ {e}")

@bot.on_message(filters.command("password") & filters.user(ADMIN_ID))
async def pa_cmd(c, m):
    try:
        pwd = m.text.split()[1]
        await user.check_password(password=pwd)
        await m.reply("✅ **لاگین شد! در حال روشن کردن موتور پخش...**")
        
        # 🔥 اینجا هم امنه
        await start_music_service()
        await m.reply("🚀 **موزیک پلیر آماده است!**")
            
    except Exception as e: await m.reply(f"❌ {e}")

# ==========================================
# 🌐 اجرا (Main)
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running")

async def main():
    # 1. وب سرور (برای اینکه رندر نخوابه)
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server Started")

    # 2. فقط ربات رو استارت میزنیم (یوزربات خاموشه)
    await bot.start()
    logger.info("🤖 Bot Started! Waiting for commands...")

    # 3. چک میکنیم شاید از قبل سشن داشته باشه
    try:
        await user.connect()
        if await user.get_me():
            logger.info("👤 Userbot already logged in. Starting Player...")
            await start_music_service()
        else:
            logger.info("⚠️ Userbot NOT logged in. Waiting for /phone...")
            # نکته مهم: اینجا user.disconnect() نمیکنیم، باز میذاریم ولی کاری نمیکنیم
    except:
        pass

    # 4. لوپ اصلی که برنامه رو باز نگه میداره
    await idle()

if __name__ == "__main__":
    asyncio.run(main())