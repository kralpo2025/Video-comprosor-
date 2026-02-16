import os
import sys
import logging
import asyncio
import shutil
import subprocess
import tarfile

# ==========================================
# 🛠 تنظیمات اولیه و لاگینگ
# ==========================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# ==========================================
# 🔧 نصب FFmpeg (حیاتی برای پخش)
# ==========================================
def setup_ffmpeg():
    """بررسی و نصب FFmpeg در مسیر سیستم"""
    cwd = os.getcwd()
    
    # اضافه کردن مسیر جاری به PATH سیستم
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    # بررسی اینکه آیا نصب است؟
    if shutil.which("ffmpeg"):
        logger.info(f"✅ FFmpeg found at: {shutil.which('ffmpeg')}")
        return

    logger.info("⏳ FFmpeg not found. Downloading static build...")
    try:
        import wget
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        print()
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        # پیدا کردن و جابجایی فایل اجرایی
        found = False
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                source = os.path.join(root, "ffmpeg")
                target = os.path.join(cwd, "ffmpeg")
                if os.path.exists(target): os.remove(target)
                shutil.move(source, target)
                os.chmod(target, 0o755) # دسترسی اجرا
                found = True
                break
        
        # پاکسازی فایل‌های اضافه
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        
        if found:
            logger.info("✅ FFmpeg installed successfully.")
        else:
            logger.error("❌ FFmpeg binary not found in extracted files.")
            
    except Exception as e:
        logger.error(f"❌ Critical Error installing FFmpeg: {e}")

# اجرای نصب قبل از ایمپورت کتابخانه‌های وابسته
setup_ffmpeg()

# ==========================================
# 📦 ایمپورت‌های اصلی
# ==========================================
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession, StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ پیکربندی ربات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads") # مسیر مطلق
PORT = int(os.environ.get("PORT", 8080))

# متغیرهای وضعیت
login_state = {}
active_files = {}

# ایجاد پوشه دانلود
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# ربات (با حافظه موقت برای جلوگیری از قفل شدن)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# یوزربات (با فایل برای حفظ نشست)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# پلیر
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی و پخش
# ==========================================
async def cleanup(chat_id):
    """پاکسازی فایل‌های مربوط به یک چت"""
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def start_engine():
    """روشن کردن موتور پخش (فقط اگر خاموش باشد)"""
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("✅ Player Engine Started")
    except Exception as e:
        logger.error(f"Engine Start Error: {e}")

async def smart_join(chat_id, stream):
    """مدیریت هوشمند اتصال به کال"""
    try:
        # حالت ۱: تلاش برای جوین شدن
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        err = str(e).lower()
        # حالت ۲: اگر قبلا در کال بودیم، موزیک را عوض کن
        if "already" in err or "group call" in err:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except Exception as change_err:
                # حالت ۳: اگر عوض نشد، لفت بده و دوباره جوین شو
                try:
                    await call_py.leave_group_call(chat_id)
                    await asyncio.sleep(1)
                    await call_py.join_group_call(chat_id, stream)
                except Exception as final_err:
                    raise Exception(f"خطا در اتصال: {final_err}")
        
        # حالت ۴: اگر ویس کال خاموش بود
        elif "no group call" in err or "not found" in err:
            raise Exception("⚠️ **ویس‌کال خاموش است!**\nلطفاً ویس‌کال گروه را روشن کنید.")
        else:
            raise e

@call_py.on_stream_end()
async def on_stream_end(client, update):
    """اتمام پخش"""
    chat_id = update.chat_id
    try:
        await client.leave_group_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 هندلرهای ربات (پنل مدیریت)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender_id = event.sender_id
    
    # جواب به همه (برای تست زنده بودن)
    msg = f"👋 **ربات موزیک فعال است.**\n🆔 آیدی شما: `{sender_id}`"
    
    if sender_id == ADMIN_ID:
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
        await msg.edit(f"❌ محدودیت تلگرام: {e.seconds} ثانیه صبر کنید.")
    except Exception as e: await msg.edit(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await start_engine()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await start_engine()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 هندلرهای یوزربات (پخش)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await start_engine()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        
        # استفاده از مسیر مطلق برای جلوگیری از ارور No video source
        file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4")
        path = await reply.download_media(file=file_path)
        active_files[chat_id] = path
        
        if not path or not os.path.exists(path):
            return await msg.edit("❌ دانلود ناموفق بود.")

        await msg.edit("🎧 اتصال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
        await smart_join(chat_id, AudioVideoPiped(path))
        
        await msg.edit("▶️ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_engine()
    msg = await event.reply("📡 اتصال به لایو...")
    try:
        await cleanup(event.chat_id)
        await smart_join(event.chat_id, AudioVideoPiped(LIVE_URL))
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
    # 1. اجرای وب سرور (بک گراند)
    asyncio.create_task(start_web())

    # 2. اتصال ربات (دستی و مطمئن)
    logger.info("🤖 Bot Connecting...")
    try:
        await bot.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot Started! Waiting for /start")
    except Exception as e:
        logger.error(f"Bot Start Error: {e}")

    # 3. اتصال یوزربات (بدون توقف برنامه)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_engine()
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