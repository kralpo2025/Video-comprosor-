import os
import asyncio
import logging
import wget
import tarfile
import shutil
import sys
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
# توکن ربات
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
# آیدی عددی خود را وارد کنید
ADMIN_ID = 7419222963

# لینک پخش زنده
LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

# لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرها
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب FFmpeg (اولین کار)
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
        logger.info("✅ FFmpeg Installed.")
    except Exception as e:
        logger.error(f"❌ FFmpeg Error: {e}")

install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# کلاینت 1: ربات (با MemorySession برای جلوگیری از قفل شدن فایل)
bot = TelegramClient('bot_session_mem', API_ID, API_HASH)

# کلاینت 2: یوزربات (با فایل سشن برای حفظ لاگین)
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

async def start_player():
    """استارت موتور پخش در صورت نیاز"""
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("✅ PyTgCalls Started")
    except Exception as e:
        logger.error(f"Player Start Error: {e}")

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 ربات مدیریت (بدون فیلتر برای دیباگ)
# ==========================================

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender_id = event.sender_id
    logger.info(f"Command /start received from {sender_id}")
    
    # ⚠️ نکته مهم: اینجا فیلتر ادمین رو برداشتیم تا ربات حتما جواب بده
    # اگر آیدی شما با ادمین فرق داشته باشه، بهتون میگه
    
    msg = f"👋 **سلام! ربات زنده است.**\n\n🆔 آیدی شما: `{sender_id}`\n🔑 آیدی ادمین: `{ADMIN_ID}`"
    
    if sender_id == ADMIN_ID:
        status = "🔴 خاموش"
        try:
            if user_client.is_connected() and await user_client.is_user_authorized():
                status = "🟢 آنلاین"
        except: pass
        
        msg += f"\n\nوضعیت یوزربات: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code 12345`\n3️⃣ `/password ...`"
    else:
        msg += "\n\n⛔️ **شما ادمین نیستید!** لطفا آیدی عددی خود را در کد اصلاح کنید."

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
        await msg.edit("✅ کد ارسال شد. بزن: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد! موتور پخش روشن شد.**")
        await start_player()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        pwd = event.pattern_match.group(1).strip()
        await user_client.sign_in(password=pwd)
        await event.reply("✅ **ورود موفق!**")
        await start_player()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 یوزربات
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await start_player()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path
        
        await msg.edit("🎧 پخش...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        await call_py.play(chat_id, AudioVideoPiped(path))
    except Exception as e:
        await msg.edit(f"❌ {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_player()
    msg = await event.reply("📡 اتصال...")
    try:
        await cleanup(event.chat_id)
        await call_py.play(event.chat_id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 لایو!", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.CallbackQuery(data=b'stop'))
async def stop_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    try:
        await call_py.leave_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.edit("⏹ توقف.")
    except: pass

# ==========================================
# 🌐 سرور (جداگانه)
# ==========================================
async def start_web_server():
    """اجرای وب‌سرور در بک‌گراند"""
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌍 Web Server Started (Background)")

# ==========================================
# 🏁 اجرای اصلی (بدون تداخل)
# ==========================================
async def main():
    # 1. وب سرور رو میفرستیم تو بک گراند که برنامه رو نگه نداره
    asyncio.create_task(start_web_server())

    # 2. استارت ربات
    logger.info("🤖 Starting Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started! Waiting for /start")

    # 3. چک کردن یوزربات (بدون بلاک کردن)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_player()
        else:
            logger.info("⚠️ Userbot needs login")
    except: pass

    # 4. نگه داشتن ربات روشن
    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass