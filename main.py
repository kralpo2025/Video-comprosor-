import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
import time
import psutil
import sys
from aiohttp import web
from telethon import TelegramClient, events
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

# لینک ثابت جدید ایران اینترنشنال
IRAN_INTL_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "whitelist.json"
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
# 🔐 مدیریت لیست سفید
# ==========================================
def load_whitelist():
    if not os.path.exists(AUTH_FILE): return {}
    try:
        with open(AUTH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def save_whitelist(data):
    with open(AUTH_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

WHITELIST = load_whitelist()

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except: pass

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# ربات فقط برای لاگین
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
# یوزربات همه کاره
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================

def get_sys_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return f"(RAM: {mem.percent}% | Disk: {disk.percent}%)"

async def cleanup(chat_id):
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def get_stream_link(url):
    ydl_opts = {'format': 'best[height<=360]/best', 'noplaylist': True, 'quiet': True, 'geo_bypass': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except: return None, None

async def start_stream_engine(chat_id, source, start_time=0):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت پایین (SD) برای جلوگیری از لگ
    ffmpeg_params = f"-ss {start_time}" if start_time > 0 else ""
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p, 
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        # متد امن: اول خروج کامل، بعد ورود
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("ویس‌کال خاموش است! (در کانال/گروه روشن کنید)")
        raise e

def is_admin(event):
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 فقط لاگین (Bot API)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    status = "وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "قطع"
    await event.reply(f"وضعیت یوزربات: {status}\n\nفقط دستورات `/phone`, `/code`, `/password` اینجا کار می‌کنند.")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد؟ `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ پسورد؟ `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# ⚙️ مدیریت لیست سفید (Userbot)
# ==========================================
@user_client.on(events.NewMessage(pattern=r'^/add(?: ?(.*))?$'))
async def add_handler(event):
    if not is_admin(event): return
    arg = event.pattern_match.group(1)
    
    try:
        if not arg: entity = await event.get_chat()
        else: entity = await user_client.get_entity(arg.strip())
        
        cid = str(entity.id)
        if cid in WHITELIST: return await event.reply(f"⚠️ `{cid}` قبلا بود.")
        
        WHITELIST[cid] = {"title": getattr(entity, 'title', 'Unknown'), "username": getattr(entity, 'username', 'None')}
        save_whitelist(WHITELIST)
        await event.reply(f"✅ **{getattr(entity, 'title', 'Chat')}** مجاز شد.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'^/del(?: ?(.*))?$'))
async def del_handler(event):
    if not is_admin(event): return
    arg = event.pattern_match.group(1)
    cid = arg.strip() if arg else str(event.chat_id)
    
    if cid in WHITELIST:
        del WHITELIST[cid]
        save_whitelist(WHITELIST)
        await event.reply(f"🗑 `{cid}` حذف شد.")
    else: await event.reply("⚠️ نبود.")

@user_client.on(events.NewMessage(pattern='^/list$'))
async def list_handler(event):
    if not is_admin(event): return
    if not WHITELIST: return await event.reply("لیست خالی.")
    msg = "**لیست مجاز:**\n" + "\n".join([f"- {d['title']} (`{i}`)" for i, d in WHITELIST.items()])
    await event.reply(msg)

# ==========================================
# 🎵 پخش مدیا (Userbot) - فارسی و انگلیسی
# ==========================================

# دستور: پخش یا /ply
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ply|پخش)$'))
async def play_media(event):
    # چک کردن امنیت
    if str(event.chat_id) not in WHITELIST: return
    
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ روی فایل ریپلای کن.")
    
    chat_id = event.chat_id
    status = await event.reply(f"📥 **دانلود...**\n{get_sys_info()}")
    await cleanup(chat_id)
    
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        if not path: return await status.edit("❌ خطا دانلود.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        
        await status.edit("🚀 **پخش...**")
        await start_stream_engine(chat_id, path)
        await status.delete() # حذف پیام دانلود برای تمیزی
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

# دستور: تی وی یا /live
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|تی وی)(?: (.*))?$'))
async def live_stream(event):
    if str(event.chat_id) not in WHITELIST: return
    
    args = event.pattern_match.group(2)
    url = args.strip() if args else IRAN_INTL_URL
    title = "ایران اینترنشنال" if not args else "لینک کاربر"
    
    status = await event.reply(f"📡 **اتصال...**\n{get_sys_info()}")
    await cleanup(event.chat_id)
    
    try:
        # اگر لینک مستقیم نبود (لینک یوتیوب بود)
        if url != IRAN_INTL_URL:
            s_url, s_title = await get_stream_link(url)
            if not s_url: return await status.edit("❌ لینک نامعتبر.")
            url = s_url
            title = s_title

        active_calls_data[event.chat_id] = {"path": url, "type": "live"}
        
        await status.edit(f"🔴 **پخش زنده: {title}**")
        await start_stream_engine(event.chat_id, url)
        await asyncio.sleep(5)
        await status.delete() # حذف پیام برای تمیزی
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# دستور: قطع یا /stop
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)$'))
async def stop_stream(event):
    if str(event.chat_id) not in WHITELIST: return
    
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ **قطع شد.**")
    except: pass

# ==========================================
# 🛡 امنیت (لفت خودکار)
# ==========================================
@user_client.on(events.ChatAction)
async def auto_leave(event):
    if event.user_added and event.user_id == (await user_client.get_me()).id:
        if str(event.chat_id) not in WHITELIST and event.chat_id != ADMIN_ID:
            try:
                await event.reply("⛔️ اجازه ندارم.")
                await user_client.kick_participant(event.chat_id, 'me')
            except: pass

# ==========================================
# 🌐 سرور
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Running"))
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