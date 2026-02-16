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
from pytgcalls.types import MediaStream  # کلاس جدید و صحیح
from pytgcalls.types import AudioQuality, VideoQuality

# ==========================================
# ⚙️ تنظیمات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

login_state = {}
active_files = {}

# ساخت پوشه دانلود
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    # افزودن مسیر جاری به PATH سیستم
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    if shutil.which("ffmpeg"):
        logger.info(f"✅ FFmpeg detected.")
        return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        print()
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        logger.info("✅ FFmpeg Installed.")
    except Exception as e:
        logger.error(f"❌ FFmpeg Install Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# 1. ربات (MemorySession برای سرعت و عدم تداخل)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# 2. یوزربات (ذخیره سشن در فایل)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# 3. پلیر موزیک
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی و پخش
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def ensure_player_active():
    """بررسی و روشن کردن موتور پخش بدون ارور تکراری"""
    try:
        # چک میکنیم آیا موتور روشن است یا نه
        if not call_py.active_calls: 
            # این یک چک ساده است، متد دقیق‌تر ping است
            try:
                await call_py.start()
                logger.info("✅ Player Engine Started")
            except RuntimeError:
                # اگر گفت already running یعنی روشنه و مشکلی نیست
                pass
    except Exception as e:
        if "already running" not in str(e):
            logger.error(f"Engine Error: {e}")

async def smart_stream(chat_id, source_path):
    """مدیریت هوشمند ورود به کال"""
    # ایجاد آبجکت مدیا استریم (جایگزین AudioVideoPiped)
    stream = MediaStream(
        source_path,
        audio_parameters=AudioQuality.STUDIO, # کیفیت بالا
        video_parameters=VideoQuality.HD_720p # کیفیت ویدیو
    )

    try:
        # حالت 1: تلاش برای جوین
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        error = str(e).lower()
        
        # حالت 2: اگر در کال هستیم، تغییر موزیک
        if "already" in error or "group call" in error:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except Exception as e2:
                # حالت 3: اگر تغییر نکرد، خروج و ورود مجدد
                try:
                    await call_py.leave_group_call(chat_id)
                    await asyncio.sleep(1)
                    await call_py.join_group_call(chat_id, stream)
                except:
                    raise e2
        elif "no group call" in error or "not found" in error:
            raise Exception("⚠️ **ویس‌کال خاموش است!**\nلطفا ویس‌کال گروه را روشن کنید.")
        else:
            raise e

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_group_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 پنل مدیریت (ربات)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    logger.info(f"Start from: {event.sender_id}")
    
    # پاسخ به همه برای تست زنده بودن
    msg = f"👋 **ربات موزیک**\n🆔 آیدی شما: `{event.sender_id}`"
    
    if event.sender_id == ADMIN_ID:
        status = "🔴 قطع"
        try:
            if user_client.is_connected() and await user_client.is_user_authorized():
                status = "🟢 آنلاین"
        except: pass
        
        msg += f"\nوضعیت یوزربات: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`\n3️⃣ `/password ...`"
    else:
        msg += "\n⛔️ شما ادمین نیستید."
        
    await event.reply(msg)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ ...")
        
        if not user_client.is_connected():
            await user_client.connect()
            
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد را بفرستید: `/code 12345`")
    except FloodWaitError as e:
        await msg.edit(f"❌ محدودیت تلگرام: {e.seconds} ثانیه.")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await ensure_player_active()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await ensure_player_active()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 یوزربات
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await ensure_player_active()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        
        # استفاده از مسیر مطلق فایل
        file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4")
        path = await reply.download_media(file=file_path)
        active_files[chat_id] = path
        
        if not path or not os.path.exists(path):
            return await msg.edit("❌ دانلود نشد.")

        await msg.edit("🎧 اتصال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
        await smart_stream(chat_id, path)
        
        await msg.edit("▶️ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await ensure_player_active()
    msg = await event.reply("📡 اتصال به لایو...")
    try:
        await cleanup(event.chat_id)
        await smart_stream(event.chat_id, LIVE_URL)
        await msg.edit("🔴 **لایو شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e: await msg.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_cmd(event):
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ تمام.")
    except: pass

@bot.on(events.CallbackQuery(data=b'stop'))
async def stop_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.edit("⏹ متوقف شد.")
    except: await event.answer("خطا", alert=True)

# ==========================================
# 🌐 اجرا
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running")

async def start_web():
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌍 Web Server Started")

async def main():
    # اجرای وب‌سرور در تسک جداگانه
    asyncio.create_task(start_web())

    # اتصال ربات
    logger.info("🤖 Bot Connecting...")
    try:
        await bot.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot Started! Waiting for /start")
    except Exception as e:
        logger.error(f"Bot Start Error: {e}")

    # چک کردن یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await ensure_player_active()
        else:
            logger.info("⚠️ Userbot needs login")
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass