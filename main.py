import os
import asyncio
import logging
import sys
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, Update
from pytgcalls.types.stream import StreamAudioEnded, StreamVideoEnded

# ==========================================
# 🔴 تنظیمات (اطلاعات خود را وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

# لینک پخش زنده (لینک m3u8 ایران اینترنشنال یا هر شبکه دیگر)
# نکته: لینک‌های پخش زنده ممکن است تغییر کنند. اگر کار نکرد، لینک جدید m3u8 پیدا کنید.
LIVE_STREAM_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"

# مسیرها
BOT_SESSION = 'bot_session'
USER_SESSION = 'user_session'
DOWNLOAD_PATH = "downloads/"

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# ایجاد پوشه دانلود
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

# پورت برای Render
PORT = int(os.environ.get("PORT", 8080))

# دیکشنری برای ذخیره مسیر فایل‌های در حال پخش (برای حذف بعدی)
active_files = {}

# ==========================================
# راه‌اندازی کلاینت‌ها
# ==========================================
bot = TelegramClient(BOT_SESSION, API_ID, API_HASH)
user_client = TelegramClient(USER_SESSION, API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# توابع کمکی
# ==========================================
async def delete_file(path):
    """حذف فایل از حافظه برای جلوگیری از پر شدن دیسک"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
            logger.info(f"🗑 فایل حذف شد: {path}")
        except Exception as e:
            logger.error(f"خطا در حذف فایل: {e}")

# ==========================================
# هندلرهای PyTgCalls (مدیریت پایان پخش)
# ==========================================
@call_py.on_stream_end()
async def on_stream_end(client: PyTgCalls, update: Update):
    """وقتی پخش فایل تمام شد، آن را پاک کن و از کال خارج شو"""
    chat_id = update.chat_id
    logger.info(f"Stream ended in {chat_id}")
    
    # خروج از کال
    try:
        await client.leave_call(chat_id)
    except:
        pass

    # حذف فایل از حافظه
    if chat_id in active_files:
        await delete_file(active_files[chat_id])
        del active_files[chat_id]

# ==========================================
# هندلرهای یوزربات (دستورات پخش)
# ==========================================

@user_client.on(events.NewMessage(pattern=r'^/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'^/ply', incoming=True, from_users=ADMIN_ID))
async def play_handler(event):
    """دانلود و پخش فایل ریپلای شده"""
    chat_id = event.chat_id
    reply = await event.get_reply_message()

    if not reply or not (reply.audio or reply.video):
        await event.reply("❌ **لطفاً روی یک آهنگ یا ویدئو ریپلای کنید.**")
        return

    msg = await event.reply("📥 **در حال دانلود فایل...**")

    try:
        # اگر قبلاً فایلی در حال پخش بود، پاکش کن
        if chat_id in active_files:
            await delete_file(active_files[chat_id])

        # دانلود فایل
        file_path = await reply.download_media(file=DOWNLOAD_PATH)
        active_files[chat_id] = file_path

        await msg.edit("🎧 **در حال پخش در ویس‌کال...**")

        # شروع پخش
        await call_py.play(
            chat_id,
            MediaStream(
                file_path,
            )
        )
    except Exception as e:
        logger.error(f"Play Error: {e}")
        await msg.edit(f"❌ خطا: `{str(e)}`\n\n*مطمئن شوید که یوزربات ادمین گروه است و ویس‌کال باز است.*")
        # اگر خطا داد، فایل دانلود شده را پاک کن
        if chat_id in active_files:
            await delete_file(active_files[chat_id])


@user_client.on(events.NewMessage(pattern=r'^/live', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'^/live', incoming=True, from_users=ADMIN_ID))
async def live_handler(event):
    """پخش زنده شبکه خبری"""
    chat_id = event.chat_id
    msg = await event.reply("📡 **در حال اتصال به پخش زنده...**")

    try:
        # پخش لینک استریم
        await call_py.play(
            chat_id,
            MediaStream(
                LIVE_STREAM_URL,
            )
        )
        await msg.edit("🔴 **پخش زنده شروع شد!**")
        
        # در حالت لایو فایلی برای حذف نداریم، اما اگر فایلی قبلا بوده پاکش میکنیم
        if chat_id in active_files:
            await delete_file(active_files[chat_id])
            del active_files[chat_id]

    except Exception as e:
        logger.error(f"Live Error: {e}")
        await msg.edit(f"❌ خطا در اتصال به لایو: `{str(e)}`")

@user_client.on(events.NewMessage(pattern=r'^/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern=r'^/stop', incoming=True, from_users=ADMIN_ID))
async def stop_handler(event):
    """توقف پخش و خروج"""
    chat_id = event.chat_id
    try:
        await call_py.leave_call(chat_id)
        await event.reply("⏹ **پخش متوقف شد.**")
        
        # پاکسازی فایل
        if chat_id in active_files:
            await delete_file(active_files[chat_id])
            del active_files[chat_id]
            
    except Exception as e:
        await event.reply(f"❌ خطا: {e}")

# ==========================================
# هندلرهای ربات (سیستم لاگین ادمین) - بدون تغییر
# ==========================================
login_state = {}

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id == ADMIN_ID:
        status = "🔴 قطع"
        try:
            if await user_client.is_user_authorized(): status = "🟢 متصل"
        except: pass
        await event.reply(f"👑 **پنل مدیریت موزیک**\nوضعیت: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code 12345`\n3️⃣ `/password ...`")
    else:
        await event.reply("⛔️ دسترسی محدود به ادمین.")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    ph = event.pattern_match.group(1).strip()
    msg = await event.reply("⏳ ...")
    try:
        if not user_client.is_connected(): await user_client.connect()
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد ارسال شد. بزن: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **یوزربات وصل شد!**")
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دو مرحله‌ای: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ لاگین موفق.")
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# وب سرور برای زنده نگه داشتن در Render
# ==========================================
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Music Userbot Running..."))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# ==========================================
# اجرای اصلی
# ==========================================
async def main():
    # استارت سرور وب
    await web_server()
    print("WebServer Started.")

    # استارت ربات مدیر
    await bot.start(bot_token=BOT_TOKEN)
    print("Bot Started.")
    
    # استارت کلاینت موزیک
    await call_py.start()
    print("PyTgCalls Started.")

    # استارت یوزربات (برای لاگین)
    # اگر قبلا لاگین شده باشد وصل می‌شود، اگر نه منتظر دستورات ربات می‌ماند
    if not await user_client.is_user_authorized():
        print("Waiting for login via Bot...")
    else:
        print("Userbot Authorized.")

    # اجرای مداوم
    await asyncio.gather(
        bot.run_until_disconnected(),
        user_client.run_until_disconnected()  # این خط مهم است تا هندلرهای یوزربات کار کنند
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass