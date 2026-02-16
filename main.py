import os
import asyncio
import logging
import wget
import tarfile
import shutil
import sys
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات (دقیق وارد شود)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
# آیدی عددی ادمین (اینجا هاردکد شده، اگر اشتباه باشد ربات به شما آیدی صحیح را می‌گوید)
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

# لاگینگ را روی INFO می‌گذاریم تا همه چیز را ببینیم
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای حافظه
login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب‌کننده FFmpeg (قبل از هر چیز)
# ==========================================
def install_ffmpeg():
    os.environ["PATH"] += os.pathsep + os.getcwd()
    if os.path.exists("ffmpeg"):
        return
    logger.info("⏳ در حال دانلود ابزار پخش (FFmpeg)...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), "./ffmpeg")
                os.chmod("./ffmpeg", 0o755)
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        logger.info("✅ نصب FFmpeg تکمیل شد.")
    except Exception as e:
        logger.error(f"❌ خطا در نصب FFmpeg: {e}")

# اجرای نصب به صورت همگام (بلاک کننده) تا قبل از اجرای ربات تمام شود
install_ffmpeg()

# ==========================================
# 🚀 تعریف کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

# 1. ربات مدیریت (Telethon)
bot = TelegramClient('bot_session', API_ID, API_HASH)

# 2. یوزربات (Telethon)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# 3. موزیک پلیر (PyTgCalls)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def start_player_engine():
    """روشن کردن موتور پخش فقط در صورت نیاز"""
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("✅ موتور پخش استارت شد.")
    except Exception as e:
        logger.error(f"Player Engine Error: {e}")

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🕵️‍♂️ لاگر تمام پیام‌ها (برای عیب‌یابی)
# ==========================================
@bot.on(events.NewMessage)
async def log_all_messages(event):
    # این تابع فقط لاگ می‌کند تا ببینیم ربات پیام می‌گیرد یا نه
    # اما جلوی بقیه هندلرها را نمی‌گیرد (چون event.stop_propagation صدا زده نشده)
    sender = await event.get_sender()
    sender_id = sender.id if sender else "Unknown"
    logger.info(f"📩 پیام جدید از: {sender_id} | متن: {event.raw_text}")

# ==========================================
# 🤖 هندلرهای ربات (پنل لاگین)
# ==========================================

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender_id = event.sender_id
    
    # اینجا چک می‌کنیم اگر ادمین نبود، بهش بگیم کیه
    if sender_id != ADMIN_ID:
        return await event.reply(f"⛔️ **دسترسی محدود**\n\n🆔 آیدی شما: `{sender_id}`\n⚙️ آیدی ادمین تنظیم شده: `{ADMIN_ID}`\n\nلطفاً آیدی خود را در کد `main.py` اصلاح کنید.")

    # بررسی وضعیت یوزربات
    status = "🔴 قطع"
    try:
        if user_client.is_connected() and await user_client.is_user_authorized():
            status = "🟢 آنلاین"
    except: pass
    
    await event.reply(
        f"👋 **سلام قربان! ربات آماده است.**\n\n"
        f"وضعیت یوزربات: {status}\n\n"
        "**۱. ورود به حساب:**\n"
        "`/phone +989xxxxxxxxx`\n\n"
        "**۲. بعد از دریافت کد:**\n"
        "`/code 12345`\n\n"
        "**۳. اگر رمز دوم دارید:**\n"
        "`/password yourpassword`"
    )

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        ph = event.pattern_match.group(1).strip()
        msg = await event.reply("⏳ در حال اتصال به سرور تلگرام...")
        
        if not user_client.is_connected():
            await user_client.connect()
            
        send_code = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = send_code.phone_code_hash
        
        await msg.edit(f"✅ کد تایید به `{ph}` ارسال شد.\n\nلطفاً کد را به صورت زیر بفرستید:\n`/code 12345`")
    except FloodWaitError as e:
        await msg.edit(f"❌ **محدودیت تلگرام:** لطفا {e.seconds} ثانیه صبر کنید.")
    except Exception as e:
        await msg.edit(f"❌ خطا: {str(e)}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        
        await event.reply("✅ **لاگین با موفقیت انجام شد!**\n🚀 در حال راه‌اندازی موتور پخش...")
        await start_player_engine()
        await event.reply("🎧 **موزیک پلیر فعال شد.**\nحالا می‌توانید در گروه‌ها از `/ply` و `/live` استفاده کنید.")
        
    except SessionPasswordNeededError:
        await event.reply("⚠️ **اکانت شما رمز دوم دارد.**\nلطفاً رمز را بفرستید:\n`/password رمزعبور`")
    except Exception as e:
        await event.reply(f"❌ خطا در ورود: {str(e)}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        pwd = event.pattern_match.group(1).strip()
        await user_client.sign_in(password=pwd)
        
        await event.reply("✅ **ورود کامل شد!**\n🚀 استارت موتور پخش...")
        await start_player_engine()
        
    except Exception as e:
        await event.reply(f"❌ خطا: {str(e)}")

# ==========================================
# 🎵 هندلرهای یوزربات (دستورات پخش)
# ==========================================

@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_cmd(event):
    # اطمینان از روشن بودن موتور
    await start_player_engine()
    
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ **روی یک آهنگ یا فیلم ریپلای کن!**")

    msg = await event.reply("📥 **در حال دانلود فایل...**")
    chat_id = event.chat_id

    try:
        await cleanup(chat_id)
        # دانلود
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path

        await msg.edit(
            "▶️ **پخش شروع شد!**",
            buttons=[[Button.inline("❌ توقف پخش", data=b'stop_cb')]]
        )
        
        await call_py.play(chat_id, AudioVideoPiped(path))
        
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_cmd(event):
    await start_player_engine()
    msg = await event.reply("📡 **در حال اتصال به شبکه خبر...**")
    
    try:
        await cleanup(event.chat_id)
        await call_py.play(event.chat_id, AudioVideoPiped(LIVE_URL))
        
        await msg.edit(
            "🔴 **پخش زنده شروع شد!**",
            buttons=[[Button.inline("❌ قطع ارتباط", data=b'stop_cb')]]
        )
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_msg_cmd(event):
    try:
        await call_py.leave_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ پخش متوقف شد.")
    except: pass

# ==========================================
# 🛑 هندلر دکمه شیشه‌ای (روی ربات اصلی)
# ==========================================
@bot.on(events.CallbackQuery(data=b'stop_cb'))
async def callback_handler(event):
    if event.sender_id != ADMIN_ID:
        return await event.answer("⛔️ شما ادمین نیستید!", alert=True)
    
    try:
        chat_id = event.chat_id
        # دستور توقف را به انجین می‌فرستیم
        await call_py.leave_call(chat_id)
        await cleanup(chat_id)
        await event.edit("⏹ **پخش با موفقیت متوقف شد.**")
    except Exception as e:
        await event.answer("مشکلی پیش آمد یا پخش قبلاً قطع شده.", alert=True)

# ==========================================
# 🌐 اجرا (Main Loop)
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running OK")

async def main():
    # 1. اجرای وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server Started")

    # 2. استارت ربات (اولویت اصلی)
    logger.info("🤖 Starting Bot Client...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started! Waiting for /start command...")

    # 3. بررسی یوزربات (بدون توقف برنامه)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot detected! Starting Player Engine...")
            await start_player_engine()
        else:
            logger.info("⚠️ Userbot not logged in. Please use /phone command.")
    except Exception as e:
        logger.error(f"Userbot check error: {e}")

    # 4. زنده نگه داشتن کل پروسه
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())