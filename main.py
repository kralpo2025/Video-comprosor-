import os
import asyncio
import logging
import wget
import tarfile
import shutil
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped
from pytgcalls.exceptions import GroupCallNotFound

# ==========================================
# ⚙️ تنظیمات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب‌کننده FFmpeg
# ==========================================
def install_ffmpeg():
    os.environ["PATH"] += os.pathsep + os.getcwd()
    if os.path.exists("ffmpeg"):
        return
    logger.info("⏳ Downloading FFmpeg...")
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
        logger.info("✅ FFmpeg Installed.")
    except Exception as e:
        logger.error(f"❌ FFmpeg Error: {e}")

install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

bot = TelegramClient('bot_session_mem', API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع کمکی پخش (اصلاح شده)
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def start_player():
    try:
        if not call_py.active_calls:
            await call_py.start()
            logger.info("✅ Engine Started")
    except Exception as e:
        logger.error(f"Engine Start Error: {e}")

async def stream_audio(chat_id, stream_obj):
    """تابع هوشمند پخش: اگر در کال باشد عوض می‌کند، نباشد جوین می‌دهد"""
    try:
        # تلاش برای تغییر استریم (اگر از قبل در کال باشد)
        await call_py.change_stream_call(chat_id, stream_obj)
    except Exception:
        # اگر در کال نبود یا ارور داد، تلاش برای جوین شدن
        try:
            await call_py.join_group_call(chat_id, stream_obj)
        except Exception as e:
            # اگر باز هم ارور داد (مثلاً هنوز وصل نشده)، یک بار لفت می‌دهد و دوباره جوین می‌شود
            try:
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream_obj)
            except Exception as final_e:
                raise final_e

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_group_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🤖 ربات مدیریت
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender_id = event.sender_id
    if sender_id != ADMIN_ID:
        return await event.reply(f"⛔️ شما ادمین نیستید.\n🆔 `{sender_id}`")
    
    status = "🔴 خاموش"
    try:
        if user_client.is_connected() and await user_client.is_user_authorized():
            status = "🟢 آنلاین"
    except: pass
    
    await event.reply(f"👋 **پنل موزیک**\nوضعیت: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`")

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
        await msg.edit("✅ کد ارسال شد: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        code = event.pattern_match.group(1).strip()
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await start_player()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        pwd = event.pattern_match.group(1).strip()
        await user_client.sign_in(password=pwd)
        await event.reply("✅ **ورود موفق!**")
        await start_player()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 یوزربات (اصلاح شده)
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def play_h(event):
    await start_player()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path
        
        await msg.edit("🎧 در حال اتصال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
        # استفاده از تابع پخش اصلاح شده
        await stream_audio(chat_id, AudioVideoPiped(path))
        
        await msg.edit("▶️ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_player()
    msg = await event.reply("📡 اتصال...")
    try:
        await cleanup(event.chat_id)
        
        # استفاده از تابع پخش اصلاح شده
        await stream_audio(event.chat_id, AudioVideoPiped(LIVE_URL))
        
        await msg.edit("🔴 **لایو شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e: await msg.edit(f"❌ {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_msg_cmd(event):
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ توقف.")
    except: pass

@bot.on(events.CallbackQuery(data=b'stop'))
async def stop_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.edit("⏹ توقف.")
    except Exception as e: await event.answer(f"Error: {e}", alert=True)

# ==========================================
# 🌐 سرور
# ==========================================
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("🌍 Web Server Started")

async def main():
    asyncio.create_task(start_web_server())
    logger.info("🤖 Starting Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started!")

    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_player()
        else:
            logger.info("⚠️ Userbot needs login")
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass