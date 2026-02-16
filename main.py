import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.errors import SessionPasswordNeeded
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات (اطلاعات خود را وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

# لینک پخش زنده (شبکه ایران اینترنشنال یا هر لینک m3u8 دیگر)
# نکته: اگر لینک کار نکرد، باید لینک m3u8 جدید جایگزین کنید
LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"

# تنظیمات سیستم
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("MusicBot")

PORT = int(os.environ.get("PORT", 8080))

# ==========================================
# 🚀 راه‌اندازی کلاینت‌ها
# ==========================================
# کلاینت ربات (برای مدیریت لاگین)
bot = Client(
    "BotSession",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# کلاینت یوزربات (برای پخش موزیک)
user = Client(
    "UserSession",
    api_id=API_ID,
    api_hash=API_HASH,
    in_memory=True # سشن در حافظه موقت ذخیره می‌شود
)

call_py = PyTgCalls(user)

# دیکشنری برای ذخیره مسیر فایل‌های در حال پخش
active_chats_files = {}

# ==========================================
# 🛠 توابع کمکی (مدیریت فایل)
# ==========================================
async def remove_file(path):
    """حذف ایمن فایل از حافظه"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
            logger.info(f"🗑 File deleted: {path}")
        except Exception as e:
            logger.error(f"Error deleting file: {e}")

async def cleanup_chat(chat_id):
    """پاکسازی فایل‌های مربوط به یک چت"""
    if chat_id in active_chats_files:
        await remove_file(active_chats_files[chat_id])
        del active_chats_files[chat_id]

# ==========================================
# 🎵 هندلرهای پخش (PyTgCalls)
# ==========================================
@call_py.on_stream_end()
async def on_stream_end(client: PyTgCalls, update):
    """وقتی پخش تمام شد (چه دستی چه خودکار)"""
    chat_id = update.chat_id
    logger.info(f"Stream ended in {chat_id}")
    
    # خروج از کال
    try:
        await client.leave_call(chat_id)
    except:
        pass
    
    # حذف فایل از سرور
    await cleanup_chat(chat_id)

# ==========================================
# 🎮 دستورات یوزربات
# ==========================================

@user.on_message(filters.command("ply") & filters.user(ADMIN_ID))
async def play_command(client, message):
    chat_id = message.chat.id
    replied = message.reply_to_message

    # بررسی اینکه آیا روی فایل درستی ریپلای شده؟
    if not replied or not (replied.audio or replied.video or replied.document):
        return await message.reply("❌ **لطفاً روی یک آهنگ یا ویدئو ریپلای کنید.**")

    status_msg = await message.reply("📥 **در حال دانلود فایل...**")

    try:
        # اگر قبلاً فایلی بوده، پاکش کن
        await cleanup_chat(chat_id)

        # دانلود فایل
        file_path = await replied.download(os.path.join(DOWNLOAD_DIR, f"{chat_id}_{message.id}.mp4"))
        active_chats_files[chat_id] = file_path

        await status_msg.edit("🎧 **در حال اتصال به ویس‌کال...**")

        # پخش فایل
        await call_py.play(
            chat_id,
            MediaStream(
                file_path,
                audio_parameters=AudioVideoPiped.AudioParameters(bitrate=48000),
                video_parameters=AudioVideoPiped.VideoParameters(width=1280, height=720, frame_rate=30),
            )
        )
        await status_msg.edit("✅ **پخش شروع شد!**\n🗑 فایل پس از پایان، خودکار حذف می‌شود.")

    except Exception as e:
        logger.error(f"Play Error: {e}")
        await status_msg.edit(f"❌ **خطا:**\n`{str(e)}`")
        await cleanup_chat(chat_id)


@user.on_message(filters.command("live") & filters.user(ADMIN_ID))
async def live_command(client, message):
    chat_id = message.chat.id
    status_msg = await message.reply("📡 **در حال اتصال به پخش زنده...**")

    try:
        await cleanup_chat(chat_id)

        await call_py.play(
            chat_id,
            MediaStream(
                LIVE_URL,
                audio_parameters=AudioVideoPiped.AudioParameters(bitrate=48000),
                video_parameters=AudioVideoPiped.VideoParameters(width=1280, height=720, frame_rate=30),
            )
        )
        await status_msg.edit("🔴 **پخش زنده شروع شد!**")

    except Exception as e:
        await status_msg.edit(f"❌ خطا: {e}")


@user.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_command(client, message):
    chat_id = message.chat.id
    try:
        await call_py.leave_call(chat_id)
        await cleanup_chat(chat_id)
        await message.reply("⏹ **پخش متوقف شد.**")
    except Exception as e:
        await message.reply(f"❌ خطا: {e}")

# ==========================================
# 🔐 پنل مدیریت (لاگین)
# ==========================================
# متغیر موقت برای لاگین
login_cache = {}

@bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_bot(client, message):
    status = "🟢 متصل" if user.is_connected else "🔴 قطع"
    await message.reply(
        f"👋 **پنل مدیریت موزیک**\nوضعیت یوزربات: {status}\n\n"
        "1️⃣ `/phone +98912...`\n"
        "2️⃣ `/code 12345`\n"
        "3️⃣ `/password رمز`"
    )

@bot.on_message(filters.command("phone") & filters.user(ADMIN_ID))
async def login_phone(client, message):
    try:
        if len(message.command) < 2: return await message.reply("شماره را وارد کنید.")
        phone = message.command[1]
        
        if not user.is_connected: await user.connect()
        
        sent_code = await user.send_code(phone)
        login_cache['phone'] = phone
        login_cache['hash'] = sent_code.phone_code_hash
        
        await message.reply("✅ کد ارسال شد. حالا بزنید: `/code 12345`")
    except Exception as e:
        await message.reply(f"❌ خطا: {e}")

@bot.on_message(filters.command("code") & filters.user(ADMIN_ID))
async def login_code(client, message):
    try:
        if len(message.command) < 2: return await message.reply("کد را وارد کنید.")
        code = message.command[1]
        
        await user.sign_in(
            login_cache['phone'],
            login_cache['hash'],
            code
        )
        await message.reply("✅ **یوزربات با موفقیت وصل شد!**")
    except SessionPasswordNeeded:
        await message.reply("⚠️ **تایید دو مرحله‌ای دارید.**\nبزنید: `/password رمز`")
    except Exception as e:
        await message.reply(f"❌ خطا: {e}")

@bot.on_message(filters.command("password") & filters.user(ADMIN_ID))
async def login_password(client, message):
    try:
        if len(message.command) < 2: return await message.reply("رمز را وارد کنید.")
        pwd = message.command[1]
        
        await user.check_password(password=pwd)
        await message.reply("✅ **ورود موفقیت آمیز بود!**")
    except Exception as e:
        await message.reply(f"❌ خطا: {e}")

# ==========================================
# 🌐 وب‌سرور (زنده نگه داشتن در Render)
# ==========================================
async def web_handler(request):
    return web.Response(text="Music Bot is Running correctly.")

async def main():
    # 1. اجرای وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    # 2. اجرای کلاینت‌ها
    await bot.start()
    await call_py.start()
    
    # 3. اتصال یوزربات اگر سشن داشت
    try:
        if not user.is_connected:
            await user.connect()
    except Exception:
        pass
        
    print("✅ Bot is fully up and running!")
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())