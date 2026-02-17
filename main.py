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
from telethon import TelegramClient, events, functions
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Chat, User

# کتابخانه‌های نسخه 1.2.9 (پایدار و تست شده)
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

# لینک پیش‌فرض (ایران اینترنشنال)
DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("ManagerBot")

login_state = {}
active_calls_data = {}

# ==========================================
# 🧹 مدیریت حافظه (Memory Management)
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)
else:
    for f in os.listdir(DOWNLOAD_DIR):
        try: os.remove(os.path.join(DOWNLOAD_DIR, f))
        except: pass

async def force_cleanup(chat_id):
    """پاکسازی تهاجمی رم و دیسک"""
    try:
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
# 🔐 لیست مجاز (Database)
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
# 📊 توابع هسته (بدون تغییر)
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%"

async def get_stream_link(url):
    ydl_opts = {
        'format': 'best[height<=360]', # بهینه سازی شده
        'noplaylist': True, 
        'quiet': True, 
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live')
    except: return None, None

async def start_stream_v1(chat_id, source):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p 
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ **ویس‌کال خاموش است!** لطفاً روشن کنید.")
        raise e

# ==========================================
# 👮‍♂️ سیستم دسترسی هوشمند (Smart Permission)
# ==========================================
async def check_permission(event):
    # 1. مالک اصلی همیشه مجاز است
    if event.sender_id == ADMIN_ID: return True
    
    # 2. خود یوزربات (پیام‌های خروجی) همیشه مجاز است
    if event.out: return True

    # 3. بررسی اینکه آیا چت در لیست مجاز (/add شده) هست؟
    if event.chat_id not in ALLOWED_CHATS: return False

    # 4. تشخیص کانال (Channel):
    # در کانال‌ها، هر پیامی که می‌آید معتبر است چون فقط ادمین حق پست گذاشتن دارد.
    # پس اگر چت کانال بود و در لیست مجاز بود، دستور اجرا شود.
    if event.is_channel and (not event.is_group):
        return True

    # 5. تشخیص گروه (Group):
    # در گروه، باید چک کنیم کاربر ادمین است یا خیر.
    try:
        # ادمین‌های مخفی (Anonymous) معمولاً با آیدی گروه پیام می‌فرستند
        # آیدی 1087968824 مربوط به GroupAnonymousBot است
        if event.sender_id == event.chat_id or event.sender_id == 1087968824:
            return True

        # چک کردن سطح دسترسی کاربر عادی
        perm = await user_client.get_permissions(event.chat_id, event.sender_id)
        if perm.is_admin or perm.is_creator:
            return True
    except: pass
    
    return False

# ==========================================
# 🤖 ربات لاگین (با لیست کامل)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    conn = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    # ساخت لیست چت‌های مجاز
    chats_list_text = ""
    if user_client.is_connected():
        count = 0
        for chat_id in ALLOWED_CHATS:
            if chat_id == ADMIN_ID: continue
            try:
                entity = await user_client.get_entity(chat_id)
                name = getattr(entity, 'title', 'Unknown')
                chats_list_text += f"{count+1}. **{name}** (`{chat_id}`)\n"
                count += 1
            except:
                chats_list_text += f"{count+1}. `ID: {chat_id}` (نامشخص)\n"
                count += 1
        if count == 0: chats_list_text = "لیست خالی است."
    else:
        chats_list_text = "⚠️ برای دیدن لیست، یوزربات باید وصل باشد."

    msg = (
        f"👋 **سلام رئیس! خوش اومدی به پنل مدیریت.**\n"
        f"وضعیت یوزربات: {conn}\n\n"
        f"🔐 **آموزش لاگین:**\n"
        f"1. دستور `/phone +989...` رو بزن.\n"
        f"2. کد اومده رو با `/code 12345` بزن.\n"
        f"3. اگه رمز دوم داری `/password ...` بزن.\n\n"
        f"📡 **دستورات یوزربات (توی کانال/گروه):**\n"
        f"➕ `افزودن` یا `/add` (فعالسازی چت)\n"
        f"➖ `حذف` یا `/del` (غیرفعالسازی چت)\n"
        f"▶️ `پخش` یا `/play` (ریپلای روی آهنگ/فیلم)\n"
        f"🔴 `لایو` یا `/live` (پخش زنده شبکه)\n"
        f"🔗 `لایو لینک` (پخش زنده لینک دلخواه)\n"
        f"⏹ `قطع` یا `/stop`\n\n"
        f"📋 **لیست چت‌های مجاز ({len(ALLOWED_CHATS)-1} مورد):**\n"
        f"{chats_list_text}"
    )
    await event.reply(msg)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد رو بفرست: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...`")
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
# 👤 هندلرهای یوزربات
# ==========================================

# 1. افزودن (Add)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target = event.pattern_match.group(2)
    chat_id = event.chat_id
    name = "این چت"
    
    if target:
        try:
            entity = await user_client.get_entity(target)
            chat_id = entity.id
            name = getattr(entity, 'title', str(chat_id))
        except: return await event.reply("❌ لینک نامعتبر.")
    else:
        chat = await event.get_chat()
        name = getattr(chat, 'title', str(chat_id))
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ **{name}** به لیست مجاز اضافه شد.\nحالا ادمین‌ها می‌تونن دستور بدن.")
    else:
        await event.reply("⚠️ قبلاً اضافه شده بود.")

# 2. حذف (Del)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 از لیست مجاز حذف شد.")
    else:
        await event.reply("⚠️ اینجا مجاز نبود.")

# 3. پینگ (Ping)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_h(event):
    if not await check_permission(event): return
    start = time.time()
    msg = await event.reply("⏳")
    await user_client.get_me()
    ping = round((time.time() - start) * 1000)
    info = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n{info}")

# 4. پخش فایل (Play)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_h(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ ریپلای کن.")

    await force_cleanup(chat_id)
    status = await event.reply("📥 **دانلود فایل...**")
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        if not path: return await status.edit("❌ دانلود نشد.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        await status.edit("🚀 **اتصال به ویس‌کال...**")
        await start_stream_v1(chat_id, path)
        await status.edit("▶️ **پخش شروع شد.**")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 5. پخش لایو (Live)
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
        await start_stream_v1(chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده:**\n📺 `{title}`\n⚡️ بهینه‌سازی شده")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 6. توقف (Stop)
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
    app.router.add_get("/", lambda r: web.Response(text="Bot Running (Managed Mode)"))
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