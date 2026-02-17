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

# لینک ثابت جدید (ایران اینترنشنال)
DEFAULT_LIVE_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "whitelist.json"
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
# 🔐 مدیریت لیست سفید (Whitelist)
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
    except Exception as e:
        logger.error(f"FFmpeg Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# ربات: فقط برای لاگین در پیوی (هیچ کدی برای گروه ندارد)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# یوزربات: موتور اصلی
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================

def get_server_stats():
    """دریافت پینگ و منابع سیستم"""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return (
            f"📊 **وضعیت سرور:**\n"
            f"🧠 رم: `{mem.percent}%`\n"
            f"💾 دیسک: `{disk.percent}%`"
        )
    except: return "خطا در خواندن اطلاعات."

async def cleanup(chat_id):
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def start_stream_engine(chat_id, source):
    """موتور پخش بهینه (SD Quality)"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت: SD_480p (تعادل بین کیفیت و سرعت)
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p
    )

    try:
        # خروج و ورود مجدد برای جلوگیری از باگ Already Joined
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است! لطفا Voice Chat را روشن کنید.")
        raise e

def is_authorized(event):
    """
    آیا پیام معتبر است؟
    1. ادمین فرستاده باشد (ADMIN_ID)
    2. یا خود یوزربات در کانال فرستاده باشد (event.out)
    """
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 بخش ربات (فقط لاگین در پیوی)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    status = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    await event.reply(
        f"👋 **پنل یوزربات (بدون دکمه)**\n"
        f"وضعیت: {status}\n\n"
        f"🔐 **لاگین:**\n`/phone` | `/code` | `/password`\n\n"
        f"📋 **دستورات (فارسی/انگلیسی):**\n"
        f"🔹 `پخش` یا `/ply` (روی فایل)\n"
        f"🔹 `لایو` (شبکه خبر)\n"
        f"🔹 `لایو [لینک]` (لینک دلخواه)\n"
        f"🔹 `قطع` یا `/stop`\n"
        f"🔹 `پینگ` (وضعیت منابع)\n"
        f"🔹 `/add` (افزودن) | `/del` (حذف)\n"
        f"🔹 `/list` (نمایش لیست)"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("کد ارسالی تلگرام: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# ⚡️ هسته مرکزی یوزربات (Universal Handler)
# ==========================================
# این تابع جایگزین تمام هندلرهای قبلی است تا تداخل ایجاد نشود
@user_client.on(events.NewMessage)
async def universal_handler(event):
    # 1. دریافت متن
    text = event.raw_text
    if not text: return
    
    # استانداردسازی (حروف کوچک و حذف فاصله)
    cmd = text.lower().strip()
    chat_id = str(event.chat_id)

    # 2. بررسی هویت (ادمین یا خود یوزربات)
    if not is_authorized(event): return

    # ==========================
    # مدیریت لیست سفید
    # ==========================
    
    # افزودن (/add)
    if cmd.startswith('/add'):
        try:
            target = cmd.replace('/add', '').strip()
            if not target: 
                entity = await event.get_chat()
            else: 
                entity = await user_client.get_entity(target)
            
            cid = str(entity.id)
            title = getattr(entity, 'title', 'Chat')
            username = getattr(entity, 'username', 'ندارد')
            
            WHITELIST[cid] = {"title": title, "username": username}
            save_whitelist(WHITELIST)
            await event.reply(f"✅ **{title}** مجاز شد.\n🆔 `{cid}`\n🔗 @{username}")
        except Exception as e: await event.reply(f"❌ خطا: {e}")
        return

    # حذف (/del)
    if cmd.startswith('/del'):
        try:
            cid = str(event.chat_id)
            if cid in WHITELIST:
                del WHITELIST[cid]
                save_whitelist(WHITELIST)
                await event.reply("🗑 حذف شد.")
            else: await event.reply("⚠️ در لیست نبود.")
        except: pass
        return

    # لیست (/list)
    if cmd == '/list':
        if not WHITELIST: return await event.reply("لیست خالی است.")
        msg = "**📋 لیست مجاز:**\n\n"
        for i, d in WHITELIST.items():
            msg += f"🔹 {d['title']} (`@{d['username']}`)\n"
        await event.reply(msg)
        return

    # ==========================
    # بررسی مجوز پخش
    # ==========================
    if chat_id not in WHITELIST: return

    # ==========================
    # دستورات اجرایی
    # ==========================

    # 1. پینگ (Ping)
    if cmd in ['پینگ', '/ping', 'ping']:
        await event.reply(get_server_stats())
        return

    # 2. پخش فایل (پخش / ply)
    if cmd in ['پخش', '/ply', 'play']:
        reply = await event.get_reply_message()
        if not reply or not (reply.audio or reply.video):
            return await event.reply("❌ ریپلای کن.")
        
        status = await event.reply("📥 **دانلود...**")
        await cleanup(event.chat_id)
        
        try:
            path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
            if not path: return await status.edit("❌ خطا در دانلود.")
            
            active_calls_data[event.chat_id] = {"path": path, "type": "file"}
            
            await status.edit("🚀 **پخش فایل...**")
            await start_stream_engine(event.chat_id, path)
            
            # حذف پیام بعد از 5 ثانیه
            await asyncio.sleep(5)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
            await cleanup(event.chat_id)
        return

    # 3. پخش لایو (لایو / live)
    # پشتیبانی از: لایو، لایو [لینک]، /live
    if cmd.startswith(('لایو', '/live', 'تی وی', 'tv')):
        parts = text.split(maxsplit=1)
        
        # اگر لینک دارد
        if len(parts) > 1:
            link = parts[1].strip()
            title = "لینک سفارشی"
            # حذف پیام کاربر (برای تمیزی)
            try: await event.delete()
            except: pass
        else:
            link = DEFAULT_LIVE_URL
            title = "ایران اینترنشنال"

        status = await event.reply(f"📡 **اتصال به {title}...**")
        await cleanup(event.chat_id)
        
        try:
            final_url = link
            # اگر لینک مستقیم نبود
            if link != DEFAULT_LIVE_URL:
                ydl_opts = {'format': 'best[height<=360]/best', 'noplaylist': True, 'quiet': True, 'geo_bypass': True}
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(link, download=False)
                        final_url = info.get('url')
                except:
                    return await status.edit("❌ لینک نامعتبر.")

            active_calls_data[event.chat_id] = {"path": final_url, "type": "live"}
            
            await status.edit(f"🔴 **پخش زنده:** {title}")
            await start_stream_engine(event.chat_id, final_url)
            
            await asyncio.sleep(5)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # 4. قطع (Stop)
    if cmd in ['قطع', '/stop', 'بستن', 'stop']:
        try:
            await call_py.leave_group_call(event.chat_id)
            await cleanup(event.chat_id)
            await event.reply("⏹ **قطع شد.**")
        except: pass
        return

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
# 🌐 سرور (Web Server)
# ==========================================
async def handle_req(request):
    return web.Response(text="Running")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_req)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"WebServer on {PORT}")

async def main():
    await start_server()
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): await call_py.start()
    except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())