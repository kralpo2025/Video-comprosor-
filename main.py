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

# لینک مستقیم سرور پخش ایران اینترنشنال (بدون نیاز به یوتیوب)
# این لینک پایدارترین لینک موجود است
DIRECT_LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

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
        logger.error(f"FFmpeg Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع اصلی
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
    """استخراج لینک استریم از یوتیوب یا سایت‌های دیگر"""
    # اگر لینک سایت ایران اینترنشنال بود، لینک مستقیم را برگردان
    if "iranintl" in url:
        return DIRECT_LIVE_URL, "Iran International (Direct)"

    ydl_opts = {
        'format': 'best[height<=360]/best', # اجبار به کیفیت پایین
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
    موتور پخش فوق بهینه شده برای جلوگیری از لگ
    """
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # ========================================================
    # ⚡️ تنظیمات جادویی برای رفع لگ (Magic Config)
    # ========================================================
    # ما با استفاده از ffmpeg_parameters رزولوشن را به زور
    # روی 640x360 و فریم ریت را روی 24 تنظیم میکنیم.
    # همچنین preset ultrafast فشار روی CPU را کم میکند.
    # ========================================================
    
    ffmpeg_params = (
        f"-ss {start_time} "
        "-vf scale=640:360 "  # تغییر سایز اجباری به 360p
        "-r 24 "              # کاهش فریم ریت به 24
        "-preset ultrafast "  # افزایش سرعت پردازش (کاهش کیفیت ولی رفع لگ)
        "-tune zerolatency "  # کاهش تاخیر
        "-b:v 500k"           # محدود کردن بیت ریت تصویر
    ) if start_time > 0 else (
        "-vf scale=640:360 "
        "-r 24 "
        "-preset ultrafast "
        "-tune zerolatency "
        "-b:v 500k"
    )

    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, # صدای متوسط کافیه
        video_parameters=VideoQuality.SD_480p, # این پارامتر کلی است، تنظیمات اصلی در بالا اعمال شد
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        # اگر در کال هستیم، استریم را عوض کن (برای Seek بدون خروج)
        await call_py.change_stream_call(chat_id, stream)
    except Exception as e:
        # اگر نتوانست عوض کند (مثلا کال قطع بود)، جوین شو
        try:
            await call_py.join_group_call(chat_id, stream)
        except Exception as join_err:
             # اگر خطای already joined داد یعنی باگ خورده، لفت بده دوباره بیا
            if "already" in str(join_err):
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(0.5)
                await call_py.join_group_call(chat_id, stream)
            else:
                raise join_err

# ==========================================
# 🤖 ربات
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    conn = "🟢" if user_client.is_connected() and await user_client.is_user_authorized() else "🔴"
    
    await event.reply(
        f"👋 **پنل مدیریت پیشرفته**\n"
        f"وضعیت یوزربات: {conn}\n\n"
        f"1️⃣ لاگین: `/phone` | `/code` | `/password`\n"
        f"2️⃣ پخش فایل: `/ply` (ریپلای)\n"
        f"3️⃣ پخش زنده: `/live` (ایران اینترنشنال)\n"
        f"4️⃣ لینک دلخواه: `/live [link]`"
    )

# --- لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def login_ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(ph)
        login_state.update({'phone': ph, 'hash': r.phone_code_hash})
        await event.reply("✅ کد: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def login_co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ پسورد: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def login_pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 یوزربات
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def on_play(event):
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.edit("❌ مدیا کو؟")
    
    chat_id = event.chat_id
    status = await event.reply("📥 **دانلود و بهینه‌سازی...**")
    await cleanup(chat_id)
    
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_calls_data[chat_id] = {"path": path, "type": "file", "position": 0}
        
        await status.edit("🚀 **شروع پخش (بهینه شده)...**")
        await start_stream_engine(chat_id, path)
        await status.delete()
        
        try: await bot.send_message(chat_id, f"▶️ **پخش فایل**\n📂 `{os.path.basename(path)}`", buttons=get_buttons(False))
        except: pass
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def on_live(event):
    url = event.pattern_match.group(1).strip()
    title = "لینک دلخواه"
    
    # اگر لینک خالی بود یا سایت ایران اینترنشنال بود
    if not url or "iranintl" in url:
        url = DIRECT_LIVE_URL
        title = "ایران اینترنشنال (زنده)"
    
    chat_id = event.chat_id
    status = await event.reply("📡 **اتصال به سرور پخش...**")
    await cleanup(chat_id)
    
    try:
        # اگر لینک مستقیم نبود، با yt-dlp بگیر
        if url != DIRECT_LIVE_URL:
             s_url, s_title = await get_stream_link(url)
             if not s_url: return await status.edit("❌ لینک نامعتبر.")
             url = s_url
             title = s_title

        active_calls_data[chat_id] = {"path": url, "type": "live", "position": 0}
        
        await status.edit(f"🔴 **پخش زنده: {title}**")
        await start_stream_engine(chat_id, url)
        await status.delete()
        
        try: await bot.send_message(chat_id, f"🔴 **پخش زنده**\n📺 {title}", buttons=get_buttons(True))
        except: pass
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 دکمه‌ها
# ==========================================
@bot.on(events.CallbackQuery)
async def on_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode()
    info = active_calls_data.get(chat_id)
    
    if not info and data != 'stop': return await event.answer("⚠️ پخش وجود ندارد.", alert=True)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ پایان پخش.")
            
        elif data == 'toggle':
            try: await call_py.resume_stream(chat_id)
            except: await call_py.pause_stream(chat_id)
            await event.answer("⏯")
            
        elif 'fw_' in data or 'rw_' in data:
            if info['type'] == 'live': return await event.answer("🚫 لایو عقب/جلو نمیشود.", alert=True)
            
            # ذخیره پوزیشن جدید
            sec = 30 if 'fw_' in data else -30
            new_pos = max(0, info['position'] + sec)
            info['position'] = new_pos
            
            await event.answer(f"⏳ پرش به {new_pos}s")
            # تغییر استریم بدون خروج از کال
            await start_stream_engine(chat_id, info['path'], start_time=new_pos)
            
    except Exception as e:
        logger.error(f"CB: {e}")

@call_py.on_stream_end()
async def on_end(client, update):
    await client.leave_group_call(update.chat_id)
    await cleanup(update.chat_id)

# ==========================================
# 🌐 سرور
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