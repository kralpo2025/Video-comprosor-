import os
import asyncio
import logging
import wget
import tarfile
import shutil
import time
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.errors import SessionPasswordNeeded
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioVideoPiped

# ==========================================
# ⚙️ تنظیمات
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

LIVE_URL = "https://live-hls-video-cf.gn-s1.com/hls/f27197-040428-144028-200928/index.m3u8"
DOWNLOAD_DIR = "downloads"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MusicBot")
PORT = int(os.environ.get("PORT", 8080))

login_data = {}
active_files = {}

# ==========================================
# 🛠 نصب FFmpeg
# ==========================================
def install_ffmpeg():
    # اضافه کردن مسیر جاری به PATH
    os.environ["PATH"] += os.pathsep + os.getcwd()
    
    if os.path.exists("ffmpeg"):
        logger.info("✅ FFmpeg موجود است.")
        return

    logger.info("⏳ در حال دانلود FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        print()
        
        with tarfile.open("ffmpeg.tar.xz") as f:
            f.extractall(".")
        
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                source = os.path.join(root, "ffmpeg")
                shutil.move(source, "./ffmpeg")
                os.chmod("./ffmpeg", 0o755)
                break
        
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        logger.info("✅ نصب تمام شد.")
    except Exception as e:
        logger.error(f"❌ خطا در نصب: {e}")

install_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

bot = Client("BotSession", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("UserSession", api_id=API_ID, api_hash=API_HASH, in_memory=True)
call_py = PyTgCalls(user)

# ==========================================
# 🗑 توابع کمکی
# ==========================================
async def cleanup(chat_id):
    if chat_id in active_files:
        path = active_files[chat_id]
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_files[chat_id]

@call_py.on_stream_end()
async def on_stream_end(client, update):
    chat_id = update.chat_id
    try:
        await client.leave_call(chat_id)
        await cleanup(chat_id)
    except: pass

# ==========================================
# 🎮 دستورات یوزربات
# ==========================================
@user.on_message(filters.command("ply") & filters.user(ADMIN_ID))
async def play_handler(c, m):
    chat_id = m.chat.id
    replied = m.reply_to_message
    if not replied or not (replied.audio or replied.video):
        return await m.reply("❌ ریپلای کن!")

    msg = await m.reply("📥 دانلود...")
    try:
        await cleanup(chat_id)
        path = await replied.download(f"{DOWNLOAD_DIR}/{chat_id}_{int(time.time())}.mp4")
        active_files[chat_id] = path

        await msg.edit("🎧 پخش...")
        await call_py.play(chat_id, AudioVideoPiped(path))
        await msg.edit("✅ پخش شد!")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")
        await cleanup(chat_id)

@user.on_message(filters.command("live") & filters.user(ADMIN_ID))
async def live_handler(c, m):
    chat_id = m.chat.id
    msg = await m.reply("📡 اتصال...")
    try:
        await cleanup(chat_id)
        await call_py.play(chat_id, AudioVideoPiped(LIVE_URL))
        await msg.edit("🔴 لایو!")
    except Exception as e:
        await msg.edit(f"❌ خطا: {e}")

@user.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_handler(c, m):
    try:
        await call_py.leave_call(m.chat.id)
        await cleanup(m.chat.id)
        await m.reply("⏹ قطع شد.")
    except: pass

# ==========================================
# 🔐 پنل مدیریت (لاگین)
# ==========================================
@bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_cmd(c, m):
    st = "🟢 متصل" if user.is_connected else "🔴 قطع (نیاز به لاگین)"
    await m.reply(f"وضعیت: {st}\n1. `/phone +98...`\n2. `/code ...`")

@bot.on_message(filters.command("phone") & filters.user(ADMIN_ID))
async def ph_cmd(c, m):
    try:
        p = m.text.split()[1]
        # اتصال اولیه بدون استارت کامل (فقط کانکت)
        if not user.is_connected: await user.connect()
        
        s = await user.send_code(p)
        login_data.update({'p': p, 'h': s.phone_code_hash})
        await m.reply("✅ کد را بفرست: `/code 12345`")
    except Exception as e: await m.reply(f"❌ {e}")

@bot.on_message(filters.command("code") & filters.user(ADMIN_ID))
async def co_cmd(c, m):
    try:
        code = m.text.split()[1]
        await user.sign_in(login_data['p'], login_data['h'], code)
        await m.reply("✅ **لاگین موفق! سرویس پخش استارت شد.**")
        
        # 🔥 نکته مهم: اینجا استارت میزنیم تا کرش نکنه
        if not call_py.active_calls:
            await call_py.start()
            
    except SessionPasswordNeeded:
        await m.reply("⚠️ رمز دوم: `/password ...`")
    except Exception as e: await m.reply(f"❌ {e}")

@bot.on_message(filters.command("password") & filters.user(ADMIN_ID))
async def pa_cmd(c, m):
    try:
        pwd = m.text.split()[1]
        await user.check_password(password=pwd)
        await m.reply("✅ **لاگین موفق! سرویس پخش استارت شد.**")
        
        # 🔥 استارت سرویس پخش بعد از موفقیت
        if not call_py.active_calls:
            await call_py.start()
            
    except Exception as e: await m.reply(f"❌ {e}")

# ==========================================
# 🌐 اجرا
# ==========================================
async def web_handler(r): return web.Response(text="Bot Running")

async def main():
    # 1. وب سرور
    app = web.Application()
    app.router.add_get("/", web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    # 2. استارت ربات مدیریت
    print("🤖 استارت ربات...")
    await bot.start()

    # 3. لاجیک هوشمند استارت یوزربات
    print("👤 بررسی وضعیت یوزربات...")
    try:
        await user.connect()
        if await user.get_me():
            print("✅ یوزربات از قبل لاگین است. استارت سرویس تماس...")
            await call_py.start()
        else:
            print("⚠️ یوزربات لاگین نیست. منتظر دستور /phone در ربات...")
            # اینجا call_py.start() را اجرا نمیکنیم تا کرش نکند
    except Exception as e:
        print(f"وضعیت لاگین: {e}")

    await idle()

if __name__ == "__main__":
    asyncio.run(main())