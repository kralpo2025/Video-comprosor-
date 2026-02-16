import os
import asyncio
import logging
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from pytgcalls import PyTgCalls, idle
from pytgcalls.types import AudioVideoPiped, MediaStream
from pytgcalls.types.stream import StreamAudioEnded, StreamVideoEnded

# ==========================================
# ⚙️ تنظیمات (اطلاعات خود را دقیق وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

# لینک پخش زنده (شبکه خبر)
LIVE_STREAM_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"

# مسیرها
DOWNLOAD_PATH = "downloads/"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MusicBot")

# پورت رندر
PORT = int(os.environ.get("PORT", 8080))

# دیکشنری برای مدیریت فایل‌های دانلودی
active_chats = {}

# ==========================================
# 🚀 راه‌اندازی کلاینت‌ها
# ==========================================
# کلاینت ربات (مدیریت)
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# کلاینت یوزربات (پخش کننده)
user = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user)

# ==========================================
# 🗑 توابع کمکی
# ==========================================
async def delete_file(path):
    """حذف ایمن فایل از حافظه"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
            logger.info(f"🗑 فایل حذف شد: {path}")
        except Exception as e:
            logger.error(f"خطا در حذف فایل: {e}")

async def cleanup_chat(chat_id):
    """پاکسازی فایل‌های یک گروه خاص"""
    if chat_id in active_chats:
        await delete_file(active_chats[chat_id])
        del active_chats[chat_id]

# ==========================================
# 🎵 هندلرهای پخش (PyTgCalls)
# ==========================================
@call_py.on_stream_end()
async def on_stream_end(client: PyTgCalls, update):
    """وقتی پخش تمام شد"""
    chat_id = update.chat_id
    logger.info(f"پخش در گروه {chat_id} تمام شد.")
    
    # خروج از کال
    try:
        await client.leave_call(chat_id)
    except:
        pass
    
    # حذف فایل
    await cleanup_chat(chat_id)

# ==========================================
# 🎮 دستورات یوزربات
# ==========================================

@user.on(events.NewMessage(pattern=r'^/ply'))
async def play_handler(event):
    """دانلود و پخش فایل"""
    # فقط ادمین یا خود یوزربات
    if event.sender_id != ADMIN_ID and not event.out:
        return

    chat_id = event.chat_id
    reply = await event.get_reply_message()

    if not reply or not (reply.audio or reply.video):
        await event.reply("❌ **روی یک آهنگ یا ویدئو ریپلای کن!**")
        return

    msg = await event.reply("📥 **در حال دانلود...**")

    try:
        # پاکسازی فایل قبلی اگر وجود داشت
        await cleanup_chat(chat_id)

        # دانلود
        file_path = await reply.download_media(file=DOWNLOAD_PATH)
        active_chats[chat_id] = file_path

        await msg.edit("🎧 **در حال اتصال به ویس‌کال...**")

        # پخش
        await call_py.play(
            chat_id,
            MediaStream(
                file_path,
                audio_parameters=AudioVideoPiped.AudioParameters(bitrate=48000),
                video_parameters=AudioVideoPiped.VideoParameters(width=1280, height=720, frame_rate=30)
            )
        )
        await msg.edit("✅ **پخش شروع شد!**\n🗑 فایل بعد از اتمام، خودکار پاک می‌شود.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit(f"❌ **خطا:**\n`{str(e)}`")
        await cleanup_chat(chat_id)

@user.on(events.NewMessage(pattern=r'^/live'))
async def live_handler(event):
    """پخش زنده"""
    if event.sender_id != ADMIN_ID and not event.out:
        return

    chat_id = event.chat_id
    msg = await event.reply("📡 **در حال دریافت سیگنال پخش زنده...**")

    try:
        await cleanup_chat(chat_id)
        
        await call_py.play(
            chat_id,
            MediaStream(
                LIVE_STREAM_URL,
                audio_parameters=AudioVideoPiped.AudioParameters(bitrate=48000),
                video_parameters=AudioVideoPiped.VideoParameters(width=1280, height=720, frame_rate=30)
            )
        )
        await msg.edit("🔴 **پخش زنده شبکه خبر شروع شد!**")

    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user.on(events.NewMessage(pattern=r'^/stop'))
async def stop_handler(event):
    if event.sender_id != ADMIN_ID and not event.out:
        return
        
    chat_id = event.chat_id
    try:
        await call_py.leave_call(chat_id)
        await cleanup_chat(chat_id)
        await event.reply("⏹ **پخش متوقف شد.**")
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🔐 پنل لاگین (مدیریت با ربات)
# ==========================================
login_state = {}

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID: return
    
    status = "🔴 قطع"
    if await user.is_user_authorized(): status = "🟢 متصل"
    
    await event.reply(
        f"👋 **پنل مدیریت**\nوضعیت یوزربات: {status}\n\n"
        "1️⃣ `/phone +98912...`\n"
        "2️⃣ `/code 12345`\n"
        "3️⃣ `/password ....`"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    phone = event.pattern_match.group(1).strip()
    try:
        if not user.is_connected(): await user.connect()
        sent = await user.send_code_request(phone)
        login_state['phone'] = phone
        login_state['hash'] = sent.phone_code_hash
        await event.reply("✅ کد ارسال شد. حالا کد را بفرست: `/code 12345`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **یوزربات وصل شد!**")
    except SessionPasswordNeededError:
        await event.reply("⚠️ **رمز دوم دارید.** بفرستید: `/password رمز`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود موفق.")
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🌐 وب سرور و اجرا
# ==========================================
async def web_handler(request):
    return web.Response(text="Bot Running")

async def main():
    # راه‌اندازی وب سرور
    app = web.Application()
    app.router.add_get('/', web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    # راه‌اندازی کلاینت‌ها
    await user.start()
    await call_py.start()
    
    print("✅ همه سیستم‌ها روشن شدند.")
    
    # زنده نگه داشتن
    await idle()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())