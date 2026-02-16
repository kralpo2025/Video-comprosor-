import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات (اطلاعات خود را وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
# آیدی عددی خودت رو اینجا بذار. اگر اشتباه باشه ربات بهت میگه.
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
# 🛠 نصب FFmpeg (حیاتی)
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
# 🚀 کلاینت‌ها (Telethon)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# کلاینت ربات (همیشه وصل)
bot = TelegramClient('BotSession', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# کلاینت یوزربات (فعلا خاموش - از MemorySession استفاده میکنیم که تداخل فایل نداشته باشه)
user = TelegramClient(MemorySession(), API_ID, API_HASH)
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
# 🔐 پنل مدیریت (ربات)
# ==========================================
async def start_music_service():
    """روشن کردن موتور پخش بعد از لاگین"""
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("🚀 Music Service Started!")
    except Exception as e:
        logger.error(f"Error starting PyTgCalls: {e}")

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender_id = event.sender_id
    
    # لاگ کردن آیدی برای اطمینان
    print(f"Start command from: {sender_id}")
    
    if sender_id != ADMIN_ID:
        return await event.reply(f"⛔️ شما ادمین نیستید.\nآیدی شما: `{sender_id}`")
    
    status = "🟢 وصل" if await user.is_user_authorized() else "🔴 قطع (نیاز به لاگین)"
    await event.reply(f"👋 سلام رئیس (نسخه Telethon)!\nوضعیت یوزربات: {status}\n\n1. `/phone +98...`\n2. `/code ...`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_handler(event):
    if event.sender_id != ADMIN_ID: return
    try:
        phone_number = event.pattern_match.group(1).strip()
        
        await event.reply("⏳ در حال اتصال به تلگرام...")
        if not user.is_connected():
            await user.connect()
            
        send_code = await user.send_code_request(phone_number)
        login_data['phone'] = phone_number
        login_data['hash'] = send_code.phone_code_hash
        
        await event.reply("✅ کد ارسال شد. بفرستید: `/code 12345`")
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_handler(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user.sign_in(login_data['phone'], code, phone_code_hash=login_data['hash'])
        
        await event.reply("✅ **لاگین شد! در حال روشن کردن پخش کننده...**")
        await start_music_service()
        await event.reply("🎧 **ربات آماده پخش است!**")
    except Exception as e:
        if "password" in str(e).lower():
            await event.reply("⚠️ رمز دو مرحله‌ای دارید: `/password ...`")
        else:
            await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def password_handler(event):
    if event.sender_id != ADMIN_ID: return
    try:
        pwd = event.pattern_match.group(1).strip()
        await user.sign_in(password=pwd)
        
        await event.reply("✅ **لاگین شد! در حال روشن کردن پخش کننده...**")
        await start_music_service()
        await event.reply("🎧 **ربات آماده پخش است!**")
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 دستورات یوزربات
# ==========================================
@user.on(events.NewMessage(pattern='/ply', outgoing=True))
@user.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_handler(event):
    chat_id = event.chat_id
    
    # چک کردن وضعیت اتصال سرویس موزیک
    try:
        if not call_py.active_calls: await call_py.start()
    except: pass

    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ روی فایل ریپلای کن!")

    msg = await event.reply("📥 دانلود...")
    try:
        await cleanup(chat_id)
        # دانلود فایل
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path

        await msg.edit("🎧 پخش...")
        await call_py.play(chat_id, AudioVideoPiped(path))
        await msg.edit("✅ پخش شد!")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user.on(events.NewMessage(pattern='/live', outgoing=True))
@user.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_handler(event):
    try:
        if not call_py.active_calls: await call_py.start()
    except: pass
    
    msg = await event.reply("📡 اتصال...")
    try:
        await cleanup(event.chat_id)
        await call_py.play(event.chat_id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 لایو!")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user.on(events.NewMessage(pattern='/stop', outgoing=True))
@user.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_handler(event):
    try:
        await call_py.leave_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ قطع شد.")
    except: pass

# ==========================================
# 🌐 اجرا (Main Loop)
# ==========================================
async def web_handler(r): return web.Response(text="Telethon Bot Alive")

async def main():
    # 1. وب سرور برای Render
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server Started")

    # 2. بررسی وضعیت یوزربات (بدون بلاک کردن)
    logger.info("👤 Checking Userbot status...")
    try:
        await user.connect()
        if await user.is_user_authorized():
            logger.info("✅ Userbot authorized. Starting Player...")
            await start_music_service()
        else:
            logger.info("⚠️ Userbot NOT authorized. Waiting for /phone in Bot...")
    except Exception as e:
        logger.error(f"Userbot check error: {e}")

    # 3. روشن نگه داشتن ربات (این خط برنامه را زنده نگه می‌دارد)
    logger.info("🤖 Bot is running...")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())