import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
import time
import psutil
import gc
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

# کتابخانه‌های نسخه 1.2.9
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

# کتابخانه برای دریافت زمان فایل
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser

import yt_dlp

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraLiteBot")

login_state = {}
active_calls_data = {}
progress_tasks = {}

# ==========================================
# 🧹 مدیریت حافظه
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)
else:
    for f in os.listdir(DOWNLOAD_DIR):
        try: os.remove(os.path.join(DOWNLOAD_DIR, f))
        except: pass

async def force_cleanup(chat_id):
    """پاکسازی کامل"""
    try:
        # متوقف کردن تسک نمایش زمان
        if chat_id in progress_tasks:
            progress_tasks[chat_id].cancel()
            del progress_tasks[chat_id]

        if chat_id in active_calls_data:
            data = active_calls_data[chat_id]
            path = data.get("path")
            if data.get("type") == "file" and path and os.path.exists(path):
                try: os.remove(path)
                except: pass
            del active_calls_data[chat_id]
        
        gc.collect()
    except: pass

# ==========================================
# 🔐 لیست مجاز
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            if ADMIN_ID not in data: data.append(ADMIN_ID)
            return data
    except: return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(chat_list, f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return
    logger.info("⏳ Downloading FFmpeg...")
    try:
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz", "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except: pass

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%"

def get_duration(file_path):
    """دریافت زمان فایل به ثانیه"""
    try:
        metadata = extractMetadata(createParser(file_path))
        if metadata and metadata.has("duration"):
            return metadata.get("duration").seconds
    except: pass
    return 0

def format_seconds(seconds):
    """تبدیل ثانیه به دقیقه:ثانیه"""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

async def get_stream_link(url):
    # کیفیت پایین (240p تا 360p) برای ثبات لایو
    ydl_opts = {
        'format': 'best[height<=360]',
        'noplaylist': True, 
        'quiet': True, 
        'geo_bypass': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live')
    except: return None, None

# ==========================================
# 🔄 نمایشگر زمان (Progress Bar)
# ==========================================
async def progress_loop(chat_id, duration, message):
    """حلقه‌ای برای آپدیت پیام و نمایش زمان پخش"""
    start_time = time.time()
    while chat_id in active_calls_data:
        await asyncio.sleep(15) # هر 15 ثانیه آپدیت کن (برای جلوگیری از فلود)
        
        current_sec = int(time.time() - start_time)
        if duration > 0 and current_sec > duration:
            break
            
        try:
            total_str = format_seconds(duration) if duration > 0 else "∞"
            curr_str = format_seconds(current_sec)
            
            # محاسبه درصد (اگر موزیک باشد)
            percent = ""
            if duration > 0:
                p = int((current_sec / duration) * 100)
                percent = f"({p}%)"
            
            text = (
                f"▶️ **در حال پخش...**\n\n"
                f"⏳ زمان: `{curr_str}` / `{total_str}` {percent}\n"
                f"🎵 وضعیت: پایدار"
            )
            await message.edit(text)
        except: pass

# ==========================================
# 🎧 موتور استریم (اصلاح شده)
# ==========================================
async def start_music(chat_id, file_path):
    """مخصوص پخش موزیک (بدون باگ کاور)"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # پارامتر جادویی -vn: ویدیو را کاملاً حذف می‌کند تا کاور باعث کرش نشود
    ffmpeg_params = "-vn"

    stream = MediaStream(
        file_path,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=None, # ویدیو خاموش
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است!")
        raise e

async def start_live(chat_id, url):
    """مخصوص پخش لایو (FPS کم برای کاهش لگ)"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # پارامترهای حیاتی برای سرورهای ضعیف:
    # -r 20: فریم ریت را روی 20 قفل می‌کند (استاندارد 30 است). این فشار CPU را کم می‌کند.
    # -preset ultrafast: سریعترین حالت انکود.
    # -tune zerolatency: کاهش تاخیر برای لایو.
    ffmpeg_params = "-r 20 -preset ultrafast -tune zerolatency"

    stream = MediaStream(
        url,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p, # کیفیت تصویر استاندارد
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است!")
        raise e

# ==========================================
# 👮‍♂️ دسترسی‌ها
# ==========================================
async def check_permission(event):
    if event.sender_id == ADMIN_ID: return True
    if event.out: return True
    if event.chat_id not in ALLOWED_CHATS: return False
    
    # کانال همیشه مجاز
    if event.is_channel and (not event.is_group): return True

    try:
        if event.sender_id == event.chat_id or event.sender_id == 1087968824: return True
        perm = await user_client.get_permissions(event.chat_id, event.sender_id)
        if perm.is_admin or perm.is_creator: return True
    except: pass
    return False

# ==========================================
# 🤖 ربات لاگین
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    conn = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    chats_list = ""
    if user_client.is_connected():
        c = 0
        for cid in ALLOWED_CHATS:
            if cid == ADMIN_ID: continue
            try:
                e = await user_client.get_entity(cid)
                name = getattr(e, 'title', str(cid))
                chats_list += f"{c+1}. **{name}**\n"
            except: chats_list += f"{c+1}. `{cid}`\n"
            c+=1
        if c==0: chats_list = "لیست خالی."
    else: chats_list = "⚠️ یوزربات قطع است."

    msg = (
        f"👋 **پنل مدیریت ربات (Ultra Lite)**\n"
        f"وضعیت: {conn}\n\n"
        f"🔐 **لاگین:** `/phone`, `/code`, `/password`\n\n"
        f"📡 **دستورات:**\n"
        f"➕ `/add` | ➖ `/del`\n"
        f"🎵 `/play` (فقط موزیک)\n"
        f"🔴 `/live` (پخش زنده)\n"
        f"⏹ `/stop`\n\n"
        f"📋 **لیست مجاز:**\n{chats_list}"
    )
    await event.reply(msg)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 هندلرها (Userbot)
# ==========================================

# 1. افزودن
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target = event.pattern_match.group(2)
    chat_id = event.chat_id
    if target:
        try:
            entity = await user_client.get_entity(target)
            chat_id = entity.id
        except: return await event.reply("❌ نامعتبر.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{chat_id}` مجاز شد.")
    else: await event.reply("⚠️ قبلاً بود.")

# 2. حذف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")

# 3. پینگ
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_h(event):
    if not await check_permission(event): return
    start = time.time()
    msg = await event.reply("⏳")
    await user_client.get_me()
    ping = round((time.time() - start) * 1000)
    info = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n{info}")

# 4. پخش موزیک (فقط صوتی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_h(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    reply = await event.get_reply_message()
    
    # 🚫 جلوگیری از پخش ویدیو
    if reply and reply.video:
        return await event.reply("❌ **پخش فایل ویدیویی مجاز نیست!**\nفقط موزیک و لایو پشتیبانی می‌شود.")

    if not reply or not reply.audio:
        return await event.reply("❌ لطفاً روی یک آهنگ ریپلای کنید.")

    await force_cleanup(chat_id)
    status = await event.reply("📥 **دانلود موزیک...**")
    
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp3"))
        if not path: return await status.edit("❌ دانلود نشد.")
        
        # دریافت زمان آهنگ برای نمایش
        duration = get_duration(path)
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        
        await status.edit("🚀 **اتصال صوتی...**")
        
        # استفاده از تابع مخصوص موزیک
        await start_music(chat_id, path)
        
        await status.edit(f"🎵 **پخش موزیک شروع شد.**\n⏱ زمان: `{format_seconds(duration)}`")
        
        # شروع نمایش زمان
        task = asyncio.create_task(progress_loop(chat_id, duration, status))
        progress_tasks[chat_id] = task

    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 5. پخش لایو
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    if not await check_permission(event): return
    try: await event.delete()
    except: pass

    chat_id = event.chat_id
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    title = "ایران اینترنشنال"

    await force_cleanup(chat_id)
    status = await user_client.send_message(chat_id, "📡 **لینک یابی...**")

    try:
        if url_arg:
            u, t = await get_stream_link(url_arg)
            if u:
                final_url = u
                title = t or "Stream"
            else:
                final_url = url_arg
                title = "لینک مستقیم"

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        
        # استفاده از تابع مخصوص لایو (FPS 20)
        await start_live(chat_id, final_url)
        
        await status.edit(f"🔴 **پخش زنده:**\n📺 `{title}`\n⚡️ حالت: FPS 20 (کاهش فشار سرور)")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 6. توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if not await check_permission(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup(event.chat_id)
        await event.reply("⏹ قطع شد.")
    except: pass

@call_py.on_stream_end()
async def on_end(client, update):
    try: await client.leave_group_call(update.chat_id)
    except: pass
    await force_cleanup(update.chat_id)

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Running (Lite Mode)"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("🚀 Starting...")
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): await call_py.start()
    except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())