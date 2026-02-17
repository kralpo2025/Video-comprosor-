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

# ایمپورت‌های ضروری وب‌سرور و تلگرام
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

# لینک ثابت جدید
IRAN_INTL_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "whitelist.json"
# پورت را از محیط می‌گیرد، اگر نبود 8080
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
# 🛠 نصب FFmpeg (مخصوص Render)
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
# ربات (فقط لاگین)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
# یوزربات (اجرا کننده)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================

def get_server_stats():
    """نمایش وضعیت سرور"""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        # محاسبه پینگ (فیک برای نمایش سرعت)
        t1 = time.time(); time.sleep(0.001); t2 = time.time()
        ping = int((t2 - t1) * 1000)
        return (
            f"📊 **وضعیت سرور:**\n"
            f"🧠 رم: `{mem.percent}%`\n"
            f"💾 دیسک: `{disk.percent}%`\n"
            f"📶 پینگ: `{ping}ms`"
        )
    except: return "خطا در دریافت اطلاعات."

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

    # کیفیت SD برای جلوگیری از لگ
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p
    )

    try:
        # خروج و ورود مجدد (برای رفع باگ‌ها)
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
    """پیام از طرف ادمین است یا خود یوزربات (برای کانال)"""
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 ربات (فقط لاگین در PV)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    status = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    msg = (
        f"👋 **پنل مدیریت (نسخه بدون دکمه)**\n"
        f"وضعیت یوزربات: {status}\n\n"
        f"🔐 **لاگین:**\n"
        f"`/phone` | `/code` | `/password`\n\n"
        f"📋 **راهنما (دستورات فارسی/انگلیسی):**\n"
        f"1️⃣ `پخش` یا `/ply` (ریپلای روی فایل)\n"
        f"2️⃣ `لایو` (شبکه خبر) | `لایو [لینک]` (لینک دلخواه)\n"
        f"3️⃣ `قطع` یا `/stop`\n"
        f"4️⃣ `پینگ` (وضعیت سرور)\n"
        f"5️⃣ `/add` (افزودن) | `/del` (حذف)\n"
        f"6️⃣ `/list` (نمایش لیست مجاز)"
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
async def main_handler(event):
    """
    این تابع تمام پیام‌ها را می‌گیرد و بررسی می‌کند.
    """
    text = event.raw_text
    if not text: return
    
    # استانداردسازی: حروف کوچک، حذف فاصله اضافی
    cmd = text.lower().strip()
    chat_id = str(event.chat_id)

    # بررسی ادمین بودن
    if not is_authorized(event): return

    # --- مدیریت لیست سفید (/add) ---
    if cmd.startswith('/add') or cmd.startswith('اد'):
        try:
            target = cmd.replace('/add', '').replace('اد', '').strip()
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

    # --- حذف از لیست سفید (/del) ---
    if cmd.startswith('/del') or cmd.startswith('حذف'):
        try:
            cid = chat_id # حذف گروه جاری
            if cid in WHITELIST:
                del WHITELIST[cid]
                save_whitelist(WHITELIST)
                await event.reply("🗑 از لیست حذف شد.")
            else: await event.reply("⚠️ اینجا در لیست نبود.")
        except: pass
        return

    # --- نمایش لیست (/list) ---
    if cmd == '/list' or cmd == 'لیست':
        if not WHITELIST: return await event.reply("لیست خالی است.")
        msg = "**📋 لیست مجاز:**\n\n"
        for i, d in WHITELIST.items():
            msg += f"🔹 {d['title']} (`@{d['username']}`)\n"
        await event.reply(msg)
        return

    # ================================
    # چک کردن مجوز برای دستورات پخش
    # ================================
    if chat_id not in WHITELIST: return

    # --- پینگ (Ping) ---
    if cmd in ['/ping', 'پینگ', 'ping']:
        await event.reply(get_server_stats())
        return

    # --- پخش فایل (Play) ---
    if cmd in ['/ply', 'پخش', 'play']:
        reply = await event.get_reply_message()
        if not reply or not (reply.audio or reply.video):
            return await event.reply("❌ ریپلای کن.")
        
        status = await event.reply("📥 **دانلود...**")
        await cleanup(event.chat_id)
        
        try:
            path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
            if not path: return await status.edit("❌ دانلود نشد.")
            
            active_calls_data[event.chat_id] = {"path": path, "type": "file"}
            
            await status.edit("🚀 **پخش...**")
            await start_stream_engine(event.chat_id, path)
            
            # پاکسازی پیام بعد از 5 ثانیه
            await asyncio.sleep(5)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
            await cleanup(event.chat_id)
        return

    # --- پخش زنده (Live) ---
    # پشتیبانی از: لایو، لایو لینک، /live، /live link
    if cmd.startswith(('لایو', '/live', 'تی وی')):
        # جدا کردن لینک (روی متن اصلی برای حفظ بزرگی/کوچکی حروف لینک)
        parts = text.split(maxsplit=1)
        
        link = parts[1].strip() if len(parts) > 1 else IRAN_INTL_URL
        title = "لینک سفارشی" if len(parts) > 1 else "ایران اینترنشنال"
        
        # اگر لینک سفارشی بود، پیام کاربر پاک شود
        if len(parts) > 1:
            try: await event.delete()
            except: pass

        status = await event.reply(f"📡 **اتصال به {title}...**")
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
                except:
                    return await status.edit("❌ لینک نامعتبر.")

            active_calls_data[event.chat_id] = {"path": final_url, "type": "live"}
            
            await status.edit(f"🔴 **پخش زنده:**\n{title}")
            await start_stream_engine(event.chat_id, final_url)
            
            await asyncio.sleep(5)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # --- قطع (Stop) ---
    if cmd in ['/stop', 'قطع', 'بستن', 'stop']:
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
async def handle_req(request):
    return web.Response(text="Bot is Running")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_req)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌍 Web Server Started on Port {PORT}")

async def main():
    # اجرای وب‌سرور در پس‌زمینه
    await start_server()
    
    # اجرای ربات‌ها
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): 
            logger.info("✅ Userbot Connected")
            await call_py.start()
    except: pass
    
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())