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

# لینک‌های ثابت و پایدار (منبع ParsaTV و سرور اصلی)
LIVE_CHANNELS = {
    "iranintl": "https://nix-cdn.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8",
    "parsatv": "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8" 
}

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای وضعیت
login_state = {}
active_calls_data = {}

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🛠 نصب FFmpeg
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
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی
# ==========================================

async def cleanup(chat_id):
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def get_stream_link(url):
    """
    سعی میکند لینک مستقیم m3u8 را پیدا کند.
    اگر لینک پارسا تی‌وی یا ایران اینترنشنال باشد، از لینک ثابت استفاده میکند.
    """
    # 1. تشخیص لینک‌های معروف (بدون معطلی yt-dlp)
    if "parsatv" in url or "iranintl" in url:
        return LIVE_CHANNELS["iranintl"], "Iran International (ParsaTV Source)"

    # 2. تلاش برای استخراج با yt-dlp برای سایر لینک‌ها
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"DL Error: {e}")
        return None, None

def get_buttons(is_live=False):
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
    """
    اجرای موزیک/ویدیو در ویس کال.
    ما اینجا از پارامترهای دستی استفاده نمیکنیم تا از کرش جلوگیری کنیم.
    کیفیت را روی SD_480p میگذاریم که کتابخانه خودش هندل کند.
    """
    
    # اطمینان از روشن بودن موتور
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # پارامتر seek فقط برای فایل‌های لوکال است، نه لایو
    ffmpeg_params = f"-ss {start_time}" if start_time > 0 else ""

    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,  # کیفیت صدای متوسط (بهینه)
        video_parameters=VideoQuality.SD_480p, # کیفیت تصویر استاندارد (بدون لگ)
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        # متد leave و سپس join مطمئن‌ترین روش برای جلوگیری از باگ است
        # تلاش برای change_stream گاهی باعث کرش می‌شود
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(0.5) # وقفه کوتاه برای آزادسازی منابع
        except:
            pass
            
        await call_py.join_group_call(chat_id, stream)
        
    except Exception as e:
        logger.error(f"Stream Error: {e}")
        # اگر ارور داد که "در حال حاضر در تماس نیستید"، دوباره تلاش کن
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال گروه خاموش است! روشن کنید.")
        raise e

# ==========================================
# 🤖 دستورات ربات (پنل ادمین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    status = "🟢 وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "🔴 قطع"
    
    await event.reply(
        f"👋 **پنل مدیریت ربات**\n"
        f"وضعیت یوزربات: {status}\n\n"
        f"1️⃣ لاگین: `/phone` | `/code` | `/password`\n"
        f"2️⃣ پخش فایل: `/ply` (ریپلای روی مدیا)\n"
        f"3️⃣ پخش زنده (ایران اینترنشنال/پارسا تی‌وی): `/live`\n\n"
        f"⚠️ **نکته:** ربات فقط واسط است. پخش توسط اکانت شما انجام می‌شود."
    )

# --- پروسه لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد را بفرستید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ پسورد: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 دستورات یوزربات (اجرا کننده)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def on_ply(event):
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.edit("❌ ریپلای کو؟")
    
    chat_id = event.chat_id
    status = await event.reply("📥 **دانلود فایل...**")
    await cleanup(chat_id)
    
    try:
        dl_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4")
        path = await reply.download_media(file=dl_path)
        
        # بررسی اینکه فایل واقعا دانلود شده باشد
        if not path or os.path.getsize(path) == 0:
            return await status.edit("❌ دانلود ناموفق بود.")

        active_calls_data[chat_id] = {"path": path, "type": "file", "position": 0}
        
        await status.edit("🎧 **اتصال به ویس‌کال...**")
        await start_stream_engine(chat_id, path)
        await status.delete()
        
        try: await bot.send_message(chat_id, f"▶️ **پخش فایل شروع شد**", buttons=get_buttons(False))
        except: pass

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def on_live(event):
    url = event.pattern_match.group(1).strip()
    
    # اگر لینک خالی بود یا مربوط به پارسا تی‌وی/ایران اینترنشنال بود
    if not url or "parsatv" in url or "iranintl" in url:
        url = LIVE_CHANNELS["iranintl"]
        title = "Iran International (Live)"
    else:
        title = "Live Stream"

    chat_id = event.chat_id
    status = await event.reply("📡 **دریافت استریم...**")
    await cleanup(chat_id)
    
    try:
        # اگر لینک مستقیم نبود (لینک یوتیوب و ...)، تبدیلش کن
        if url not in LIVE_CHANNELS.values():
            s_url, s_title = await get_stream_link(url)
            if not s_url: return await status.edit("❌ لینک قابل پخش یافت نشد.")
            url = s_url
            title = s_title

        active_calls_data[chat_id] = {"path": url, "type": "live", "position": 0}
        
        await status.edit(f"🔴 **شروع پخش زنده: {title}**")
        
        # استارت انجین
        await start_stream_engine(chat_id, url)
        
        await status.delete()
        try: await bot.send_message(chat_id, f"🔴 **پخش زنده فعال شد**", buttons=get_buttons(True))
        except: pass
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 هندلر دکمه‌ها
# ==========================================
@bot.on(events.CallbackQuery)
async def on_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode()
    info = active_calls_data.get(chat_id)
    
    if not info and data != 'stop': return await event.answer("⚠️ پخش فعال نیست.", alert=True)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ **متوقف شد.**")
            
        elif data == 'toggle':
            # پایتون تلگرام کالز گاهی روی ریزوم گیر میکند، این ترای اکسپت ضروری است
            try: await call_py.resume_stream(chat_id)
            except: await call_py.pause_stream(chat_id)
            await event.answer("⏯")
            
        elif 'fw_' in data or 'rw_' in data:
            if info['type'] == 'live': return await event.answer("🚫 در پخش زنده نمیشود.", alert=True)
            
            sec = 30 if 'fw_' in data else -30
            new_pos = max(0, info['position'] + sec)
            info['position'] = new_pos
            
            await event.answer(f"⏳ پرش به {new_pos} ثانیه...")
            # شروع مجدد پخش از ثانیه جدید
            await start_stream_engine(chat_id, info['path'], start_time=new_pos)
            
    except Exception as e:
        logger.error(f"CB Error: {e}")
        # اگر خطا داد احتمالا ویس بسته شده
        await event.answer("خطا در ارتباط با ویس کال", alert=True)

@call_py.on_stream_end()
async def on_end(client, update):
    await client.leave_group_call(update.chat_id)
    await cleanup(update.chat_id)

# ==========================================
# 🌐 وب سرور
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): await call_py.start()
    except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())