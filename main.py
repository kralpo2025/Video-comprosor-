import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# 🔴 تنظیمات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

# لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")

# متغیرهای سراسری
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب کننده FFmpeg (برای رندر)
# ==========================================
def install_ffmpeg():
    # اضافه کردن مسیر جاری به PATH
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
        logger.info("✅ FFmpeg نصب شد.")
    except Exception as e:
        logger.error(f"❌ خطا در نصب FFmpeg: {e}")

install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# ربات (همیشه وصل)
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# یوزربات (فعلا خاموش)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

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
# 🔐 پنل مدیریت (سیستم لاگین کدی که دادی)
# ==========================================
async def check_and_start_player():
    """اگر یوزربات وصل شد، پلیر رو روشن کن"""
    try:
        if await user_client.is_user_authorized():
            if not call_py.active_calls:
                await call_py.start()
                logger.info("✅ موزیک پلیر استارت شد!")
    except Exception as e:
        logger.error(f"Player Start Error: {e}")

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.reply("⛔️ شما ادمین نیستید.")
        
    status = "🔴 قطع"
    try:
        if await user_client.is_user_authorized(): status = "🟢 متصل"
    except: pass
    
    await event.reply(f"👑 **پنل مدیریت موزیک**\nوضعیت: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code 12345`\n3️⃣ `/password ...`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    ph = event.pattern_match.group(1).strip()
    msg = await event.reply("⏳ اتصال...")
    try:
        if not user_client.is_connected(): await user_client.connect()
        
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد ارسال شد. بزن: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **یوزربات وصل شد!**")
        await check_and_start_player() # روشن کردن پلیر
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دو مرحله‌ای: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ لاگین موفق.")
        await check_and_start_player() # روشن کردن پلیر
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎮 دستورات موزیک (Userbot)
# ==========================================

@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_handler(event):
    # اطمینان از روشن بودن موتور پخش
    try:
        if not call_py.active_calls: await call_py.start()
    except: pass

    chat_id = event.chat_id
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

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
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

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_handler(event):
    try:
        await call_py.leave_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ قطع شد.")
    except: pass

# ==========================================
# 🌐 اجرا (Main)
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running")

async def main():
    # 1. وب سرور (برای زنده ماندن در رندر)
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print("🌍 Web Server Started")

    # 2. بررسی وضعیت یوزربات
    print("👤 Checking Userbot...")
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            print("✅ Userbot is Logged In. Starting Player...")
            await check_and_start_player()
        else:
            print("⚠️ Userbot NOT Logged In. Use Bot to login.")
    except Exception as e:
        print(f"Login Check Error: {e}")

    # 3. روشن نگه داشتن ربات
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())