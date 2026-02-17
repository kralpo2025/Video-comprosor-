import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
import time
import psutil
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
# 🔐 لیست سفید (Whitelist)
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
    try:
        logger.info("⏳ Installing FFmpeg...")
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
# 📊 توابع کمکی
# ==========================================

def get_sys_info():
    """دریافت وضعیت رم و دیسک"""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return f"(RAM: {mem.percent}% | Disk: {disk.percent}%)"
    except: return ""

async def cleanup(chat_id):
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def start_stream_engine(chat_id, source):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات ساده برای جلوگیری از کرش FFmpeg
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p
    )

    try:
        # خروج اجباری قبل از ورود برای رفع باگ
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال گروه/کانال خاموش است!")
        raise e

def is_admin(event):
    # چک میکند آیا پیام از طرف ادمین است یا خود یوزربات (برای کانال ضروری است)
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 ربات (فقط لاگین - بدون دکمه)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    status = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    await event.reply(f"یوزربات: {status}\n\n`/phone شماره`\n`/code کد`\n`/password رمز`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("کد: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("رمز دوم: `/password ...`")
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
# ⚙️ هندلرهای یوزربات (جداگانه برای اطمینان)
# ==========================================

# 1. مدیریت لیست سفید (/add)
@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?: ?(.*))?'))
async def add_h(event):
    if not is_admin(event): return
    arg = event.pattern_match.group(1)
    
    try:
        if not arg: entity = await event.get_chat()
        else: entity = await user_client.get_entity(arg.strip())
        
        cid = str(entity.id)
        WHITELIST[cid] = {"title": getattr(entity, 'title', 'Chat')}
        save_whitelist(WHITELIST)
        await event.reply(f"✅ مجاز شد:\n{getattr(entity, 'title', 'Chat')}\nID: `{cid}`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# 2. مدیریت لیست سفید (/del)
@user_client.on(events.NewMessage(pattern=r'(?i)^/del(?: ?(.*))?'))
async def del_h(event):
    if not is_admin(event): return
    arg = event.pattern_match.group(1)
    cid = arg.strip() if arg else str(event.chat_id)
    
    if cid in WHITELIST:
        del WHITELIST[cid]
        save_whitelist(WHITELIST)
        await event.reply(f"🗑 حذف شد: `{cid}`")
    else: await event.reply("⚠️ در لیست نبود.")

# 3. نمایش لیست (/list)
@user_client.on(events.NewMessage(pattern=r'(?i)^/list$'))
async def list_h(event):
    if not is_admin(event): return
    if not WHITELIST: return await event.reply("لیست خالی.")
    msg = "**لیست مجاز:**\n" + "\n".join([f"- {d['title']} (`{i}`)" for i, d in WHITELIST.items()])
    await event.reply(msg)

# 4. پخش فایل (/ply یا پخش)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ply|پخش|/play)$'))
async def play_h(event):
    if not is_admin(event): return
    if str(event.chat_id) not in WHITELIST: return
    
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ روی فایل ریپلای کن.")
    
    chat_id = event.chat_id
    status = await event.reply(f"📥 **دانلود...**\n{get_sys_info()}")
    await cleanup(chat_id)
    
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        if not path: return await status.edit("❌ دانلود نشد.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        
        await status.edit("🚀 **پخش...**")
        await start_stream_engine(chat_id, path)
        await status.delete()
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

# 5. پخش لایو (/live یا تی وی)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|تی وی|live)(?: (.*))?$'))
async def live_h(event):
    if not is_admin(event): return
    if str(event.chat_id) not in WHITELIST: return

    args = event.pattern_match.group(2)
    link = args.strip() if args else IRAN_INTL_URL
    title = "لینک کاربر" if args else "ایران اینترنشنال"

    status = await event.reply(f"📡 **اتصال...**\n{get_sys_info()}")
    await cleanup(event.chat_id)

    try:
        final_url = link
        # اگر لینک مستقیم نبود (یوتیوب و...)
        if link != IRAN_INTL_URL:
            ydl_opts = {'format': 'best[height<=360]/best', 'noplaylist': True, 'quiet': True, 'geo_bypass': True}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(link, download=False)
                    final_url = info.get('url')
                    title = info.get('title')
            except:
                return await status.edit("❌ لینک نامعتبر.")

        active_calls_data[event.chat_id] = {"path": final_url, "type": "live"}
        
        await status.edit(f"🔴 **پخش زنده: {title}**")
        await start_stream_engine(event.chat_id, final_url)
        await asyncio.sleep(2)
        await status.delete()

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# 6. قطع پخش (/stop یا قطع)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع|stop)$'))
async def stop_h(event):
    if not is_admin(event): return
    if str(event.chat_id) not in WHITELIST: return
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ **قطع شد.**")
    except: pass

# ==========================================
# 🛡 امنیت (Auto Leave)
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
    app.router.add_get("/", lambda r: web.Response(text="Bot Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): 
            logger.info("Userbot Connected")
            await call_py.start()
    except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())