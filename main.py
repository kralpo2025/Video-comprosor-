import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
import time
import psutil
import gc
from aiohttp import web
from telethon import TelegramClient, events, functions, types
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, ChannelPrivateError
from telethon.tl.types import Channel, Chat, User

# کتابخانه‌های نسخه 1.2.9 (Pytgcalls Legacy)
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

import yt_dlp

# ==========================================
# ⚙️ تنظیمات (Config)
# ==========================================
# مقادیر پیش‌فرض یا دریافت از Environment Variables
API_ID = int(os.environ.get("API_ID", 27868969))
API_HASH = os.environ.get("API_HASH", "bdd2e8fccf95c9d7f3beeeff045f8df4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8149847784:AAEvF5GSrzyxyO00lw866qusfRjc4HakwfA")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 7419222963))

DEFAULT_LIVE_URL = "http://stream.livetv.stream/live.m3u8" # لینک تست
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("UltraStreamer")

login_state = {}
active_calls_data = {}

# ==========================================
# 🧹 مدیریت حافظه و فایل
# ==========================================
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

async def force_cleanup(chat_id):
    """پاکسازی تهاجمی برای خالی نگه داشتن رم"""
    try:
        if chat_id in active_calls_data:
            data = active_calls_data[chat_id]
            path = data.get("path")
            
            # حذف فایل فیزیکی اگر وجود دارد و از نوع فایل است
            if data.get("type") == "file" and path and os.path.exists(path):
                try:
                    os.remove(path)
                except: pass
            
            del active_calls_data[chat_id]
        
        # درخواست آزادسازی رم از پایتون
        gc.collect()
    except: pass

# ==========================================
# 🔐 لیست مجاز (Database)
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            if ADMIN_ID not in data: data.append(ADMIN_ID)
            return data
    except: return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(chat_list, f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg (خودکار)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Downloading FFmpeg for Render...")
    try:
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        # نسخه استاتیک لینوکس
        wget.download("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz", "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
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
# 📊 توابع کمکی سیستم
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent(interval=0.1)
    
    status_msg = (
        f"🧠 **RAM:** `{mem.percent}%` (Used: {mem.used // 1024**2}MB)\n"
        f"💾 **Disk:** `{disk.percent}%`\n"
        f"⚙️ **CPU:** `{cpu}%`"
    )
    return status_msg

async def get_stream_link(url):
    # تنظیمات حرفه‌ای yt-dlp برای دریافت بهترین کیفیت مناسب استریم بدون لگ
    ydl_opts = {
        'format': 'best[height<=480]',  # 480p تعادل عالی بین کیفیت و پرفورمنس
        'noplaylist': True,
        'quiet': True,
        'geo_bypass': True,
        'hls_prefer_native': True, # برای لایو مهم است
        'concurrent_fragment_downloads': 5
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"YTDL Error: {e}")
        return None, None

async def start_stream_v1(chat_id, source):
    """
    موتور پخش استریم نسخه 1.2.9
    """
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت:
    # VideoQuality.SD_480p بهترین گزینه برای Render است.
    # HD_720p ممکن است باعث قطعی صدا شود.
    stream = MediaStream(
        source,
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p,
        # فلگ‌های اضافه برای جلوگیری از کرش ffmpeg در لایو
        ffmpeg_parameters="-preset ultrafast -tune zerolatency" 
    )

    try:
        # اگر تماسی هست، اول خارج شو
        try: await call_py.leave_group_call(chat_id)
        except: pass
        await asyncio.sleep(1.5) # مکث کوتاه برای تلگرام
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ **ویس‌کال خاموش است!** لطفاً ویس‌چت گروه/کانال را روشن کنید.")
        raise e

# ==========================================
# 👮‍♂️ سیستم دسترسی (Logic)
# ==========================================
async def check_permission(event):
    """
    منطق دسترسی:
    1. ادمین اصلی همیشه دسترسی دارد.
    2. پیام‌های خود ربات (Out) مجاز است.
    3. چت باید در لیست مجاز (Allowed) باشد.
    4. اگر کانال است: مجاز است (چون فقط ادمین پست میزارد).
    5. اگر گروه است: فرستنده باید ادمین گروه باشد.
    """
    # 1. مالک اصلی
    if event.sender_id == ADMIN_ID: return True
    
    # 2. خود یوزربات
    if event.out: return True

    # 3. چک لیست سفید
    # نکته: در کانال‌ها event.chat_id همان آیدی کانال است
    chat_id = event.chat_id
    # هندل کردن آیدی‌های -100 (استاندارد تلگرام)
    simple_id = int(str(chat_id).replace("-100", ""))
    
    is_allowed = (chat_id in ALLOWED_CHATS) or (simple_id in ALLOWED_CHATS)
    if not is_allowed: return False

    # 4. منطق کانال (Channel)
    if event.is_channel and not event.is_group:
        # در کانال فقط کسانی که دسترسی پست دارند می‌توانند پیام بفرستند
        # پس اگر پیام آمد یعنی فرستنده ادمین است.
        return True

    # 5. منطق گروه (Group)
    if event.is_group:
        try:
            perm = await user_client.get_permissions(event.chat_id, event.sender_id)
            if perm.is_admin or perm.is_creator:
                return True
        except: 
            pass # شاید نتوانستیم پرمیشن بگیریم
    
    return False

# ==========================================
# 🤖 ربات لاگین (Bot Interface)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    # وضعیت اتصال یوزربات
    is_connected = user_client.is_connected() and await user_client.is_user_authorized()
    conn_status = "🟢 متصل" if is_connected else "🔴 قطع"
    
    # اطلاعات سیستم
    sys_info = await get_system_info()
    
    # لیست چت‌های مجاز
    chats_str = ""
    for cid in ALLOWED_CHATS:
        if cid == ADMIN_ID: continue
        try:
            # سعی می‌کنیم نام چت را بگیریم (اگر در کش باشد)
            entity = await bot.get_entity(cid)
            title = entity.title if hasattr(entity, 'title') else "User/Chat"
            chats_str += f"🆔 `{cid}` | 🛡 {title}\n"
        except:
            chats_str += f"🆔 `{cid}`\n"
    
    if not chats_str: chats_str = "هیچ گروهی اضافه نشده است."

    text = (
        f"🤖 **کنترل پنل ربات استریمر**\n\n"
        f"📡 **وضعیت یوزربات:** {conn_status}\n"
        f"━━━━━━━━━━━━━━\n"
        f"{sys_info}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📝 **لیست مجاز:**\n{chats_str}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔐 **راهنمای لاگین:**\n"
        f"1️⃣ `/phone +98912...`\n"
        f"2️⃣ `/code 12345`\n"
        f"3️⃣ `/password (اگر رمز دوم دارید)`\n"
    )
    await event.reply(text)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ **کد ارسال شد!**\nارسال با: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین با موفقیت انجام شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ **تایید دو مرحله‌ای فعال است.**\nارسال رمز با: `/password your_pass`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود تکمیل شد.**")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# 👤 هندلرها (Userbot)
# ==========================================

# 1. افزودن هوشمند (لینک، یوزرنیم، ریپلای)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/add|افزودن)(?:\s+(.+))?'))
async def add_h(event):
    # فقط ادمین اصلی یا خود ربات می‌تواند چت اضافه کند
    if event.sender_id != ADMIN_ID and not event.out: return
    
    arg = event.pattern_match.group(2)
    target_id = None
    target_title = "Unknown"

    try:
        if arg:
            # حالت لینک یا یوزرنیم
            if "joinchat" in arg:
                # لینک خصوصی
                try:
                    invite_hash = arg.split("/")[-1]
                    await user_client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
                    await event.reply("✅ به چت خصوصی پیوستم. حالا دوباره کامند بزن تا ادد بشه.")
                    return
                except Exception as e:
                    return await event.reply(f"❌ خطا در جوین: {e}")
            else:
                # لینک عمومی یا یوزرنیم
                entity = await user_client.get_entity(arg)
                target_id = entity.id
                target_title = getattr(entity, 'title', 'Chat')
        else:
            # حالت بدون آرگومان (چت جاری)
            target_id = event.chat_id
            chat = await event.get_chat()
            target_title = getattr(chat, 'title', 'Current Chat')

        if target_id:
            if target_id not in ALLOWED_CHATS:
                ALLOWED_CHATS.append(target_id)
                save_allowed_chats(ALLOWED_CHATS)
                await event.reply(f"✅ **افزوده شد!**\n📌 نام: {target_title}\n🆔 آیدی: `{target_id}`")
            else:
                await event.reply(f"⚠️ **این چت قبلاً در لیست بود!**\n🆔 `{target_id}`")
                
    except Exception as e:
        await event.reply(f"❌ خطا: {str(e)}\nلطفا لینک صحیح وارد کنید.")

# 2. حذف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/del|حذف)'))
async def del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 **از لیست مجاز حذف شد.**")
    else:
        await event.reply("⚠️ این چت در لیست نبود.")

# 3. پینگ و آمار
@user_client.on(events.NewMessage(pattern=r'(?i)^(/ping|پینگ|وضعیت)'))
async def ping_h(event):
    if not await check_permission(event): return
    start = time.time()
    msg = await event.reply("⏳ **در حال محاسبه...**")
    ping = round((time.time() - start) * 1000)
    info = await get_system_info()
    await msg.edit(f"📶 **Ping:** `{ping}ms`\n\n{info}")

# 4. پخش لایو (Live)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    url_arg = event.pattern_match.group(2)
    final_url = DEFAULT_LIVE_URL
    title = "Live TV"
    
    # حذف پیام فرمان برای تمیزی
    try: await event.delete()
    except: pass

    await force_cleanup(chat_id)
    status = await user_client.send_message(chat_id, "🔍 **در حال پردازش لینک لایو...**")

    try:
        if url_arg:
            u, t = await get_stream_link(url_arg)
            if u:
                final_url = u
                title = t or "Stream"
            else:
                final_url = url_arg # Fallback direct link

        active_calls_data[chat_id] = {"path": final_url, "type": "live"}
        
        await status.edit(f"🚀 **در حال اتصال به استریم...**\n📺 `{title}`")
        await start_stream_v1(chat_id, final_url)
        
        await status.edit(f"🔴 **پخش زنده شروع شد!**\n\n📺 **نام:** `{title}`\n⚡️ **کیفیت:** `480p (HQ)`\n✅ **وضعیت:** عالی (بدون لگ)")
        
    except Exception as e:
        logger.error(e)
        await status.edit(f"❌ **خطا در پخش:**\n`{e}`")
        await force_cleanup(chat_id)

# 5. پخش فایل (Play)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش|/ply)'))
async def play_h(event):
    if not await check_permission(event): return
    
    chat_id = event.chat_id
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video):
        return await event.reply("❌ **لطفا روی یک آهنگ یا ویدیو ریپلای کنید.**")

    await force_cleanup(chat_id)
    status = await event.reply("📥 **در حال دانلود فایل روی سرور...**")
    try:
        path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
        if not path: return await status.edit("❌ دانلود ناموفق بود.")
        
        active_calls_data[chat_id] = {"path": path, "type": "file"}
        await status.edit("🔄 **در حال پردازش و تبدیل...**")
        
        await start_stream_v1(chat_id, path)
        await status.edit("▶️ **پخش فایل شروع شد.**")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")
        await force_cleanup(chat_id)

# 6. توقف
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع|بسه)'))
async def stop_h(event):
    if not await check_permission(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        await force_cleanup(event.chat_id)
        await event.reply("⏹ **پخش متوقف شد و حافظه پاکسازی گردید.**")
    except Exception as e:
        await event.reply(f"⚠️ {e}")

@call_py.on_stream_end()
async def on_end(client, update):
    try: await client.leave_group_call(update.chat_id)
    except: pass
    await force_cleanup(update.chat_id)

# ==========================================
# 🌐 سرور Keep-Alive و اجرا
# ==========================================
async def main():
    # سرور وب برای زنده نگه داشتن در Render
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is Running High Performance!"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    logger.info("🚀 Starting Userbot...")
    
    # استارت ربات لاگین
    await bot.start(bot_token=BOT_TOKEN)
    
    # استارت یوزربات
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            await call_py.start()
            me = await user_client.get_me()
            logger.info(f"✅ Userbot Logged in as: {me.first_name}")
    except Exception as e:
        logger.error(f"⚠️ Userbot login failed: {e}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())