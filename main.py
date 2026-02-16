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
from pytgcalls.exceptions import GroupCallNotFound, NoActiveGroupCall

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")

login_state = {}
active_files = {}

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def install_ffmpeg():
    os.environ["PATH"] += os.pathsep + os.getcwd()
    if os.path.exists("ffmpeg"): return
    logger.info("⏳ Downloading FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), "./ffmpeg")
                os.chmod("./ffmpeg", 0o755)
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        logger.info("✅ FFmpeg Installed.")
    except: pass

install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

bot = TelegramClient('bot_session_mem', API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# ♻️ توابع هوشمند پخش (اصلاح شده)
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

async def start_player():
    """روشن کردن موتور پخش در صورت خاموشی"""
    try:
        if not call_py.active_calls:
            await call_py.start()
    except: pass

async def smart_stream(chat_id, stream):
    """
    تابع هوشمند:
    1. اول سعی میکنه جوین بده.
    2. اگه ارور داد 'قبلا هستی'، استریم رو چنج میکنه.
    3. اگه ارور داد 'کال نیست'، به کاربر میگه.
    """
    try:
        # تلاش اول: جوین شدن
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        err = str(e).lower()
        # اگر قبلا جوین بودیم، فقط موزیک رو عوض کن
        if "already" in err or "in a group call" in err:
            try:
                await call_py.change_stream_call(chat_id, stream)
            except Exception as e2:
                raise Exception(f"خطا در تغییر موزیک: {e2}")
        
        # اگر ویس کال اصلا وجود نداشت
        elif "no group call" in err or "not found" in err:
            raise Exception("⚠️ **ویس‌کال گروه خاموش است!**\nلطفاً ابتدا ویس‌کال را توسط ادمین‌ها روشن کنید.")
        
        # سایر ارورها (مثل تایم‌اوت)
        else:
            # تلاش نهایی: خروج اجباری و ورود مجدد
            try:
                await call_py.leave_group_call(chat_id)
                await asyncio.sleep(1)
                await call_py.join_group_call(chat_id, stream)
            except:
                raise e # اگر باز هم نشد، ارور اصلی رو نشون بده

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
async def start_h(event):
    if event.sender_id != ADMIN_ID: return await event.reply("⛔️")
    
    st = "🟢 آنلاین" if user_client.is_connected() and await user_client.is_user_authorized() else "🔴 قطع"
    await event.reply(f"👋 **پنل مدیریت**\nوضعیت یوزربات: {st}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`")

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
        await msg.edit("✅ کد رو بفرست: `/code 12345`")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین شد!**")
        await start_player()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود موفق!**")
        await start_player()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 🎵 یوزربات
# ==========================================
@user_client.on(events.NewMessage(pattern='/ply', outgoing=True))
@user_client.on(events.NewMessage(pattern='/ply', incoming=True, from_users=ADMIN_ID))
async def ply_h(event):
    await start_player()
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video): return await event.reply("❌ ریپلای کن.")
    
    msg = await event.reply("📥 دانلود...")
    chat_id = event.chat_id
    try:
        await cleanup(chat_id)
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        active_files[chat_id] = path
        
        await msg.edit("🎧 در حال اتصال به کال...", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
        
        # استفاده از تابع هوشمند
        await smart_stream(chat_id, AudioVideoPiped(path))
        
        await msg.edit("✅ **پخش شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user_client.on(events.NewMessage(pattern='/live', outgoing=True))
@user_client.on(events.NewMessage(pattern='/live', incoming=True, from_users=ADMIN_ID))
async def live_h(event):
    await start_player()
    msg = await event.reply("📡 اتصال به لایو...")
    try:
        await cleanup(event.chat_id)
        await smart_stream(event.chat_id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 **لایو شروع شد!**", buttons=[[Button.inline("❌ توقف", data=b'stop')]])
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern='/stop', outgoing=True))
@user_client.on(events.NewMessage(pattern='/stop', incoming=True, from_users=ADMIN_ID))
async def stop_cmd(event):
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.reply("⏹ قطع شد.")
    except: pass

@bot.on(events.CallbackQuery(data=b'stop'))
async def stop_cb(event):
    if event.sender_id != ADMIN_ID: return await event.answer("⛔️", alert=True)
    try:
        await call_py.leave_group_call(event.chat_id)
        await cleanup(event.chat_id)
        await event.edit("⏹ متوقف شد.")
    except Exception as e: await event.answer(f"Error: {e}", alert=True)

# ==========================================
# 🌐 اجرا
# ==========================================
async def web_handler(r): return web.Response(text="Bot OK")

async def main():
    # وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("🌍 Web Server")

    # ربات
    logger.info("🤖 Bot Starting...")
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("✅ Bot Started!")

    # یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            logger.info("👤 Userbot Logged In")
            await start_player()
    except: pass

    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())