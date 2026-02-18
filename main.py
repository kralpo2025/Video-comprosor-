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
import random
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Chat, User

# کتابخانه‌های نسخه 1.2.9 (لگاسی)
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

# لینک پیش‌فرض که گفتید دستی کار می‌کند
DEFAULT_LIVE_URL = "https://fo-live.iraninternational.com/out/v1/ad74279027874747805d7621c5484828/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("LegacyStreamer")

login_state = {}

# ==========================================
# 🔐 مدیریت لیست مجاز
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            return [int(i) for i in data]
    except: return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(list(set(chat_list)), f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg (کد تضمینی)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return
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
    cpu = psutil.cpu_percent()
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n🖥 CPU: {cpu}%"

async def get_stream_link(url):
    ydl_opts = {'format': 'best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live')
    except: return url, "Live Stream"

async def start_stream_v1(chat_id, source):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass
    
    # پخش مستقیم بدون دستکاری (طبق درخواست شما برای سرعت بیشتر)
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p 
    )

    try: await call_py.leave_group_call(chat_id)
    except: pass
    await asyncio.sleep(1)
    await call_py.join_group_call(chat_id, stream)

# ==========================================
# 👮‍♂️ سیستم امنیتی سخت‌گیرانه
# ==========================================
async def security_check(event):
    chat_id = event.chat_id
    if chat_id in ALLOWED_CHATS:
        return True
    
    try:
        await event.reply("💢 مرتیکه کسکش! این چت مجاز نیست. ادمینت غلط کرده منو آورده اینجا. سیکتیر!")
        await user_client.delete_dialog(chat_id) 
    except: pass
    return False

# ==========================================
# 🤬 آنتی‌مزاحم (فحش در پی‌وی)
# ==========================================
@user_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def anti_annoying(event):
    if event.sender_id == ADMIN_ID: return
    
    insults = [
        "کون ده با تو چیکار داری؟ گمشو از پیوی بیرون.",
        "مرتیکه جنده زاده، دفعه آخرت باشه به این اکانت پیام میدی.",
        "سیکتیر کن تا نریدم به هیکلت بی شرف.",
        "کونی مگه نگفتم اینجا نیای؟ گمشو ننه جنده.",
        "خایه‌مالو سگ بگاد، برو تا بلاکت نکردم کسکش."
    ]
    
    try:
        await event.reply(random.choice(insults))
        await asyncio.sleep(1)
        # پاک کردن دوطرفه چت
        await user_client.delete_dialog(event.sender_id, revoke=True)
    except: pass

# ==========================================
# 🤖 ربات لاگین (Bot API)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    await event.reply("🤖 سیستم مدیریت استریم آنلاین است.")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ یوزربات متصل شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...` ")
    except Exception as e: await event.reply(f"❌ {e}")

# افزودن از طریق ربات با لینک یا ایدی
@bot.on(events.NewMessage(pattern='/add (.+)'))
async def bot_add(event):
    if event.sender_id != ADMIN_ID: return
    target = event.pattern_match.group(1).strip()
    try:
        e = await user_client.get_entity(target)
        if e.id not in ALLOWED_CHATS:
            ALLOWED_CHATS.append(e.id)
            save_allowed_chats(ALLOWED_CHATS)
            await event.reply(f"✅ چت `{e.id}` مجاز شد.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 👤 هندلرهای یوزربات (Userbot)
# ==========================================

# افزودن در گروه (توسط خود یوزربات)
@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?:\s+(.+))?'))
async def user_add_h(event):
    # فقط اگر فرستنده ادمین اصلی باشد یا خود یوزربات پیام را داده باشد
    if event.sender_id != ADMIN_ID and not event.out: return
    
    target = event.pattern_match.group(1)
    chat_id = event.chat_id
    
    if target:
        try:
            e = await user_client.get_entity(target)
            chat_id = e.id
        except: return await event.reply("❌ نامعتبر.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ چت `{chat_id}` مجاز شد.")
    else:
        await event.reply("⚠️ در لیست بود.")

# حذف چت از لیست سفید
@user_client.on(events.NewMessage(pattern=r'(?i)^/del(?:\s+(.+))?'))
async def user_del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target = event.pattern_match.group(1)
    chat_id = event.chat_id
    if target:
        try: chat_id = int(target)
        except: pass
    
    if chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"🗑 چت `{chat_id}` حذف شد.")

# پینگ
@user_client.on(events.NewMessage(pattern=r'(?i)^/ping'))
async def ping_h(event):
    if not await security_check(event): return
    start = time.time()
    info = await get_system_info()
    ping = round((time.time() - start) * 1000)
    await event.reply(f"🚀 **Online**\n📶 Ping: `{ping}ms`\n{info}")

# لایو (با حذف خودکار لینک)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    if not await security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    # اگر لینک نداده بود، از لینک پیش‌فرض استفاده کن و حتماً پردازشش کن
    final_url = url_arg if url_arg else DEFAULT_LIVE_URL
    
    # حذف دستور برای مخفی ماندن لینک از بقیه
    try: await event.delete()
    except: pass

    status = await user_client.send_message(event.chat_id, "📡 در حال رندر مستقیم لایو...")

    try:
        # پردازش لینک (چه پیش‌فرض چه ارسالی)
        u, t = await get_stream_link(final_url)
        await start_stream_v1(event.chat_id, u)
        await status.edit(f"🔴 **پخش زنده فعال شد**\n📺 `{t}`\n⚡️ اتصال مستقیم")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")

# توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if not await security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        gc.collect()
        await event.reply("⏹ قطع شد.")
    except: pass

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Stable Streamer Active"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            if not call_py.active_calls: await call_py.start()
    except: pass
    
    print("🚀 Bot is LIVE!")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())