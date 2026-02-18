import os
import asyncio
import logging
import json
import tarfile
import shutil
import time
import psutil
import gc
import urllib.request
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError

# کتابخانه‌های نسخه 1.2.9
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

# لینک پیش‌فرض
DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("LiveBotOnly")

login_state = {}

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
# 🛠 نصب FFmpeg (بدون wget)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Downloading FFmpeg...")
    try:
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        urllib.request.urlretrieve(url, "ffmpeg.tar.xz")
        
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
    try:
        import cryptg
        speed = "🚀 Ultra (Cryptg)"
    except:
        speed = "⚠️ Normal"
    return f"🧠 RAM: {mem.percent}%\n⚡️ {speed}"

async def start_live(chat_id, stream_url):
    """
    موتور پخش فقط مخصوص لایو (M3U8)
    """
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات حیاتی برای جلوگیری از لگ در لایو
    # -reconnect 1: اگر نت قطع شد وصل شو
    # -tune zerolatency: حذف بافر
    ffmpeg_params = (
        "-preset ultrafast "
        "-tune zerolatency "
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5"
    )

    stream = MediaStream(
        stream_url,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1.5)
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است!")
        raise e

# ==========================================
# 🤖 ربات لاگین (مدیریت)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    conn = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(
        f"📺 **پنل مدیریت لایو**\nوضعیت: {conn}\n\n"
        f"1. `/add` - افزودن گروه\n"
        f"2. `/del` - حذف گروه\n"
        f"3. `/live` - پخش لایو پیش‌فرض\n"
        f"4. `/live [لینک]` - پخش لینک دستی\n"
        f"5. `/stop` - قطع پخش\n\n"
        f"🔐 لاگین: `/phone`, `/code`, `/password`"
    )

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
# 👤 هندلرها (فقط لایو و ادد)
# ==========================================

# 1. افزودن (فقط ادمین اصلی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target_id = event.chat_id
    if event.pattern_match.group(2):
        try:
            entity = await user_client.get_entity(event.pattern_match.group(2))
            target_id = entity.id
        except: return await event.reply("❌ آیدی نامعتبر.")
    
    if target_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(target_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ اینجا ({target_id}) به لیست مجاز اضافه شد.")
    else:
        await event.reply("⚠️ قبلاً اضافه شده.")

# 2. حذف (فقط ادمین اصلی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")

# 3. پخش لایو (با سیستم امنیتی فحاش)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    chat_id = event.chat_id
    
    # === بررسی دسترسی ===
    if chat_id not in ALLOWED_CHATS:
        try:
            await event.reply("🖕 **کصکش کیرم تو گروهت! اینجا مجاز نیست بای.**")
            await user_client.delete_dialog(chat_id) # لفت دادن
        except: pass
        return
    # ====================

    # حذف پیام حاوی لینک (برای امنیت و تمیزی)
    try: await event.delete()
    except: pass

    url_arg = event.pattern_match.group(2)
    status = await user_client.send_message(chat_id, "📡 **در حال اتصال...**")

    try:
        if url_arg:
            final_url = url_arg # لینک دستی
            title = "Custom Stream"
        else:
            final_url = DEFAULT_LIVE_URL # لینک پیش‌فرض
            title = "Default TV"

        await start_live(chat_id, final_url)
        await status.edit(f"🔴 **پخش زنده:** `{title}`\n⚡️ **کیفیت:** عالی (بدون لگ)")
        
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")

# 4. توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if event.chat_id not in ALLOWED_CHATS: return
    try:
        await call_py.leave_group_call(event.chat_id)
        await event.reply("⏹ قطع شد.")
        gc.collect()
    except: pass

# 5. پینگ
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ)'))
async def ping_h(event):
    if event.chat_id not in ALLOWED_CHATS: return
    start = time.time()
    msg = await event.reply("⏳")
    ping = round((time.time() - start) * 1000)
    sys = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n{sys}")

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Live Bot Running"))
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