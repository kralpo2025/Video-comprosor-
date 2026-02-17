import os
import asyncio
import logging
import json
import wget
import tarfile
import shutil
import time
import psutil
from telethon import TelegramClient, events
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

# لینک ثابت جدید ایران اینترنشنال
IRAN_INTL_URL = "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
AUTH_FILE = "whitelist.json"
PORT = int(os.environ.get("PORT", 8080))

# تنظیمات لاگ (برای دیدن خطاها در کنسول)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("MusicBot")

# متغیرهای وضعیت
login_state = {}
active_calls_data = {}

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# ==========================================
# 🔐 لیست سفید (Whitelist Manager)
# ==========================================
def load_whitelist():
    if not os.path.exists(AUTH_FILE): return {}
    try:
        with open(AUTH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def save_whitelist(data):
    with open(AUTH_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

WHITELIST = load_whitelist()

# ==========================================
# 🛠 نصب FFmpeg (خودکار)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if cwd not in os.environ["PATH"]:
        os.environ["PATH"] = cwd + os.pathsep + os.environ["PATH"]
    
    if shutil.which("ffmpeg"): return

    logger.info("⏳ Installing FFmpeg...")
    try:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
        wget.download(url, "ffmpeg.tar.xz")
        with tarfile.open("ffmpeg.tar.xz") as f: f.extractall(".")
        for root, dirs, files in os.walk("."):
            if "ffmpeg" in files:
                shutil.move(os.path.join(root, "ffmpeg"), os.path.join(cwd, "ffmpeg"))
                os.chmod(os.path.join(cwd, "ffmpeg"), 0o755)
                break
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
    except Exception as e:
        logger.error(f"FFmpeg Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها (Bot & Userbot)
# ==========================================
# ربات (برای لاگین)
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
# یوزربات (برای استریم و مدیریت)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی (Helpers)
# ==========================================

def get_server_stats():
    """دریافت پینگ و وضعیت منابع"""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        # محاسبه پینگ فیک (چون پینگ واقعی نیاز به روت دارد، زمان اجرا را میگیریم)
        t_start = time.time()
        time.sleep(0.01)
        t_end = time.time()
        ping = int((t_end - t_start) * 1000)
        
        return (
            f"📊 **وضعیت سرور:**\n"
            f"🧠 رم: `{mem.percent}%`\n"
            f"💾 دیسک: `{disk.percent}%`\n"
            f"📶 پینگ: `{ping}ms`"
        )
    except: return "خطا در دریافت اطلاعات."

async def cleanup(chat_id):
    """پاکسازی فایل‌های موقت"""
    if chat_id in active_calls_data:
        data = active_calls_data[chat_id]
        path = data.get("path")
        if data.get("type") == "file" and path and os.path.exists(path):
            try: os.remove(path)
            except: pass
        del active_calls_data[chat_id]

async def start_stream_engine(chat_id, source):
    """موتور پخش کننده (بدون دکمه، بدون کرش)"""
    if not call_py.active_calls:
        try: await call_py.start()
        except: pass

    # تنظیمات کیفیت SD (480p) برای جلوگیری از لگ
    # استفاده از AudioQuality.MEDIUM برای صدای شفاف و سبک
    stream = MediaStream(
        source, 
        audio_parameters=AudioQuality.MEDIUM, 
        video_parameters=VideoQuality.SD_480p
    )

    try:
        # استراتژی خروج و ورود (Safe Re-join)
        # این کار باگ "Already Joined" یا گیر کردن روی استریم قبلی را حل میکند
        try:
            await call_py.leave_group_call(chat_id)
            await asyncio.sleep(1)
        except: pass
        
        await call_py.join_group_call(chat_id, stream)
    except Exception as e:
        if "no group call" in str(e).lower():
            raise Exception("⚠️ ویس‌کال خاموش است! لطفا Voice Chat گروه/کانال را روشن کنید.")
        raise e

def is_authorized(event):
    """
    بررسی دسترسی:
    1. پیام از طرف ادمین باشد (ADMIN_ID)
    2. پیام از طرف خود یوزربات باشد (event.out) -> برای دستور دادن در کانال‌ها
    """
    return event.sender_id == ADMIN_ID or event.out

# ==========================================
# 🤖 ربات (Bot API) - فقط لاگین و راهنما در PV
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    
    status = "✅ متصل" if user_client.is_connected() and await user_client.is_user_authorized() else "❌ قطع"
    
    help_text = (
        f"👋 **پنل مدیریت (نسخه فارسی)**\n"
        f"وضعیت یوزربات: {status}\n\n"
        f"🔐 **لاگین:**\n"
        f"`/phone` | `/code` | `/password`\n\n"
        f"📋 **دستورات (در گروه و کانال):**\n"
        f"🔹 پخش فایل: `پخش` یا `/ply` (ریپلای)\n"
        f"🔹 پخش زنده: `لایو` یا `تی وی` (شبکه خبر)\n"
        f"🔹 پخش لینک: `لایو لینک` (مثال: `لایو https://...`)\n"
        f"🔹 توقف: `قطع` یا `بستن`\n"
        f"🔹 وضعیت: `پینگ`\n"
        f"🔹 مدیریت: `/add` (افزودن) | `/del` (حذف)"
    )
    await event.reply(help_text)

# --- هندلرهای لاگین ---
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(event.pattern_match.group(1).strip())
        login_state.update({'phone': event.pattern_match.group(1).strip(), 'hash': r.phone_code_hash})
        await event.reply("✅ کد تلگرام را بفرستید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ **لاگین با موفقیت انجام شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دوم دارید. بفرستید: `/password رمز`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID or not event.is_private: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **ورود تکمیل شد.**")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# ⚡️ پردازشگر مرکزی یوزربات (Universal Handler)
# ==========================================
@user_client.on(events.NewMessage)
async def message_handler(event):
    """
    این تابع مغز متفکر ربات است. تمام پیام‌ها را بررسی می‌کند.
    اگر دستوری پیدا کند، اجرا می‌کند.
    """
    
    # 1. فیلتر کردن پیام‌های خالی
    text = event.raw_text
    if not text: return
    
    # نرمال‌سازی متن (حذف فاصله اضافی، تبدیل به حروف کوچک)
    cmd = text.lower().strip()
    chat_id = str(event.chat_id)

    # 2. بررسی ادمین بودن
    if not is_authorized(event): return

    # ==========================
    # 📝 مدیریت لیست سفید (Whitelist)
    # ==========================
    
    # افزودن گروه/کانال: /add
    if cmd.startswith('/add'):
        try:
            target = cmd.replace('/add', '').strip()
            # اگر جلوی دستور چیزی ننوشته بود، چت جاری را بردار
            if not target: 
                entity = await event.get_chat()
            else: 
                entity = await user_client.get_entity(target)
            
            cid = str(entity.id)
            title = getattr(entity, 'title', 'Chat')
            username = getattr(entity, 'username', 'ندارد')
            
            WHITELIST[cid] = {"title": title, "username": username}
            save_whitelist(WHITELIST)
            
            await event.reply(f"✅ **{title}** مجاز شد.\n🆔 `{cid}`\n🔗 @{username}")
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # حذف گروه/کانال: /del
    if cmd.startswith('/del'):
        try:
            # اینجا فرض میکنیم کاربر میخواد گروه جاری رو حذف کنه
            cid = str(event.chat_id)
            if cid in WHITELIST:
                del WHITELIST[cid]
                save_whitelist(WHITELIST)
                await event.reply("🗑 از لیست مجاز حذف شد.")
            else:
                await event.reply("⚠️ اینجا در لیست نبود.")
        except: pass
        return

    # لیست: /list
    if cmd == '/list':
        if not WHITELIST: return await event.reply("📭 لیست خالی است.")
        msg = "**📋 لیست گروه‌ها/کانال‌های مجاز:**\n\n"
        for i, d in WHITELIST.items():
            msg += f"🔹 {d['title']} (`@{d['username']}`)\n"
        await event.reply(msg)
        return

    # ==========================
    # ⛔️ گارد امنیتی (اگر مجاز نیست، ادامه نده)
    # ==========================
    if chat_id not in WHITELIST: return

    # ==========================
    # 📶 وضعیت سرور: پینگ
    # ==========================
    if cmd in ['پینگ', '/ping', 'ping']:
        await event.reply(get_server_stats())
        return

    # ==========================
    # ▶️ پخش فایل: پخش / ply
    # ==========================
    if cmd in ['پخش', '/ply', 'play']:
        reply = await event.get_reply_message()
        if not reply or not (reply.audio or reply.video):
            return await event.reply("❌ روی یک آهنگ یا فیلم ریپلای کن.")
        
        status = await event.reply("📥 **در حال دانلود...**")
        await cleanup(event.chat_id)
        
        try:
            path = await reply.download_media(file=os.path.join(DOWNLOAD_DIR, f"{chat_id}.mp4"))
            if not path: return await status.edit("❌ دانلود ناموفق.")
            
            active_calls_data[event.chat_id] = {"path": path, "type": "file"}
            
            await status.edit("🚀 **پخش شروع شد.**")
            await start_stream_engine(event.chat_id, path)
            
            # پاک کردن پیام وضعیت بعد از چند ثانیه
            await asyncio.sleep(5)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
            await cleanup(event.chat_id)
        return

    # ==========================
    # 📺 پخش زنده: لایو / تی وی
    # ==========================
    # تشخیص: اگر پیام با "لایو" یا "/live" شروع شود
    if cmd.startswith(('لایو', '/live', 'تی وی', 'tv')):
        parts = text.split(maxsplit=1) # جدا کردن لینک از دستور
        
        # اگر لینک داده شده بود
        if len(parts) > 1:
            link = parts[1].strip()
            title = "لینک سفارشی"
            # حذف پیام کاربر (برای تمیزی کانال/گروه)
            try: await event.delete()
            except: pass
        else:
            # اگر لینک نبود، پخش ایران اینترنشنال
            link = IRAN_INTL_URL
            title = "ایران اینترنشنال"

        status = await event.reply(f"📡 **اتصال به {title}...**")
        await cleanup(event.chat_id)
        
        try:
            final_url = link
            # اگر لینک مستقیم نبود (مثل یوتیوب)، تبدیلش کن
            if link != IRAN_INTL_URL:
                ydl_opts = {'format': 'best[height<=360]/best', 'noplaylist': True, 'quiet': True, 'geo_bypass': True}
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(link, download=False)
                        final_url = info.get('url')
                except:
                    return await status.edit("❌ لینک نامعتبر است.")

            active_calls_data[event.chat_id] = {"path": final_url, "type": "live"}
            
            await status.edit(f"🔴 **پخش زنده فعال شد:**\n{title}")
            await start_stream_engine(event.chat_id, final_url)
            
            # پاک کردن پیام وضعیت بعد از چند ثانیه
            await asyncio.sleep(5)
            await status.delete()
            
        except Exception as e:
            await event.reply(f"❌ خطا: {e}")
        return

    # ==========================
    # ⏹ قطع پخش: قطع / stop
    # ==========================
    if cmd in ['قطع', '/stop', 'بستن', 'stop']:
        try:
            await call_py.leave_group_call(event.chat_id)
            await cleanup(event.chat_id)
            await event.reply("⏹ **پخش متوقف شد.**")
        except: pass
        return

# ==========================================
# 🛡 خروج خودکار (Auto Leave)
# ==========================================
@user_client.on(events.ChatAction)
async def auto_leave(event):
    # اگر ربات به گروهی اضافه شد
    if event.user_added and event.user_id == (await user_client.get_me()).id:
        chat_id = str(event.chat_id)
        # اگر مجاز نبود و ادمین هم نبود
        if chat_id not in WHITELIST and event.chat_id != ADMIN_ID:
            try:
                await event.reply("⛔️ **اجازه فعالیت ندارم.**\n(ادمین باید با دستور `/add` مجوز دهد)")
                await user_client.kick_participant(event.chat_id, 'me')
            except: pass

# ==========================================
# 🌐 سرور (برای روشن ماندن)
# ==========================================
async def main():
    # اجرای وب سرور ساده
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    # اجرای ربات‌ها
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized(): 
            logger.info("Userbot Logged In Successfully")
            await call_py.start()
    except: pass
    
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())