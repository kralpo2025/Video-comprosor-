import os
import asyncio
import logging
import wget
import tarfile
import shutil
import sys
import time
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
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

# لینک پیش‌فرض برای دستور /live (اگر لینکی داده نشود)
DEFAULT_LIVE_URL = "https://www.youtube.com/live/A92pqZQAsm8?si=LMguHUxEkBAZRNWX"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

login_state = {}

# دیکشنری برای ذخیره وضعیت پخش هر گروه (برای جلو/عقب کردن)
# ساختار: {chat_id: {"path": str, "type": "file"|"live", "position": int, "msg_id": int}}
active_calls_data = {}

# ساخت پوشه دانلود
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🛠 نصب FFmpeg (خودکار)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    if shutil.which("ffmpeg"):
        logger.info(f"✅ FFmpeg detected.")
        return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        print()
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        logger.info("✅ FFmpeg Installed.")
    except Exception as e:
        logger.error(f"❌ FFmpeg Install Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی (Helper Functions)
# ==========================================

async def cleanup(chat_id):
    """پاکسازی فایل‌ها و اطلاعات حافظه برای یک گروه"""
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        # اگر فایل لوکال بود و وجود داشت، حذف کن
        if data.get("type") == "file" and path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"🗑 Deleted file: {path}")
            except Exception as e:
                logger.error(f"Error deleting file: {e}")
        
        # حذف از حافظه رم
        del active_calls_data[chat_id]

async def get_live_stream_url(youtube_url):
    """استخراج لینک مستقیم (m3u8) از یوتیوب با yt-dlp"""
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            return info['url'], info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"Yt-dlp error: {e}")
        return None, None

def get_control_buttons(is_live=False):
    """تولید دکمه‌های کنترلی"""
    if is_live:
        return [[Button.inline("❌ توقف پخش", data=b'stop')]]
    else:
        return [
            [
                Button.inline("⏪ 30s", data=b'rewind_30'),
                Button.inline("⏸/▶️", data=b'pause_resume'),
                Button.inline("⏩ 30s", data=b'forward_30')
            ],
            [Button.inline("❌ توقف و پاکسازی", data=b'stop')]
        ]

async def ensure_player_active():
    """اطمینان از روشن بودن موتور پخش"""
    if not call_py.active_calls:
        try:
            await call_py.start()
        except RuntimeError:
            pass

async def smart_stream(chat_id, source, start_time=0, stream_type="video"):
    """
    مدیریت پخش هوشمند
    source: مسیر فایل یا لینک
    start_time: زمان شروع (برای seek)
    stream_type: video یا audio
    """
    # تنظیمات کیفیت: SD_480p برای جلوگیری از لگ در سرورهای ضعیف بسیار مهم است
    # کیفیت صدا روی MEDIUM تنظیم شده تا پهنای باند کمتری بگیرد
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p if stream_type == "video" else None,
        ffmpeg_parameters=f"-ss {start_time}" if start_time > 0 else ""
    )

    try:
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        error = str(e).lower()
        if "already" in error or "group call" in error:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except Exception as e2:
                # اگر تغییر استریم کار نکرد، خارج شو و دوباره وارد شو
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream)
        elif "no group call" in error:
            raise Exception("⚠️ **ویس‌کال خاموش است!**")
        else:
            raise e

# ==========================================
# 🎮 هندلر دکمه‌ها (Callback Query)
# ==========================================
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.answer("⛔️ شما ادمین نیستید.", alert=True)
    
    chat_id = event.chat_id
    data = event.data.decode('utf-8')
    
    if chat_id not in active_calls_data and data != 'stop':
        return await event.answer("⚠️ پخشی در جریان نیست.", alert=True)
        
    info = active_calls_data.get(chat_id)

    try:
        if data == 'stop':
            await call_py.leave_group_call(chat_id)
            await cleanup(chat_id)
            await event.edit("⏹ **پخش متوقف شد.**", buttons=None)
            
        elif data == 'pause_resume':
            status = await call_py.pause_stream(chat_id)
            # اگر pause شد True برمیگردونه، اگر resume شد False (در برخی ورژن ها)
            # اما معمولا متد pause_stream وضعیت رو تغییر میده.
            # برای سادگی در نسخه های قدیمی:
            try:
                # تلاش برای resume اگر pause است
                await call_py.resume_stream(chat_id)
                await event.answer("▶️ ادامه پخش")
            except:
                await call_py.pause_stream(chat_id)
                await event.answer("⏸ توقف موقت")

        elif data.startswith('forward_') or data.startswith('rewind_'):
            if info['type'] == 'live':
                return await event.answer("⚠️ در پخش زنده امکان عقب/جلو وجود ندارد.", alert=True)
            
            seconds = int(data.split('_')[1])
            if 'rewind' in data:
                seconds = -seconds
            
            new_pos = max(0, info['position'] + seconds)
            info['position'] = new_pos # آپدیت موقعیت در حافظه
            
            await event.answer(f"⏳ پرش به ثانیه {new_pos}...")
            
            # شروع مجدد استریم از موقعیت جدید
            await smart_stream(chat_id, info['path'], start_time=new_pos)
            
    except Exception as e:
        logger.error(f"Callback Error: {e}")
        await event.answer("خطا در اجرا", alert=True)

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    logger.info(f"Stream ended for {chat_id}")
    try:
        await client.leave_group_call(chat_id)
    except: pass
    await cleanup(chat_id)

# ==========================================
# 🎵 دستورات ربات (Userbot Commands)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await ensure_player_active()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ روی یک آهنگ یا ویدیو ریپلای کنید.")
    
    msg = await event.reply("📥 **در حال دانلود فایل...**")
    chat_id = event.chat_id
    
    # اول قبلی رو پاک کن
    await cleanup(chat_id)
    
    try:
        file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4") # همه چیز رو MP4 ذخیره میکنیم موقتا
        path = await reply.download_media(file=file_path)
        
        if not path or not os.path.exists(path):
            return await msg.edit("❌ دانلود ناموفق بود.")

        # ذخیره اطلاعات برای مدیریت بعدی
        active_calls_data[chat_id] = {
            "path": path,
            "type": "file",
            "position": 0,
            "msg_id": msg.id
        }

        await msg.edit("🎧 **در حال آماده‌سازی پخش...**")
        
        # پخش با شروع از ثانیه 0
        await smart_stream(chat_id, path, start_time=0)
        
        await msg.edit(
            f"▶️ **پخش شروع شد!**\n📂 فایل: `{os.path.basename(path)}`", 
            buttons=get_control_buttons(is_live=False)
        )
        
    except Exception as e:
        logger.error(f"Play Error: {e}")
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'/live ?(.*)', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await ensure_player_active()
    
    # گرفتن لینک از جلوی دستور
    input_url = event.pattern_match.group(1).strip()
    
    # اگر لینک وارد نشده بود، از لینک پیش‌فرض (ایران اینترنشنال) استفاده کن
    target_url = input_url if input_url else DEFAULT_LIVE_URL
    
    msg = await event.reply(f"📡 **در حال پردازش لینک پخش زنده...**\n🔗 `{target_url}`")
    chat_id = event.chat_id
    
    await cleanup(chat_id)
    
    try:
        # استخراج لینک مستقیم M3U8
        stream_url, title = await get_live_stream_url(target_url)
        
        if not stream_url:
            return await msg.edit("❌ نتوانستم لینک پخش زنده را پیدا کنم. شاید لینک نامعتبر است.")
            
        active_calls_data[chat_id] = {
            "path": stream_url,
            "type": "live",
            "position": 0
        }

        await smart_stream(chat_id, stream_url, stream_type="video")
        
        await msg.edit(
            f"🔴 **پخش زنده شروع شد!**\n📺 عنوان: **{title}**", 
            buttons=get_control_buttons(is_live=True)
        )
        
    except Exception as e:
        logger.error(f"Live Error: {e}")
        await msg.edit(f"❌ خطا: {e}")

# ==========================================
# 🤖 دستورات مدیریتی (Bot Commands)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID: return
    await event.reply(
        "👋 **پنل مدیریت ربات موزیک**\n\n"
        "1️⃣ `/ply` (ریپلای روی مدیا)\n"
        "2️⃣ `/live [link]` (پخش زنده - خالی بگذارید برای شبکه پیشفرض)\n"
        "3️⃣ `/ping` (بررسی وضعیت)\n"
        "🔑 **مدیریت لاگین:**\n`/phone` | `/code` | `/password`"
    )

@bot.on(events.NewMessage(pattern='/ping'))
async def ping_h(event):
    start = time.time()
    msg = await event.reply("Pong!")
    end = time.time()
    uptime = f"{round((end - start) * 1000)}ms"
    active_c = len(call_py.active_calls)
    await msg.edit(f"🟢 **آنلاین**\n📶 پینگ: `{uptime}`\n🔊 تماس‌های فعال: `{active_c}`")

# هندلرهای لاگین یوزربات (همان کدهای قبلی شما با کمی تمیزکاری)
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ ...")
        if not user_client.is_connected(): await user_client.connect()
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد را بفرستید: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await ensure_player_active()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await ensure_player_active()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🌐 سرور وب (Keep Alive)
# ==========================================
async def web_handler(r): return web.Response(text="Music Bot is Running & Healthy")

async def start_web():
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌍 Web Server Started on Port {PORT}")

async def main():
    asyncio.create_task(start_web())
    
    logger.info("🤖 Bot Connecting...")
    await bot.start(bot_token=BOT_TOKEN)
    
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Connected")
            await ensure_player_active()
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass