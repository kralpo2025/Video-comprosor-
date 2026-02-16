import os
import asyncio
import logging
import wget
import tarfile
import shutil
import sys
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession, StringSession
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

# لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای حافظه
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def install_ffmpeg():
    os.environ["PATH"] += os.pathsep + os.getcwd()
    if os.path.exists("ffmpeg"):
        return
    logger.info("⏳ Downloading FFmpeg...")
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
        logger.info("✅ FFmpeg Ready.")
    except: pass

install_ffmpeg()

# ==========================================
# 🚀 تعریف کلاینت‌ها (بدون استارت)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# 1. ربات مدیریت (از MemorySession استفاده می‌کنیم تا فایل نسازد و گیر نکند)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# 2. یوزربات (از فایل استفاده می‌کند تا لاگین بماند)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# 3. پلیر
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
    """تلاش برای روشن کردن موتور پخش"""
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("✅ Player Engine Started")
    except Exception as e:
        logger.error(f"Engine Start Error: {e}")

async def safe_play(chat_id, stream_input):
    """تابع پخش امن: خروج و ورود مجدد"""
    try:
        # اول سعی میکنیم لفت بدیم (اگر قبلا بوده باشیم)
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(0.5)
        except: pass
        
        # حالا جوین میشیم
        await call_py.join_group_call(chat_id, stream_input)
    except Exception as e:
        raise e

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_group_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 هندلرهای ربات (پنل)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    # لاگ می‌کنیم که پیام رسیده
    logger.info(f"Start command from {event.sender_id}")
    
    if event.sender_id != ADMIN_ID:
        return await event.reply(f"⛔️ شما ادمین نیستید.\n🆔 `{event.sender_id}`")
    
    status = "🔴 قطع"
    try:
        if user_client.is_connected() and await user_client.is_user_authorized():
            status = "🟢 آنلاین"
    except: pass
    
    await event.reply(
        f"👋 **پنل موزیک**\nوضعیت یوزربات: {status}\n\n"
        "1️⃣ `/phone +98...`\n"
        "2️⃣ `/code 12345`\n"
        "3️⃣ `/password ...`\n\n"
        "🎵 پخش: `/ply` (روی فایل)\n"
        "📡 زنده: `/live`\n"
        "⏹ توقف: `/stop`"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ اتصال به سرور...")
        
        if not user_client.is_connected():
            await user_client.connect()
            
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد را بفرستید: `/code 12345`")
    except FloodWaitError as e:
        await msg.edit(f"❌ محدودیت تلگرام: {e.seconds} ثانیه صبر کنید.")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد! موتور پخش روشن شد.**")
        await start_player_engine()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم دارید: `/password ...`")
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await start_player_engine()
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎵 هندلرهای یوزربات
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def ply_h(event):
    await start_player_engine()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path
        
        await msg.edit("🎧 اتصال به کال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        await safe_play(chat_id, AudioVideoPiped(path))
        await msg.edit("▶️ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}\n\n*نکته: ویس‌کال گروه باید روشن باشد.*")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_player_engine()
    msg = await event.reply("📡 اتصال به لایو...")
    try:
        await cleanup(event.chat_id)
        await safe_play(event.chat_id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 **لایو شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_cmd(event):
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ توقف.")
    except: pass

@bot.on(events.CallbackQuery(data=b'stop'))
async def stop_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.edit("⏹ متوقف شد.")
    except: await event.answer("خطا یا قبلا متوقف شده.", alert=True)

# ==========================================
# 🌐 سرور و اجرا
# ==========================================
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌍 Web Server Started")

async def main():
    # 1. وب سرور (در پس‌زمینه)
    asyncio.create_task(start_web_server())

    # 2. استارت ربات (با connect و sign_in دستی برای اطمینان)
    logger.info("🤖 Bot Connecting...")
    await bot.connect()
    if not await bot.is_user_authorized():
        await bot.sign_in(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started & Authorized! Waiting for /start")

    # 3. یوزربات (بدون بلاک کردن)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_player_engine()
        else:
            logger.info("⚠️ Userbot needs login")
    except Exception as e:
        logger.error(f"Userbot Check Error: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass