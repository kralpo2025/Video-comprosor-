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

# متغیرهای وضعیت
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
# ربات فقط برای لاگین در پیوی
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
# یوزربات برای همه کارها
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================

def get_server_stats():
    """دریافت وضعیت کامل سرور برای دستور پینگ"""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        # محاسبه پینگ (زمان پاسخگویی تقریبی)
        start = time.time()
        end = time.time()
        ping_ms = round((end - start) * 1000)
        
        return (
            f"🤖 **وضعیت سیستم:**\n"
            f"🧠 رم: `{mem.percent}%`\n"
            f"💾 دیسک: `{disk.percent}%`\n"
            f"📶 پینگ: `{ping_ms}ms`"
        )
    except: return "خطا در دریافت اطلاعات سیستم"

def get_simple_stats():
    """فقط برای نمایش موقع پخش"""
    try:
        mem = psutil.virtual_memory()
        return f"(RAM: {mem.percent}%)"
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

    # تنظیمات کیفیت SD (برای جلوگیری از لگ)
    # ویدیو 480p و صدای مدیوم
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p
    )

    try:
        # خروج اجباری و سپس ورود (برای جلوگیری از کرش و باگ)
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است! لطفا آن را روشن کنید.")
        raise e

def is_authorized(event):
    """پیام فقط از طرف ادمین یا خود یوزربات (در کانال) باشد"""
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 ربات (فقط لاگین و راهنما در PV)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    status = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    msg = (
        f"👋 **پنل لاگین یوزربات**\n"
        f"وضعیت اتصال: {status}\n\n"
        f"🔐 **لاگین:**\n"
        f"`/phone +98...` | `/code ...` | `/password ...`\n\n"
        f"--- **راهنمای دستورات (در گروه/کانال)** ---\n"
        f"1️⃣ **پخش فایل:** (ریپلای روی آهنگ/فیلم)\n"
        f"   دستور: `پخش` یا `/ply`\n\n"
        f"2️⃣ **پخش زنده:**\n"
        f"   دستور: `لایو` یا `تی وی` (شبکه پیش‌فرض)\n"
        f"   دستور: `لایو [لینک]` (پخش لینک دلخواه)\n\n"
        f"3️⃣ **توقف:**\n"
        f"   دستور: `قطع` یا `/stop`\n\n"
        f"4️⃣ **وضعیت سرور:**\n"
        f"   دستور: `پینگ` یا `/ping`\n\n"
        f"5️⃣ **مدیریت لیست مجاز:**\n"
        f"   دستور: `/add` (افزودن) | `/del` (حذف)"
    )
    await event.reply(msg)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("کد: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود تکمیل شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# ⚡️ پردازشگر مرکزی یوزربات (Universal Handler)
# ==========================================
@user_client.on(events.NewMessage)
async def userbot_handler(event):
    """
    این تابع تمام پیام‌های دریافتی یوزربات را بررسی می‌کند.
    اگر پیام از ادمین باشد و شامل کلمات کلیدی باشد، اجرا می‌شود.
    """
    
    # 1. دریافت متن
    text = event.raw_text
    if not text: return
    
    # استانداردسازی متن (حروف کوچک و حذف فاصله)
    cmd = text.lower().strip()
    chat_id = str(event.chat_id)

    # 2. بررسی هویت (فقط ادمین یا خود یوزربات)
    if not is_authorized(event): return

    # ============================
    # دستورات مدیریتی (همیشه فعال)
    # ============================
    
    # افزودن به لیست سفید (/add)
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
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # حذف از لیست سفید (/del)
    if cmd.startswith('/del'):
        try:
            target = cmd.replace('/del', '').strip()
            cid = target if target else chat_id
            
            if cid in WHITELIST:
                del WHITELIST[cid]
                save_whitelist(WHITELIST)
                await event.reply(f"🗑 حذف شد: `{cid}`")
            else:
                await event.reply("⚠️ در لیست نبود.")
        except: pass
        return
        
    # نمایش لیست (/list)
    if cmd == '/list':
        if not WHITELIST: return await event.reply("لیست خالی.")
        msg = "**لیست مجاز:**\n\n"
        for i, d in WHITELIST.items():
            msg += f"🔹 **{d['title']}**\n🆔 `{i}`\n🔗 @{d['username']}\n\n"
        await event.reply(msg)
        return

    # ============================
    # بخش چک کردن مجوز (Whitelist Check)
    # ============================
    # اگر چت در لیست سفید نیست، بقیه دستورات اجرا نشوند
    if chat_id not in WHITELIST: return

    # ============================
    # دستور 1: پینگ و وضعیت سرور
    # ============================
    if cmd in ['/ping', 'پینگ', 'ping']:
        stats = get_server_stats()
        await event.reply(stats)
        return

    # ============================
    # دستور 2: پخش فایل (پخش / ply)
    # ============================
    if cmd in ['/ply', 'پخش', 'play', '/play']:
        reply = await event.get_reply_message()
        if not reply or not (reply.audio or reply.video):
            return await event.reply("❌ روی فایل ریپلای کن.")
        
        status = await event.reply(f"📥 **دانلود...** {get_simple_stats()}")
        await cleanup(event.chat_id)
        
        try:
            path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
            if not path: return await status.edit("❌ دانلود نشد.")
            
            active_calls_data[event.chat_id] = {"path": path, "type": "file"}
            
            await status.edit("🚀 **پخش فایل...**")
            await start_stream_engine(event.chat_id, path)
            await status.delete() # حذف پیام وضعیت
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
            await cleanup(event.chat_id)
        return

    # ============================
    # دستور 3: پخش زنده (لایو / تی وی)
    # ============================
    # تشخیص: اگر پیام با یکی از این کلمات شروع شود
    if cmd.startswith(('لایو', 'تی وی', '/live', 'live')):
        
        # جدا کردن لینک (اگر کاربر فرستاده باشد)
        parts = text.split(maxsplit=1) # روی متن اصلی (نه lower) اسپلیت میکنیم
        
        # اگر قسمت دوم وجود داشت، لینک است، وگرنه لینک پیش‌فرض
        link = parts[1].strip() if len(parts) > 1 else IRAN_INTL_URL
        title = "لینک سفارشی" if len(parts) > 1 else "ایران اینترنشنال"
        
        # اگر لینک سفارشی بود، پیام کاربر را پاک کن (طبق درخواست)
        if len(parts) > 1:
            try: await event.delete()
            except: pass

        status = await event.reply(f"📡 **اتصال...** {get_simple_stats()}")
        await cleanup(event.chat_id)
        
        try:
            final_url = link
            # اگر لینک مستقیم نبود (مثلا یوتیوب بود)، تبدیلش کن
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
            await asyncio.sleep(3)
            await status.delete() # حذف پیام وضعیت
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # ============================
    # دستور 4: قطع پخش (قطع / stop)
    # ============================
    if cmd in ['/stop', 'قطع', 'stop', 'بستن']:
        try:
            await call_py.leave_group_call(event.chat_id)
            await cleanup(event.chat_id)
            await event.reply("⏹ **قطع شد.**")
        except: pass
        return

# ==========================================
# 🛡 امنیت (خروج خودکار)
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