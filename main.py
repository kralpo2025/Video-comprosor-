import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات (اطلاعات خود را وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

# لینک پخش زنده (ایران اینترنشنال)
LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"

DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای سراسری
login_data = {}
active_files = {}

# ==========================================
# 🛠 نصب‌کننده اتوماتیک FFmpeg
# ==========================================
def install_ffmpeg():
    os.environ["PATH"] += os.pathsep + os.getcwd()
    if os.path.exists("ffmpeg"):
        return
    logger.info("⏳ در حال دانلود ابزار پخش (FFmpeg)...")
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
        logger.info("✅ ابزار پخش نصب شد.")
    except Exception as e:
        logger.error(f"❌ خطا در نصب: {e}")

install_ffmpeg()

# ==========================================
# 🚀 راه‌اندازی کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# 1. ربات مدیریت (همیشه آنلاین)
bot = TelegramClient('bot_session', API_ID, API_HASH)

# 2. یوزربات (پخش کننده موزیک)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 🗑 توابع مدیریت فایل و استریم
# ==========================================
async def cleanup(chat_id):
    """حذف فایل دانلودی پس از پایان پخش"""
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

@call_py.on_stream_end()
async def on_stream_end(client, update):
    """وقتی پخش تمام شد (خودکار)"""
    chat_id = update.chat_id
    try:
        await client.leave_call(chat_id)
        await cleanup(chat_id)
        # ارسال پیام اطلاع رسانی به گروه (اختیاری)
        # await bot.send_message(chat_id, "✅ پخش تمام شد.")
    except: pass

async def ensure_player_active():
    """اطمینان از روشن بودن موتور پخش"""
    try:
        if not call_py.active_calls:
            await call_py.start()
    except: pass

# ==========================================
# 🎮 هندلرهای یوزربات (پخش موزیک/ویدیو/لایو)
# ==========================================

@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_handler(event):
    await ensure_player_active()
    chat_id = event.chat_id
    reply = await event.get_reply_message()

    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ **روی یک آهنگ یا ویدئو ریپلای کنید.**")

    msg = await event.reply("📥 **در حال دانلود فایل...**")

    try:
        await cleanup(chat_id)
        
        # دانلود فایل
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path

        await msg.edit("🎧 **در حال اتصال به ویس‌کال...**")
        
        # پخش فایل
        await call_py.play(chat_id, AudioVideoPiped(path))
        
        # دکمه شیشه‌ای برای ربات (نه یوزربات)
        # چون یوزربات نمی‌تونه دکمه شیشه‌ای بفرسته، فقط متن رو ادیت میکنیم
        await msg.edit(
            "✅ **پخش شروع شد!**\n🗑 فایل بعد از پایان حذف می‌شود.",
            buttons=[[Button.inline("❌ توقف پخش", data=b"stop_play")]]
        )
        
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_handler(event):
    await ensure_player_active()
    chat_id = event.chat_id
    
    msg = await event.reply("📡 **در حال دریافت سیگنال شبکه خبر...**")
    
    try:
        await cleanup(chat_id)
        
        # پخش لینک آنلاین
        await call_py.play(chat_id, AudioVideoPiped(LIVE_URL))
        
        await msg.edit(
            "🔴 **پخش زنده (ایران اینترنشنال) شروع شد!**",
            buttons=[[Button.inline("❌ قطع ارتباط", data=b"stop_play")]]
        )
    except Exception as e:
        await msg.edit(f"❌ خطا در اتصال به لایو: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_command(event):
    chat_id = event.chat_id
    try:
        await call_py.leave_call(chat_id)
        await cleanup(chat_id)
        await event.reply("⏹ **پخش متوقف شد.**")
    except: pass

# ==========================================
# 🤖 هندلرهای ربات (دکمه‌ها و مدیریت)
# ==========================================

# هندلر دکمه "توقف پخش"
@bot.on(events.CallbackQuery(data=b"stop_play"))
async def callback_stop(event):
    if event.sender_id != ADMIN_ID:
        return await event.answer("⛔️ شما ادمین نیستید!", alert=True)
    
    chat_id = event.chat_id
    try:
        await call_py.leave_call(chat_id)
        await cleanup(chat_id)
        await event.edit("⏹ **پخش توسط ادمین متوقف شد.**")
    except Exception as e:
        await event.answer(f"خطا: {e}", alert=True)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.reply(f"⛔️ دسترسی ندارید.\nآیدی شما: `{event.sender_id}`")
    
    status = "🟢 متصل" if await user_client.is_user_authorized() else "🔴 قطع (نیاز به لاگین)"
    
    text = (
        f"👋 **پنل مدیریت موزیک بات**\n"
        f"وضعیت یوزربات: {status}\n\n"
        "**دستورات لاگین:**\n"
        "1️⃣ `/phone +98...`\n"
        "2️⃣ `/code 12345`\n"
        "3️⃣ `/password ...`\n\n"
        "**دستورات پخش (در گروه):**\n"
        "🎵 `/ply` (روی فایل ریپلای کن)\n"
        "📡 `/live` (پخش زنده شبکه خبر)\n"
        "⏹ `/stop` (توقف پخش)"
    )
    await event.reply(text)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ ...")
        
        if not user_client.is_connected(): await user_client.connect()
        
        s = await user_client.send_code_request(ph)
        login_data['phone'] = ph
        login_data['hash'] = s.phone_code_hash
        await msg.edit("✅ کد ارسال شد. بزن: `/code 12345`")
    except FloodWaitError as e:
        await msg.edit(f"⚠️ **محدودیت تلگرام:** {e.seconds} ثانیه صبر کنید.")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_data['phone'], code, phone_code_hash=login_data['hash'])
        await event.reply("✅ **یوزربات وصل شد!**\n🚀 سیستم پخش فعال شد.")
        await ensure_player_active()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دو مرحله‌ای: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**\n🚀 سیستم پخش فعال شد.")
        await ensure_player_active()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🌐 اجرا (بدون توقف)
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running")

async def main():
    # 1. وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server Started")

    # 2. استارت ربات
    logger.info("🤖 Starting Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started!")

    # 3. چک کردن یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("✅ Userbot Logged In. Starting Player...")
            await ensure_player_active()
    except Exception as e:
        logger.error(f"Userbot Check: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())