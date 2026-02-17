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
# ربات فقط برای لاگین (در PV)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
# یوزربات برای همه کارها
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

async def start_stream_engine(chat_id, source, start_time=0):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت SD (برای جلوگیری از لگ)
    ffmpeg_params = f"-ss {start_time}" if start_time > 0 else ""
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p, 
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        # خروج اجباری و سپس ورود (برای جلوگیری از کرش)
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
        f"👋 **پنل مدیریت یوزربات (مخصوص ادمین)**\n"
        f"وضعیت اتصال: {status}\n\n"
        f"📚 **راهنمای دستورات (فارسی و انگلیسی):**\n"
        f"دستورات زیر را در گروه یا کانال (توسط یوزربات) ارسال کنید:\n\n"
        f"📥 **پخش فایل:** (ریپلای روی فایل)\n"
        f"➖ `پخش` یا `/ply`\n\n"
        f"📺 **پخش زنده:**\n"
        f"➖ `لایو` یا `/live` یا `تی وی` (پخش ایران اینترنشنال)\n"
        f"➖ `لایو [لینک]` (پخش لینک دلخواه)\n"
        f"   *(مثال: `لایو https://example.com/video.m3u8`)*\n\n"
        f"⛔️ **توقف:**\n"
        f"➖ `قطع` یا `/stop`\n\n"
        f"⚙️ **مدیریت لیست:**\n"
        f"➖ `/add` (افزودن گروه/کانال جاری)\n"
        f"➖ `/del` (حذف گروه/کانال جاری)\n"
        f"➖ `/list` (نمایش لیست مجاز)\n\n"
        f"🔐 **لاگین:**\n"
        f"`/phone` | `/code` | `/password`"
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
# ⚡️ هسته مرکزی یوزربات (بدون دکمه، با دستورات فارسی)
# ==========================================
@user_client.on(events.NewMessage)
async def universal_handler(event):
    """
    این تابع تمام پیام‌ها را بررسی می‌کند و جایگزین همه هندلرهای جداگانه شده است.
    این کار تضمین می‌کند که دستورات در کانال و گروه بدون باگ اجرا شوند.
    """
    
    # 1. دریافت متن و اعتبارسنجی
    text = event.raw_text
    if not text: return
    
    # استانداردسازی (حذف فاصله و کوچک کردن حروف)
    # text_lower برای مقایسه دستورات استفاده می‌شود
    text_lower = text.lower().strip()
    chat_id = str(event.chat_id)

    # 2. بررسی اینکه ادمین یا خود یوزربات باشد
    if not is_authorized(event): return

    # ============================
    # بخش 1: دستورات مدیریتی
    # ============================
    
    # افزودن به لیست سفید (/add)
    if text_lower.startswith('/add'):
        try:
            target = text_lower.replace('/add', '').strip()
            if not target: 
                entity = await event.get_chat() # گروه جاری
            else: 
                entity = await user_client.get_entity(target) # لینک یا آیدی
            
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
    if text_lower.startswith('/del'):
        try:
            target = text_lower.replace('/del', '').strip()
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
    if text_lower == '/list':
        if not WHITELIST: return await event.reply("لیست خالی.")
        msg = "**لیست مجاز:**\n\n"
        for i, d in WHITELIST.items():
            msg += f"🔹 **{d['title']}**\n🆔 `{i}`\n🔗 @{d['username']}\n\n"
        await event.reply(msg)
        return

    # ============================
    # بخش 2: چک کردن مجوز پخش
    # ============================
    if chat_id not in WHITELIST: return

    # ============================
    # بخش 3: دستور پخش فایل
    # ============================
    # دستورات: پخش، ply, /ply, play
    if text_lower in ['/ply', 'پخش', 'play', '/play']:
        reply = await event.get_reply_message()
        if not reply or not (reply.audio or reply.video):
            return await event.reply("❌ روی فایل ریپلای کن.")
        
        status = await event.reply(f"📥 **دانلود...**\n{get_sys_info()}")
        await cleanup(event.chat_id)
        
        try:
            path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
            if not path: return await status.edit("❌ دانلود نشد.")
            
            active_calls_data[event.chat_id] = {"path": path, "type": "file"}
            
            await status.edit("🚀 **پخش فایل...**")
            await start_stream_engine(event.chat_id, path)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
            await cleanup(event.chat_id)
        return

    # ============================
    # بخش 4: دستور پخش زنده
    # ============================
    # دستورات: لایو، تی وی، live, /live (همراه با لینک یا بدون لینک)
    if text_lower.startswith(('لایو', 'تی وی', '/live', 'live')):
        
        # جدا کردن دستور از لینک (اگر وجود داشته باشد)
        parts = text.split(maxsplit=1) # اسپلیت روی متن اصلی (نه lower) برای حفظ بزرگ/کوچکی لینک
        
        link = parts[1].strip() if len(parts) > 1 else IRAN_INTL_URL
        title = "لینک سفارشی" if len(parts) > 1 else "ایران اینترنشنال"
        
        # حذف پیام حاوی لینک (برای تمیزی) اگر لینک دلخواه بود
        if len(parts) > 1:
            try: await event.delete()
            except: pass

        status = await event.reply(f"📡 **اتصال...**\n{get_sys_info()}")
        await cleanup(event.chat_id)
        
        try:
            final_url = link
            # اگر لینک مستقیم نبود (مثل یوتیوب)، تبدیل کن
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
    # بخش 5: دستور قطع (Stop)
    # ============================
    # دستورات: قطع، stop, /stop, بستن
    if text_lower in ['/stop', 'قطع', 'stop', 'بستن']:
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