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
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality
import yt_dlp

# ==========================================
# ⚙️ تنظیمات اصلی (Config)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

# لینک اختصاصی ایران اینترنشنال
IRAN_INTL_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای حافظه
login_state = {}
active_calls_data = {}

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🔐 سیستم مدیریت لیست سفید (Security)
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE):
        # به صورت پیش‌فرض ادمین مجاز است
        return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            return json.load(f)
    except:
        return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(chat_list, f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    if shutil.which("ffmpeg"):
        return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
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
# 📊 توابع سیستمی و کمکی
# ==========================================

def get_system_status():
    """دریافت وضعیت رم و دیسک"""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return (
        f"🧠 **RAM:** {mem.percent}%\n"
        f"💾 **Disk:** {disk.percent}% Used"
    )

async def cleanup(chat_id):
    """پاکسازی فایل و اطلاعات"""
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def get_stream_link(url):
    ydl_opts = {
        'format': 'best[height<=360]/best',
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        return None, None

def get_buttons(is_live=False):
    if is_live:
        return [[Button.inline("❌ قطع پخش", data=b'stop')]]
    return [
        [
            Button.inline("⏪ 30s", data=b'rw_30'),
            Button.inline("⏸/▶️", data=b'toggle'),
            Button.inline("⏩ 30s", data=b'fw_30')
        ],
        [Button.inline("❌ قطع و حذف", data=b'stop')]
    ]

async def start_stream_engine(chat_id, source, start_time=0):
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت پایین برای جلوگیری از لگ
    ffmpeg_params = f"-ss {start_time}" if start_time > 0 else ""

    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=ffmpeg_params
    )

    try:
        # متد امن: خروج و ورود مجدد
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
        
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است! (در کانال باید لایو را استارت کنید)")
        raise e

# ==========================================
# 🛡 ناظر امنیتی (Security Watcher)
# ==========================================
@user_client.on(events.ChatAction)
async def security_check(event):
    """اگر یوزربات به گروهی اضافه شد که در لیست نیست، لفت بده"""
    # اگر ایونت مربوط به اضافه شدن یوزربات بود
    if event.user_added and event.user_id == (await user_client.get_me()).id:
        chat_id = event.chat_id
        if chat_id not in ALLOWED_CHATS and chat_id != ADMIN_ID:
            try:
                await event.reply("⛔️ **من اجازه ندارم اینجا باشم!**\nفقط با اجازه `Owner` کار می‌کنم.\n\n👋 بای!")
                await user_client.kick_participant(chat_id, 'me')
            except:
                pass # اگر نتونست پیام بده یا لفت بده

# ==========================================
# 🤖 ربات (مدیریت و لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    conn = "🟢 آنلاین" if user_client.is_connected() and await user_client.is_user_authorized() else "🔴 آفلاین"
    sys_info = get_system_status()
    
    msg = (
        f"👋 **پنل مدیریت ربات استریمر**\n\n"
        f"وضعیت یوزربات: {conn}\n"
        f"{sys_info}\n\n"
        f"🛠 **دستورات مدیریتی:**\n"
        f"➕ افزودن گروه/کانال: `/add` (در گروه بفرستید)\n"
        f"➖ حذف گروه/کانال: `/del`\n"
        f"📋 لیست مجاز: `/list`\n\n"
        f"🎵 **دستورات پخش (توسط یوزربات):**\n"
        f"▶️ پخش فایل: `/ply` (ریپلای)\n"
        f"📡 ایران اینترنشنال: `/live`\n\n"
        f"🔑 **لاگین:** `/phone`, `/code`, `/password`"
    )
    await event.reply(msg)

# ==========================================
# ⚙️ دستورات مدیریتی لیست سفید (Admin Only)
# ==========================================
@user_client.on(events.NewMessage(pattern='/add', outgoing=True))
@user_client.on(events.NewMessage(pattern='/add', incoming=True, from_users=ADMIN_ID))
async def add_chat(event):
    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ اینجا ({chat_id}) به لیست مجاز اضافه شد.")
    else:
        await event.reply("⚠️ اینجا قبلاً اضافه شده است.")

@user_client.on(events.NewMessage(pattern='/del', outgoing=True))
@user_client.on(events.NewMessage(pattern='/del', incoming=True, from_users=ADMIN_ID))
async def del_chat(event):
    chat_id = event.chat_id
    if chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"🗑 اینجا ({chat_id}) از لیست مجاز حذف شد.")
    else:
        await event.reply("⚠️ اینجا در لیست نبود.")

@bot.on(events.NewMessage(pattern='/list'))
async def list_chats(event):
    if event.sender_id != ADMIN_ID: return
    msg = "**📋 لیست گروه‌ها/کانال‌های مجاز:**\n\n"
    for cid in ALLOWED_CHATS:
        msg += f"🆔 `{cid}`\n"
    await event.reply(msg)

# --- لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد را بفرستید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ پسورد: `/password ...`")
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
# 👤 اجرای مدیا (فقط در چت‌های مجاز)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def on_ply(event):
    chat_id = event.chat_id
    
    # ⛔️ چک کردن لیست سفید
    if chat_id not in ALLOWED_CHATS:
        return await event.reply("⛔️ این گروه/کانال مجاز نیست. ادمین باید `/add` بزند.")

    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.edit("❌ ریپلای کو؟")
    
    # اطلاعات فایل
    file_size_mb = reply.file.size / (1024 * 1024)
    sys_status = get_system_status()
    
    status = await event.reply(
        f"📥 **در حال دانلود...**\n"
        f"📦 حجم فایل: `{file_size_mb:.2f} MB`\n"
        f"⚙️ منابع سرور:\n{sys_status}"
    )
    await cleanup(chat_id)
    
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        
        if not path or os.path.getsize(path) == 0:
            return await status.edit("❌ دانلود خراب بود.")

        active_calls_data[chat_id] = {"path": path, "type": "file", "position": 0}
        
        await status.edit("🚀 **شروع پخش (بهینه شده)...**")
        await start_stream_engine(chat_id, path)
        await status.delete()
        
        try: await bot.send_message(chat_id, f"▶️ **پخش فایل فعال شد**", buttons=get_buttons(False))
        except: pass

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def on_live(event):
    chat_id = event.chat_id
    
    # ⛔️ چک کردن لیست سفید
    if chat_id not in ALLOWED_CHATS:
        return await event.reply("⛔️ اینجا مجاز نیست.")

    url = event.pattern_match.group(1).strip()
    title = "لینک دلخواه"
    
    # اگر لینک خالی بود یا سایت ایران اینترنشنال بود
    if not url or "iranintl" in url or "livetvstream" in url:
        url = IRAN_INTL_URL
        title = "ایران اینترنشنال"
    
    sys_status = get_system_status()
    status = await event.reply(f"📡 **اتصال به ماهواره...**\n{sys_status}")
    await cleanup(chat_id)
    
    try:
        # اگر لینک مستقیم نبود، با yt-dlp بگیر
        if url != IRAN_INTL_URL:
             s_url, s_title = await get_stream_link(url)
             if not s_url: return await status.edit("❌ لینک نامعتبر.")
             url = s_url
             title = s_title

        active_calls_data[chat_id] = {"path": url, "type": "live", "position": 0}
        
        await status.edit(f"🔴 **پخش زنده: {title}**\nکیفیت: SD (ضد لگ)")
        await start_stream_engine(chat_id, url)
        await status.delete()
        
        try: await bot.send_message(chat_id, f"🔴 **پخش زنده فعال**\n📺 {title}", buttons=get_buttons(True))
        except: pass
        
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 هندلر دکمه‌ها
# ==========================================
@bot.on(events.CallbackQuery)
async def on_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode()
    info = active_calls_data.get(chat_id)
    
    if not info and data != 'stop': return await event.answer("⚠️ پخش وجود ندارد.", alert=True)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ پایان پخش.")
            
        elif data == 'toggle':
            try: await call_py.resume_stream(chat_id)
            except: await call_py.pause_stream(chat_id)
            await event.answer("⏯")
            
        elif 'fw_' in data or 'rw_' in data:
            if info['type'] == 'live': return await event.answer("🚫 لایو عقب/جلو نمیشود.", alert=True)
            
            sec = 30 if 'fw_' in data else -30
            new_pos = max(0, info['position'] + sec)
            info['position'] = new_pos
            
            await event.answer(f"⏳ {new_pos}s")
            await start_stream_engine(chat_id, info['path'], start_time=new_pos)
            
    except Exception as e:
        await event.answer("خطا", alert=True)

@call_py.on_stream_end()
async def on_end(client, update):
    await client.leave_group_call(update.chat_id)
    await cleanup(update.chat_id)

# ==========================================
# 🌐 سرور
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Secured"))
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