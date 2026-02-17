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

# لینک ثابت ایران اینترنشنال
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
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی
# ==========================================

def get_sys_info():
    """دریافت وضعیت رم و دیسک بدون خطا"""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return f"(RAM: {mem.percent}% | Disk: {disk.percent}%)"
    except: return "(RAM: ?)"

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

    # تنظیمات کیفیت SD برای جلوگیری از لگ
    ffmpeg_params = f"-ss {start_time}" if start_time > 0 else ""
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p, 
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        # متد امن: خروج اجباری و ورود مجدد (برای رفع باگ کرش)
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("ویس‌کال خاموش است! (Voice Chat را روشن کنید)")
        raise e

def is_authorized(event):
    # ادمین یا خود یوزربات (برای کانال event.out مهم است)
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 ربات فقط برای لاگین (همراه راهنما)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    status = "✅ وصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    help_text = (
        f"👋 **پنل مدیریت یوزربات موزیک**\n"
        f"وضعیت اتصال: {status}\n\n"
        f"🔐 **راهنمای لاگین:**\n"
        f"1️⃣ `/phone +98912...`\n"
        f"2️⃣ `/code 12345`\n"
        f"3️⃣ `/password (رمز دو مرحله‌ای)`\n\n"
        f"📋 **دستورات یوزربات (در گروه/کانال):**\n"
        f"🔹 **پخش فایل:** ریپلای کنید و بنویسید:\n"
        f"`پخش` یا `/ply`\n\n"
        f"🔹 **پخش زنده (ایران اینترنشنال):**\n"
        f"`لایو` یا `/live` یا `تی وی`\n\n"
        f"🔹 **پخش لینک دلخواه:**\n"
        f"`لایو لینک` (مثال: `لایو https://...`)\n\n"
        f"🔹 **توقف پخش:**\n"
        f"`قطع` یا `/stop`\n\n"
        f"⚙️ **مدیریت:**\n"
        f"`/add` (افزودن گروه/کانال)\n"
        f"`/del` (حذف گروه/کانال)\n"
        f"`/list` (نمایش لیست مجاز)"
    )
    await event.reply(help_text)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("کد ارسالی تلگرام: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین با موفقیت انجام شد.")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("رمز دوم دارید: `/password رمز`")
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
# ⚡️ هسته مرکزی یوزربات (بدون دکمه)
# ==========================================
@user_client.on(events.NewMessage)
async def universal_handler(event):
    # دریافت متن پیام (حتی کپشن)
    text = event.raw_text
    if not text: return
    
    # استانداردسازی متن
    text = text.lower().strip()
    chat_id = str(event.chat_id)

    # فقط ادمین یا خود یوزربات
    if not is_authorized(event): return

    # --- 1. مدیریت لیست سفید (Add/Del/List) ---
    
    if text.startswith('/add'):
        try:
            target = text.replace('/add', '').strip()
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

    if text.startswith('/del'):
        try:
            target = text.replace('/del', '').strip()
            cid = target if target else chat_id
            
            if cid in WHITELIST:
                del WHITELIST[cid]
                save_whitelist(WHITELIST)
                await event.reply(f"🗑 حذف شد: `{cid}`")
            else:
                await event.reply("⚠️ در لیست نبود.")
        except: pass
        return
        
    if text == '/list':
        if not WHITELIST: return await event.reply("لیست خالی.")
        msg = "**لیست مجاز:**\n\n"
        for i, d in WHITELIST.items():
            msg += f"🔹 **{d['title']}**\n🆔 `{i}`\n🔗 @{d['username']}\n\n"
        await event.reply(msg)
        return

    # --- 2. بررسی مجوز پخش ---
    if chat_id not in WHITELIST: return

    # --- 3. دستور پخش فایل (پخش / ply) ---
    if text in ['/ply', 'پخش', 'play', '/play']:
        reply = await event.get_reply_message()
        if not reply or not (reply.audio or reply.video):
            return await event.reply("❌ روی فایل ریپلای کن.")
        
        status = await event.reply(f"📥 **دانلود...**\n{get_sys_info()}")
        await cleanup(event.chat_id)
        
        try:
            # دانلود فایل
            path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
            
            if not path: return await status.edit("❌ خطا در دانلود.")
            
            active_calls_data[event.chat_id] = {"path": path, "type": "file"}
            
            await status.edit("🚀 **پخش فایل...**")
            await start_stream_engine(event.chat_id, path)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
            await cleanup(event.chat_id)
        return

    # --- 4. دستور پخش زنده (لایو / تی وی) ---
    # پشتیبانی از: لایو، لایو لینک، /live، /live link
    if text.startswith('/live') or text.startswith('تی وی') or text.startswith('لایو') or text.startswith('live'):
        parts = text.split()
        # اگر کاربر لینکی جلوش گذاشته بود
        link = parts[1] if len(parts) > 1 else IRAN_INTL_URL
        title = "لینک سفارشی" if len(parts) > 1 else "ایران اینترنشنال"
        
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
            await asyncio.sleep(2)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # --- 5. دستور قطع (Stop) ---
    if text in ['/stop', 'قطع', 'stop', 'بستن']:
        try:
            await call_py.leave_group_call(event.chat_id)
            await cleanup(event.chat_id)
            await event.reply("⏹ **قطع شد.**")
        except: pass
        return

# ==========================================
# 🛡 خروج خودکار (Security)
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