import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from telethon import TelegramClient, events, Button
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

# مسیر دانلود و پورت سرور
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

# تنظیم لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای وضعیت
login_state = {}
active_calls_data = {}  # ذخیره اطلاعات پخش هر گروه

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🛠 نصب خودکار FFmpeg (برای سرورهای خام)
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
        logger.error(f"FFmpeg Install Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# ربات (فقط برای مدیریت و ارسال دکمه)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# یوزربات (برای دانلود مدیا و جوین شدن در ویس کال)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# پلیر
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی (Helpers)
# ==========================================

async def cleanup(chat_id):
    """پاکسازی فایل و رم"""
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        
        # اگر فایل دانلود شده بود (لایو نبود)، حذفش کن
        if data.get("type") == "file" and path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"Deleted file: {path}")
            except: pass
        
        # حذف از دیکشنری وضعیت
        del active_calls_data[chat_id]

async def get_stream_link(url):
    """استخراج لینک مستقیم استریم از یوتیوب"""
    ydl_opts = {'format': 'best[ext=mp4]/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"Yt-dlp: {e}")
        return None, None

def get_buttons(is_live=False):
    """تولید دکمه‌ها"""
    if is_live:
        return [[Button.inline("❌ توقف پخش", data=b'stop')]]
    
    return [
        [
            Button.inline("⏪ 30 ثانیه", data=b'rw_30'),
            Button.inline("⏯ مکث/ادامه", data=b'toggle'),
            Button.inline("⏩ 30 ثانیه", data=b'fw_30')
        ],
        [Button.inline("❌ توقف و حذف", data=b'stop')]
    ]

async def start_stream_engine(chat_id, source, start_time=0):
    """مدیریت هوشمند پخش و اتصال"""
    # اطمینان از روشن بودن موتور
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت (480p برای جلوگیری از لگ)
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=f"-ss {start_time}" if start_time > 0 else ""
    )

    try:
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        err = str(e).lower()
        if "already" in err or "group call" in err:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except:
                # اگر تغییر استریم نشد، خروج و ورود مجدد
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream)
        elif "no group call" in err:
            raise Exception("ویس‌کال گروه خاموش است! لطفا آن را روشن کنید.")
        else:
            raise e

# ==========================================
# 🤖 بخش مدیریت ربات (فقط دستورات ادمین و لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    # بررسی وضعیت اتصال یوزربات
    is_connected = False
    try:
        if user_client.is_connected() and await user_client.is_user_authorized():
            is_connected = True
    except: pass

    status_text = "🟢 **متصل**" if is_connected else "🔴 **قطع**"
    
    msg = (
        f"👋 سلام رئیس!\n"
        f"📊 وضعیت اکانت تلگرام: {status_text}\n\n"
        f"💡 **راهنما:**\n"
        f"برای استفاده از ربات، دستورات زیر را در گروه ارسال کنید (توسط اکانت خودتان یا هر کسی، ربات فقط اجرا می‌کند):\n\n"
        f"1️⃣ **پخش فایل:** روی آهنگ یا ویدیو ریپلای کنید و بنویسید `/ply`\n"
        f"2️⃣ **پخش زنده:** دستور `/live [لینک]` (بدون لینک شبکه ایران اینترنشنال پخش میشود)\n\n"
        f"🔑 **دستورات لاگین (اینجا بفرستید):**\n"
        f"`/phone +98912...`\n`/code 12345`\n`/password ...`"
    )
    await event.reply(msg)

# --- پروسه لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def login_phone(event):
    if event.sender_id != ADMIN_ID: return
    try:
        phone = event.pattern_match.group(1).strip()
        if not user_client.is_connected(): await user_client.connect()
        sent = await user_client.send_code_request(phone)
        login_state['phone'] = phone
        login_state['hash'] = sent.phone_code_hash
        await event.reply("✅ کد ارسال شد. بفرستید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def login_code(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین با موفقیت انجام شد!** حالا می‌تونید تو گروه دستورات رو بزنید.")
    except SessionPasswordNeededError:
        await event.reply("⚠️ اکانت رمز دوم دارد. بفرستید: `/password ...`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def login_pass(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود تکمیل شد.**")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 👤 بخش یوزربات (اجرای دستورات مدیا)
# ==========================================

@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def user_play_handler(event):
    """هندلر پخش فایل (ریپلای)"""
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.edit("❌ روی یک مدیا ریپلای کن.")

    chat_id = event.chat_id
    status_msg = await event.reply("📥 **در حال دانلود...**")
    
    # پاکسازی پخش قبلی
    await cleanup(chat_id)

    try:
        # دانلود فایل
        dl_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4")
        path = await reply.download_media(file=dl_path)
        
        if not path:
            return await status_msg.edit("❌ دانلود نشد.")

        # ذخیره وضعیت
        active_calls_data[chat_id] = {
            "path": path,
            "type": "file",
            "position": 0
        }

        # شروع پخش
        await status_msg.edit("🎧 **اتصال به ویس‌کال...**")
        await start_stream_engine(chat_id, path, start_time=0)
        
        # حذف پیام وضعیت یوزربات
        await status_msg.delete()

        # ارسال پنل شیشه‌ای توسط ربات (چون یوزربات نمیتونه دکمه بفرسته)
        try:
            await bot.send_message(
                chat_id,
                f"▶️ **پخش فایل شروع شد**\n📂 فایل: `{os.path.basename(path)}`",
                buttons=get_buttons(is_live=False)
            )
        except Exception:
            # اگر ربات در گروه نبود، یوزربات پیام متنی میفرستد
            await event.reply("⚠️ **توجه:** برای نمایش دکمه‌های کنترلی، ربات (بات مادر) را در گروه ادمین کنید.")

    except Exception as e:
        logger.error(f"Play Error: {e}")
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def user_live_handler(event):
    """هندلر پخش زنده"""
    input_url = event.pattern_match.group(1).strip()
    
    # لینک پیش‌فرض: ایران اینترنشنال
    DEFAULT_LIVE = "https://www.youtube.com/live/A92pqZQAsm8?si=LMguHUxEkBAZRNWX"
    target_url = input_url if input_url else DEFAULT_LIVE
    
    chat_id = event.chat_id
    status_msg = await event.reply("📡 **دریافت لینک استریم...**")
    
    await cleanup(chat_id)

    try:
        stream_url, title = await get_stream_link(target_url)
        if not stream_url:
            return await status_msg.edit("❌ لینک استریم یافت نشد.")

        active_calls_data[chat_id] = {
            "path": stream_url,
            "type": "live",
            "position": 0
        }

        await status_msg.edit(f"🔴 **در حال اتصال به: {title}**")
        await start_stream_engine(chat_id, stream_url)
        
        await status_msg.delete()
        
        try:
            await bot.send_message(
                chat_id,
                f"🔴 **پخش زنده فعال شد**\n📺 کانال: **{title}**",
                buttons=get_buttons(is_live=True)
            )
        except:
            await event.reply("⚠️ ربات در گروه نیست، دکمه‌ها نمایش داده نمی‌شوند.")

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 هندلر دکمه‌ها (فقط ربات)
# ==========================================
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.answer("⛔️ دست نزن بچه!", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode('utf-8')
    
    info = active_calls_data.get(chat_id)
    
    # اگر پخشی نیست و دکمه استاپ نیست، ارور بده
    if not info and data != 'stop':
        return await event.answer("⚠️ پخش فعالی وجود ندارد.", alert=True)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ **پخش متوقف و فایل پاک شد.**", buttons=None)

        elif data == 'toggle':
            # پایتون-تلگرام-کالز متد ساده برای وضعیت ندارد، سعی میکنیم ریزوم کنیم اگر ارور داد پاز میکنیم
            try:
                await call_py.resume_stream(chat_id)
                await event.answer("▶️ ادامه")
            except:
                await call_py.pause_stream(chat_id)
                await event.answer("⏸ مکث")

        elif data.startswith('fw_') or data.startswith('rw_'):
            if info['type'] == 'live':
                return await event.answer("⚠️ در پخش زنده نمی‌توان عقب/جلو کرد.", alert=True)
            
            sec = int(data.split('_')[1])
            if 'rw' in data: sec = -sec
            
            new_pos = max(0, info['position'] + sec)
            info['position'] = new_pos
            
            await event.answer(f"⏳ پرش به ثانیه {new_pos}...")
            await start_stream_engine(chat_id, info['path'], start_time=new_pos)

    except Exception as e:
        logger.error(f"Button Error: {e}")
        await event.answer("خطا در اجرا", alert=True)

@call_py.on_stream_end()
async def stream_ended(client, update):
    chat_id = update.chat_id
    try: await client.leave_group_call(chat_id)
    except: pass
    await cleanup(chat_id)

# ==========================================
# 🌐 سرور وب (برای روشن ماندن در Render)
# ==========================================
async def web_handler(r): return web.Response(text="Bot is Running...")

async def main():
    # راه‌اندازی وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    asyncio.create_task(site.start())
    
    logger.info("🤖 Starting Bot & Userbot...")
    
    # استارت ربات
    await bot.start(bot_token=BOT_TOKEN)
    
    # اتصال یوزربات (بدون لاگین اجباری، لاگین از طریق ربات انجام میشه)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("✅ Userbot is Logged In")
            if not call_py.active_calls:
                await call_py.start()
        else:
            logger.info("⚠️ Userbot Not Logged In. Use /start in Bot PV.")
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from telethon import TelegramClient, events, Button
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

# مسیر دانلود و پورت سرور
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

# تنظیم لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای وضعیت
login_state = {}
active_calls_data = {}  # ذخیره اطلاعات پخش هر گروه

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🛠 نصب خودکار FFmpeg (برای سرورهای خام)
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
        logger.error(f"FFmpeg Install Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
# ربات (فقط برای مدیریت و ارسال دکمه)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)

# یوزربات (برای دانلود مدیا و جوین شدن در ویس کال)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# پلیر
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی (Helpers)
# ==========================================

async def cleanup(chat_id):
    """پاکسازی فایل و رم"""
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        
        # اگر فایل دانلود شده بود (لایو نبود)، حذفش کن
        if data.get("type") == "file" and path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"Deleted file: {path}")
            except: pass
        
        # حذف از دیکشنری وضعیت
        del active_calls_data[chat_id]

async def get_stream_link(url):
    """استخراج لینک مستقیم استریم از یوتیوب"""
    ydl_opts = {'format': 'best[ext=mp4]/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"Yt-dlp: {e}")
        return None, None

def get_buttons(is_live=False):
    """تولید دکمه‌ها"""
    if is_live:
        return [[Button.inline("❌ توقف پخش", data=b'stop')]]
    
    return [
        [
            Button.inline("⏪ 30 ثانیه", data=b'rw_30'),
            Button.inline("⏯ مکث/ادامه", data=b'toggle'),
            Button.inline("⏩ 30 ثانیه", data=b'fw_30')
        ],
        [Button.inline("❌ توقف و حذف", data=b'stop')]
    ]

async def start_stream_engine(chat_id, source, start_time=0):
    """مدیریت هوشمند پخش و اتصال"""
    # اطمینان از روشن بودن موتور
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت (480p برای جلوگیری از لگ)
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM,
        video_parameters=VideoQuality.SD_480p,
        ffmpeg_parameters=f"-ss {start_time}" if start_time > 0 else ""
    )

    try:
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        err = str(e).lower()
        if "already" in err or "group call" in err:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except:
                # اگر تغییر استریم نشد، خروج و ورود مجدد
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream)
        elif "no group call" in err:
            raise Exception("ویس‌کال گروه خاموش است! لطفا آن را روشن کنید.")
        else:
            raise e

# ==========================================
# 🤖 بخش مدیریت ربات (فقط دستورات ادمین و لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    # بررسی وضعیت اتصال یوزربات
    is_connected = False
    try:
        if user_client.is_connected() and await user_client.is_user_authorized():
            is_connected = True
    except: pass

    status_text = "🟢 **متصل**" if is_connected else "🔴 **قطع**"
    
    msg = (
        f"👋 سلام رئیس!\n"
        f"📊 وضعیت اکانت تلگرام: {status_text}\n\n"
        f"💡 **راهنما:**\n"
        f"برای استفاده از ربات، دستورات زیر را در گروه ارسال کنید (توسط اکانت خودتان یا هر کسی، ربات فقط اجرا می‌کند):\n\n"
        f"1️⃣ **پخش فایل:** روی آهنگ یا ویدیو ریپلای کنید و بنویسید `/ply`\n"
        f"2️⃣ **پخش زنده:** دستور `/live [لینک]` (بدون لینک شبکه ایران اینترنشنال پخش میشود)\n\n"
        f"🔑 **دستورات لاگین (اینجا بفرستید):**\n"
        f"`/phone +98912...`\n`/code 12345`\n`/password ...`"
    )
    await event.reply(msg)

# --- پروسه لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def login_phone(event):
    if event.sender_id != ADMIN_ID: return
    try:
        phone = event.pattern_match.group(1).strip()
        if not user_client.is_connected(): await user_client.connect()
        sent = await user_client.send_code_request(phone)
        login_state['phone'] = phone
        login_state['hash'] = sent.phone_code_hash
        await event.reply("✅ کد ارسال شد. بفرستید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def login_code(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین با موفقیت انجام شد!** حالا می‌تونید تو گروه دستورات رو بزنید.")
    except SessionPasswordNeededError:
        await event.reply("⚠️ اکانت رمز دوم دارد. بفرستید: `/password ...`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def login_pass(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود تکمیل شد.**")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 👤 بخش یوزربات (اجرای دستورات مدیا)
# ==========================================

@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def user_play_handler(event):
    """هندلر پخش فایل (ریپلای)"""
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.edit("❌ روی یک مدیا ریپلای کن.")

    chat_id = event.chat_id
    status_msg = await event.reply("📥 **در حال دانلود...**")
    
    # پاکسازی پخش قبلی
    await cleanup(chat_id)

    try:
        # دانلود فایل
        dl_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4")
        path = await reply.download_media(file=dl_path)
        
        if not path:
            return await status_msg.edit("❌ دانلود نشد.")

        # ذخیره وضعیت
        active_calls_data[chat_id] = {
            "path": path,
            "type": "file",
            "position": 0
        }

        # شروع پخش
        await status_msg.edit("🎧 **اتصال به ویس‌کال...**")
        await start_stream_engine(chat_id, path, start_time=0)
        
        # حذف پیام وضعیت یوزربات
        await status_msg.delete()

        # ارسال پنل شیشه‌ای توسط ربات (چون یوزربات نمیتونه دکمه بفرسته)
        try:
            await bot.send_message(
                chat_id,
                f"▶️ **پخش فایل شروع شد**\n📂 فایل: `{os.path.basename(path)}`",
                buttons=get_buttons(is_live=False)
            )
        except Exception:
            # اگر ربات در گروه نبود، یوزربات پیام متنی میفرستد
            await event.reply("⚠️ **توجه:** برای نمایش دکمه‌های کنترلی، ربات (بات مادر) را در گروه ادمین کنید.")

    except Exception as e:
        logger.error(f"Play Error: {e}")
        await event.reply(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def user_live_handler(event):
    """هندلر پخش زنده"""
    input_url = event.pattern_match.group(1).strip()
    
    # لینک پیش‌فرض: ایران اینترنشنال
    DEFAULT_LIVE = "https://www.youtube.com/live/A92pqZQAsm8?si=LMguHUxEkBAZRNWX"
    target_url = input_url if input_url else DEFAULT_LIVE
    
    chat_id = event.chat_id
    status_msg = await event.reply("📡 **دریافت لینک استریم...**")
    
    await cleanup(chat_id)

    try:
        stream_url, title = await get_stream_link(target_url)
        if not stream_url:
            return await status_msg.edit("❌ لینک استریم یافت نشد.")

        active_calls_data[chat_id] = {
            "path": stream_url,
            "type": "live",
            "position": 0
        }

        await status_msg.edit(f"🔴 **در حال اتصال به: {title}**")
        await start_stream_engine(chat_id, stream_url)
        
        await status_msg.delete()
        
        try:
            await bot.send_message(
                chat_id,
                f"🔴 **پخش زنده فعال شد**\n📺 کانال: **{title}**",
                buttons=get_buttons(is_live=True)
            )
        except:
            await event.reply("⚠️ ربات در گروه نیست، دکمه‌ها نمایش داده نمی‌شوند.")

    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🎮 هندلر دکمه‌ها (فقط ربات)
# ==========================================
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.answer("⛔️ دست نزن بچه!", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode('utf-8')
    
    info = active_calls_data.get(chat_id)
    
    # اگر پخشی نیست و دکمه استاپ نیست، ارور بده
    if not info and data != 'stop':
        return await event.answer("⚠️ پخش فعالی وجود ندارد.", alert=True)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ **پخش متوقف و فایل پاک شد.**", buttons=None)

        elif data == 'toggle':
            # پایتون-تلگرام-کالز متد ساده برای وضعیت ندارد، سعی میکنیم ریزوم کنیم اگر ارور داد پاز میکنیم
            try:
                await call_py.resume_stream(chat_id)
                await event.answer("▶️ ادامه")
            except:
                await call_py.pause_stream(chat_id)
                await event.answer("⏸ مکث")

        elif data.startswith('fw_') or data.startswith('rw_'):
            if info['type'] == 'live':
                return await event.answer("⚠️ در پخش زنده نمی‌توان عقب/جلو کرد.", alert=True)
            
            sec = int(data.split('_')[1])
            if 'rw' in data: sec = -sec
            
            new_pos = max(0, info['position'] + sec)
            info['position'] = new_pos
            
            await event.answer(f"⏳ پرش به ثانیه {new_pos}...")
            await start_stream_engine(chat_id, info['path'], start_time=new_pos)

    except Exception as e:
        logger.error(f"Button Error: {e}")
        await event.answer("خطا در اجرا", alert=True)

@call_py.on_stream_end()
async def stream_ended(client, update):
    chat_id = update.chat_id
    try: await client.leave_group_call(chat_id)
    except: pass
    await cleanup(chat_id)

# ==========================================
# 🌐 سرور وب (برای روشن ماندن در Render)
# ==========================================
async def web_handler(r): return web.Response(text="Bot is Running...")

async def main():
    # راه‌اندازی وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    asyncio.create_task(site.start())
    
    logger.info("🤖 Starting Bot & Userbot...")
    
    # استارت ربات
    await bot.start(bot_token=BOT_TOKEN)
    
    # اتصال یوزربات (بدون لاگین اجباری، لاگین از طریق ربات انجام میشه)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("✅ Userbot is Logged In")
            if not call_py.active_calls:
                await call_py.start()
        else:
            logger.info("⚠️ Userbot Not Logged In. Use /start in Bot PV.")
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main()