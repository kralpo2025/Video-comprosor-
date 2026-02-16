import os
import asyncio
import logging
import wget
import tarfile
import shutil
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession, StringSession
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

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

# تنظیمات لاگ (فقط اطلاعات مهم)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای حافظه
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب‌کننده FFmpeg (حیاتی برای رندر)
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
# 🚀 تعریف کلاینت‌ها (بدون استارت)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# کلاینت 1: ربات مدیریت (Telethon)
bot = TelegramClient('bot_session', API_ID, API_HASH)

# کلاینت 2: یوزربات (Telethon) - فایل سشن می‌سازیم تا لاگین بماند
user_client = TelegramClient('user_session', API_ID, API_HASH)

# کلاینت 3: موزیک پلیر (PyTgCalls)
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
    """موتور پخش را فقط در صورت نیاز روشن می‌کند"""
    if not call_py.active_calls:
        try:
            await call_py.start()
            logger.info("✅ PyTgCalls Engine Started!")
        except Exception as e:
            logger.error(f"Engine Start Fail: {e}")

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 هندلرهای ربات (پنل لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.reply(f"⛔️ شما ادمین نیستید.\nآیدی شما: `{event.sender_id}`")
    
    # بررسی وضعیت یوزربات (بدون گیر کردن)
    status = "🔴 خاموش"
    if user_client.is_connected() and await user_client.is_user_authorized():
        status = "🟢 آنلاین"
        
    await event.reply(
        f"👋 **پنل مدیریت ربات**\n"
        f"وضعیت یوزربات: {status}\n\n"
        "**ورود به حساب:**\n"
        "1️⃣ `/phone +98...`\n"
        "2️⃣ `/code 12345`\n"
        "3️⃣ `/password ...`\n\n"
        "**دستورات پخش (در گروه):**\n"
        "🎵 `/ply` (روی مدیا)\n"
        "📡 `/live` (شبکه خبر)\n"
        "❌ `/stop`"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_handler(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ اتصال به سرور تلگرام...")
        
        if not user_client.is_connected():
            await user_client.connect()
            
        send_code = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = send_code.phone_code_hash
        
        await msg.edit("✅ کد ارسال شد. لطفا کد را بفرستید:\n`/code 12345`")
    except FloodWaitError as e:
        await msg.edit(f"❌ **محدودیت:** {e.seconds} ثانیه صبر کنید.")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_handler(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        
        await event.reply("✅ **لاگین موفقیت آمیز بود!**\n🚀 در حال استارت موتور پخش...")
        await start_player_engine()
        await event.reply("🎧 **ربات آماده پخش است!**")
        
    except SessionPasswordNeededError:
        await event.reply("⚠️ **تایید دو مرحله‌ای:**\n`/password رمزعبور`")
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def password_handler(event):
    if event.sender_id != ADMIN_ID: return
    try:
        pwd = event.pattern_match.group(1).strip()
        await user_client.sign_in(password=pwd)
        
        await event.reply("✅ **ورود موفق!**\n🚀 استارت موتور پخش...")
        await start_player_engine()
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎵 هندلرهای یوزربات (پخش کننده)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_command(event):
    # چک میکنیم موتور روشن باشد
    await start_player_engine()
    
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ روی فایل ریپلای کن!")

    msg = await event.reply("📥 **در حال دانلود...**")
    chat_id = event.chat_id

    try:
        await cleanup(chat_id)
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path

        await msg.edit("🎧 **در حال پخش...**", buttons=[[Button.inline("❌ توقف پخش", data=b'stop')]])
        
        await call_py.play(chat_id, AudioVideoPiped(path))
        
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_command(event):
    await start_player_engine()
    msg = await event.reply("📡 **اتصال به شبکه خبر...**")
    
    try:
        await cleanup(event.chat_id)
        await call_py.play(event.chat_id, AudioVideoPiped(LIVE_URL))
        
        await msg.edit("🔴 **پخش زنده شروع شد!**", buttons=[[Button.inline("❌ قطع ارتباط", data=b'stop')]])
        
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_command(event):
    try:
        await call_py.leave_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ پخش متوقف شد.")
    except: pass

# ==========================================
# 🛑 هندلر دکمه شیشه‌ای (روی ربات)
# ==========================================
@bot.on(events.CallbackQuery(data=b'stop'))
async def callback_stop(event):
    if event.sender_id != ADMIN_ID:
        return await event.answer("⛔️ دسترسی ندارید!", alert=True)
    
    # دستور توقف را اجرا میکنیم
    try:
        # اینجا باید با یوزربات عملیات را انجام دهیم اما دکمه روی ربات است
        # پس از آبجکت call_py استفاده میکنیم
        chat_id = event.chat_id
        await call_py.leave_call(chat_id)
        await cleanup(chat_id)
        await event.edit("⏹ **پخش با دکمه متوقف شد.**")
    except Exception as e:
        await event.answer(f"خطا: {e}", alert=True)

# ==========================================
# 🌐 سرور و اجرا (Main)
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running")

async def main():
    # 1. اجرای وب سرور (اولویت اول)
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server Started")

    # 2. استارت ربات (اولویت دوم)
    logger.info("🤖 Starting Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started! Waiting for /start...")

    # 3. یوزربات (بدون استارت اجباری)
    # فقط چک میکنیم اگر سشن داشت وصل شه، اگر نداشت کاری نمیکنه (گیر نمیکنه)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("✅ Userbot Auto-Logged in!")
            await start_player_engine()
        else:
            logger.info("⚠️ Userbot needs login via /phone")
    except Exception as e:
        logger.error(f"Userbot Check: {e}")

    # 4. زنده نگه داشتن برنامه
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())