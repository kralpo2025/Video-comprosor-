import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
import sys
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality
import yt_dlp

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

# مسیرها و پورت
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

# لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای وضعیت
login_state = {}
active_calls_data = {}

# ساخت پوشه دانلود
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🛠 نصب FFmpeg (مخصوص Render)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    if shutil.which("ffmpeg"):
        return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except Exception as e:
        logger.error(f"FFmpeg Install Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# ربات: فقط برای مدیریت و ارسال دکمه
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# یوزربات: برای دانلود و پخش (فایل سشن روی دیسک ذخیره می‌شود)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# موتور پخش
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی
# ==========================================

async def cleanup(chat_id):
    """پاکسازی فایل‌ها و آزادسازی حافظه"""
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        
        # حذف فایل اگر وجود داشته باشد
        if data.get("type") == "file" and path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"🗑 Deleted file: {path}")
            except Exception as e:
                logger.error(f"Cleanup Error: {e}")
        
        del active_calls_data[chat_id]

async def get_stream_link(url):
    """گرفتن لینک مستقیم استریم با کیفیت مناسب"""
    # فرمت worstvideo برای کاهش مصرف رم سرور، صدا بهترین کیفیت
    ydl_opts = {
        'format': 'best[height<=480]/best',
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"Yt-dlp Error: {e}")
        return None, None

def get_buttons(is_live=False):
    """دکمه‌های شیشه‌ای"""
    if is_live:
        return [[Button.inline("❌ توقف پخش", data=b'stop')]]
    
    return [
        [
            Button.inline("⏪ 30s", data=b'rw_30'),
            Button.inline("⏸/▶️", data=b'toggle'),
            Button.inline("⏩ 30s", data=b'fw_30')
        ],
        [Button.inline("❌ توقف و حذف", data=b'stop')]
    ]

async def start_stream_engine(chat_id, source, start_time=0):
    """مدیریت اتصال به ویس‌کال"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیم کیفیت روی 480p برای جلوگیری از لگ
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=f"-ss {start_time}" if start_time > 0 else ""
    )

    try:
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        err = str(e).lower()
        if "already" in err or "group call" in err:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except:
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream)
        elif "no group call" in err:
            raise Exception("⚠️ ویس‌کال گروه خاموش است! روشن کنید.")
        else:
            raise e

# ==========================================
# 🤖 ربات منیجر (دستورات ادمین و لاگین)
# ==========================================

@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    is_connected = False
    try:
        if user_client.is_connected() and await user_client.is_user_authorized():
            is_connected = True
    except: pass

    status = "🟢 **متصل**" if is_connected else "🔴 **قطع**"
    
    text = (
        f"👋 **مدیریت ربات موزیک**\n"
        f"وضعیت اکانت: {status}\n\n"
        f"📋 **راهنما:**\n"
        f"1️⃣ برای لاگین از دستورات زیر استفاده کن:\n"
        f"`/phone +98...`\n`/code 12345`\n`/password ...`\n\n"
        f"2️⃣ بعد از اتصال، در گروه:\n"
        f"- ریپلای روی فایل: `/ply`\n"
        f"- پخش زنده: `/live`\n\n"
        f"⚠️ **نکته:** ربات (همین بات) باید در گروه **ادمین** باشد تا دکمه‌ها کار کنند."
    )
    await event.reply(text)

# --- پروسه لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def login_phone(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        if not user_client.is_connected(): await user_client.connect()
        sent = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = sent.phone_code_hash
        await event.reply("✅ کد را بفرست: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def login_code(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!** حالا برو تو گروه دستور بده.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم داری: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def login_pass(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود تکمیل شد.**")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 یوزربات (اجرای مدیا)
# ==========================================

@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def user_play(event):
    """پخش فایل ریپلای شده"""
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.edit("❌ ریپلای روی فایل الزامی است.")

    chat_id = event.chat_id
    status = await event.reply("📥 **دانلود...**")
    await cleanup(chat_id)

    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        if not path: return await status.edit("❌ دانلود نشد.")

        active_calls_data[chat_id] = {"path": path, "type": "file", "position": 0}

        await status.edit("🎧 **اتصال...**")
        await start_stream_engine(chat_id, path)
        await status.delete()

        # تلاش برای ارسال دکمه توسط ربات
        try:
            await bot.send_message(
                chat_id, 
                f"▶️ **پخش شروع شد**\n📂 `{os.path.basename(path)}`",
                buttons=get_buttons(False)
            )
        except:
            await event.reply("⚠️ ربات در گروه نیست! دکمه‌ها نمایش داده نمی‌شوند.")

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def user_live(event):
    """پخش زنده"""
    url = event.pattern_match.group(1).strip()
    # لینک پیش‌فرض
    if not url:
        url = "https://www.youtube.com/live/A92pqZQAsm8?si=LMguHUxEkBAZRNWX"
    
    chat_id = event.chat_id
    status = await event.reply("📡 **دریافت لینک...**")
    await cleanup(chat_id)

    try:
        stream_url, title = await get_stream_link(url)
        if not stream_url: return await status.edit("❌ لینک نامعتبر.")

        active_calls_data[chat_id] = {"path": stream_url, "type": "live", "position": 0}

        await status.edit(f"🔴 **پخش: {title}**")
        await start_stream_engine(chat_id, stream_url)
        await status.delete()

        try:
            await bot.send_message(
                chat_id, 
                f"🔴 **پخش زنده**\n📺 {title}",
                buttons=get_buttons(True)
            )
        except: pass

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 کالبک دکمه‌ها
# ==========================================
@bot.on(events.CallbackQuery)
async def callback(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode('utf-8')
    info = active_calls_data.get(chat_id)

    if not info and data != 'stop':
        return await event.answer("⚠️ پخش فعال نیست.", alert=True)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ **متوقف شد.**", buttons=None)
        
        elif data == 'toggle':
            try: await call_py.resume_stream(chat_id)
            except: await call_py.pause_stream(chat_id)
            await event.answer("تغییر وضعیت")
        
        elif 'fw_' in data or 'rw_' in data:
            if info['type'] == 'live': return await event.answer("لایو عقب/جلو نمیشود!", alert=True)
            
            sec = 30 if 'fw_' in data else -30
            new_pos = max(0, info['position'] + sec)
            info['position'] = new_pos
            
            await event.answer(f"پرش به {new_pos}s")
            await start_stream_engine(chat_id, info['path'], start_time=new_pos)

    except Exception as e:
        logger.error(f"CB Error: {e}")

@call_py.on_stream_end()
async def stream_end(client, update):
    await client.leave_group_call(update.chat_id)
    await cleanup(update.chat_id)

# ==========================================
# 🌐 وب‌سرور و اجرا
# ==========================================
async def web_handler(r):
    return web.Response(text="Bot Running")

async def main():
    # وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    asyncio.create_task(site.start())
    logger.info("🌍 Web Server Started")

    # استارت ربات
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("🤖 Bot Started")

    # تلاش برای اتصال یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Connected")
            await call_py.start()
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())