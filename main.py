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
import random
import glob
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.channels import GetParticipantRequest

# استفاده از کلاس‌های صحیح، پایدار و تست شده برای نسخه 1.2.9
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

# لینک پیش‌فرض شبکه ایران اینترنشنال
DEFAULT_LIVE_URL = "https://iran.kralp.workers.dev/https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("StableStreamer")

login_state = {}
current_playing = {} # برای ذخیره وضعیت فعلی پخش

# ==========================================
# 🔐 مدیریت لیست مجاز
# ==========================================
def load_allowed_chats():
    if not os.path.exists(AUTH_FILE): return [ADMIN_ID]
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
            return [int(i) for i in data]
    except: return [ADMIN_ID]

def save_allowed_chats(chat_list):
    with open(AUTH_FILE, 'w') as f:
        json.dump(list(set(chat_list)), f)

ALLOWED_CHATS = load_allowed_chats()

# ==========================================
# 🛠 نصب FFmpeg (کد تضمینی شما)
# ==========================================
def setup_ffmpeg():
    cwd = os.getcwd()
    if shutil.which("ffmpeg"): return
    try:
        if os.path.exists("ffmpeg.tar.xz"): os.remove("ffmpeg.tar.xz")
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
        logger.error(f"FFmpeg Setup Error: {e}")

setup_ffmpeg()

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی (استخراج لینک آسنکرون برای رفع تق‌تق صدا)
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent()
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n🖥 CPU: {cpu}%"

def extract_info_sync(url):
    # تنظیم روی 360p برای جلوگیری از لگ روی سرور رایگان Render
    ydl_opts = {
        'format': 'best[height<=360]/best', 
        'noplaylist': True, 
        'quiet': True,
        'geo_bypass': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

async def get_stream_link(url):
    try:
        info = await asyncio.to_thread(extract_info_sync, url)
        return info.get('url'), info.get('title', 'Live Stream')
    except Exception as e:
        logger.error(f"yt-dlp error: {e}")
        return url, "Live Stream"

# ==========================================
# 👮‍♂️ سیستم امنیتی (بررسی ادمین بودن)
# ==========================================
async def is_admin(event):
    if event.sender_id == ADMIN_ID:
        return True
    try:
        participant = await user_client(GetParticipantRequest(event.chat_id, event.sender_id))
        if hasattr(participant.participant, 'admin_rights') or type(participant.participant).__name__ == 'ChannelParticipantCreator':
            return True
    except: pass
    return False

async def security_check(event):
    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        try:
            await event.reply("💢 مرتیکه! این چت مجاز نیست. ادمینت غلط کرده منو آورده اینجا. سیکتیر!")
            await user_client.delete_dialog(chat_id) 
        except: pass
        return False
    
    if not await is_admin(event):
        await event.reply("⚠️ شرمنده! فقط ادمین‌های این گروه میتونن دستورات پخش و لایو رو مدیریت کنن.")
        return False
        
    return True

# ==========================================
# 🤬 آنتی‌مزاحم (مخصوص بسیجی‌ها و سایبری‌ها)
# ==========================================
@user_client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def anti_annoying(event):
    if event.sender_id == ADMIN_ID: return
    
    insults = [
        "ساندیس‌خور بدبخت، سیکتیر کن بیرون تا نریدم به هیکلت. 🖕",
        "مادرتو گاییدم بسیجی خایه‌مال، گمشو از پیوی من بیرون جنده زاده.",
        "اگه بسیجی هستی که مادرتو سگ بگاد، کونی مگه نگفتم اینجا نیا؟",
        "جیره‌خور نظام آخوندی، سیکتیر کن تا بلاکت نکردم کسکش.",
        "آخوند پرست صیغه‌ای، دفعه آخرت باشه به این اکانت پیام میدی.",
        "خایه‌مالو سگ بگاد، برو ساندیس‌تو بخور کونی.",
        "بسیجی مادرجنده، برو گمشو تو سوراخ موشت تا ننتو نگاییدم."
    ]
    
    try:
        await event.reply(random.choice(insults))
        await asyncio.sleep(5)
        # پاک کردن دوطرفه پیام‌ها برای جلوگیری از اسپم
        await user_client.delete_dialog(event.sender_id, revoke=True)
    except: pass

# ==========================================
# 🤖 ربات مدیریت (Bot API)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    status_text = "🔴 **آفلاین** (یوزربات هنوز لاگین نشده)"
    if user_client.is_connected() and await user_client.is_user_authorized():
        me = await user_client.get_me()
        status_text = f"🟢 **آنلاین**\n👤 اکانت متصل: `{me.first_name}`"

    help_text = f"""
🤖 **سیستم مدیریت پیشرفته استریم**

وضعیت یوزربات: {status_text}

📋 **لیست دستورات ربات لاگین (همینجا):**
🔸 `/phone [شماره]` : ارسال کد ورود به اکانت
🔸 `/code [کد]` : تایید کد ورود
🔸 `/password [رمز]` : وارد کردن رمز دو مرحله‌ای
🔸 `/add [لینک/آیدی]` : مجاز کردن یک گروه برای پخش از راه دور

🛠 **دستورات قابل استفاده در گروه‌ها (توسط ادمین‌ها و شما):**
🔹 `/add` : مجاز کردن گروه فعلی
🔹 `/del` : حذف گروه فعلی از مجازها
🔹 `/live` یا `لایو` : پخش زنده شبکه ایران اینترنشنال
🔹 `/live [لینک]` یا `لایو [لینک]` : پخش استریم یا فیلم از لینک
🔹 `/play` یا `پخش` : **(ریپلای روی آهنگ/ویدیو)** پخش فایل در ویسکال
🔹 `/stop` یا `قطع` : توقف کامل و خروج از ویسکال
🔹 `/pause` یا `توقف موقت` : متوقف کردن موقت پخش
🔹 `/resume` یا `ادامه` : ادامه پخش
🔹 `/mute` یا `بی صدا` : قطع صدای ربات در ویسکال
🔹 `/unmute` یا `صدا دار` : وصل صدای ربات
🔹 `/volume [1-200]` : تنظیم بلندی صدا
🔹 `/status` یا `/وضعیت` : نمایش اطلاعات فایل/لایو در حال پخش
🔹 `/clearcache` یا `/پاکسازی` : حذف فایل‌های دانلودی برای رفع هنگی سرور
🔹 `/ping` : تست سرعت اتصال یوزربات
"""
    await event.reply(help_text)

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    phone = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(phone)
        login_state['phone'] = phone
        login_state['hash'] = r.phone_code_hash
        await event.reply("✅ کد ارسال شد. حالا بزنید: `/code 12345`")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(login_state['phone'], code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **یوزربات با موفقیت لاگین شد!**")
        if not call_py.active_calls: await call_py.start()
    except SessionPasswordNeededError:
        await event.reply("⚠️ رمز دوم دارید! بزنید: `/password رمز` ")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ **رمز دوم تایید شد. ورود موفق!**")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/add (.+)'))
async def bot_add_h(event):
    if event.sender_id != ADMIN_ID: return
    target = event.pattern_match.group(1).strip()
    try:
        entity = await user_client.get_entity(target)
        if entity.id not in ALLOWED_CHATS:
            ALLOWED_CHATS.append(entity.id)
            save_allowed_chats(ALLOWED_CHATS)
            await event.reply(f"✅ چت `{entity.id}` ( {target} ) مجاز شد.")
        else:
            await event.reply("⚠️ این گروه از قبل در لیست مجاز بود.")
    except Exception as e: await event.reply(f"❌ پیدا نشد: {e}")

# ==========================================
# 👤 هندلرهای یوزربات در گروه‌ها
# ==========================================

@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?:\s+(.+))?'))
async def user_add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target = event.pattern_match.group(1)
    chat_id = event.chat_id
    if target:
        try:
            e = await user_client.get_entity(target)
            chat_id = e.id
        except: return await event.reply("❌ گروه یا چت نامعتبر.")
    
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"✅ این گروه (`{chat_id}`) به لیست مجاز اضافه شد.")
    else:
        await event.reply("⚠️ قبلاً مجاز بود.")

@user_client.on(events.NewMessage(pattern=r'(?i)^/del(?:\s+(.+))?'))
async def user_del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    target = event.pattern_match.group(1)
    chat_id = event.chat_id
    if target:
        try:
            e = await user_client.get_entity(target)
            chat_id = e.id
        except:
            try: chat_id = int(target)
            except: pass
    
    if chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply(f"🗑 گروه `{chat_id}` از لیست مجاز حذف شد.")

# پینگ بهینه شده (درخواست واقعی به سرور تلگرام برای گرفتن تاخیر دقیق)
@user_client.on(events.NewMessage(pattern=r'(?i)^/ping'))
async def ping_h(event):
    if not await security_check(event): return
    start = time.time()
    await user_client.get_me() 
    ping = round((time.time() - start) * 1000)
    info = await get_system_info()
    await event.reply(f"🚀 **ربات با سرعت عالی در حال اجراست**\n📶 Ping: `{ping}ms`\n\n{info}")

# لایو (بدون لگ با رزولوشن 360p و پردازش آسنکرون)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    if not await security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    url_to_play = url_arg if url_arg else DEFAULT_LIVE_URL
    
    try: await event.delete()
    except: pass

    status = await user_client.send_message(event.chat_id, "📡 در حال اتصال به استریم و بهینه‌سازی کیفیت... لطفاً صبور باشید☆")

    try:
        stream_url, title = await get_stream_link(url_to_play)
        
        if not call_py.active_calls:
            try: await call_py.start()
            except: pass

        # استفاده از MediaStream برای نسخه 1.2.9
        stream = MediaStream(
            stream_url,
            audio_parameters=AudioQuality.MEDIUM, 
            video_parameters=VideoQuality.SD_360p # تغییر به 360 برای جلوگیری از لگ سرور رایگان
        )

        try: await call_py.leave_group_call(event.chat_id)
        except: pass
        await asyncio.sleep(1)
        
        await call_py.join_group_call(event.chat_id, stream)
        current_playing[event.chat_id] = f"🔴 لایو: {title}"
        
        await status.edit(f"🔴 **پخش زنده فعال شد**\n📺 `{title}`\n⚡️ کیفیت پردازش روی بهینه‌ترین حالت تنظیم شد.")
    except Exception as e:
        await status.edit(f"❌ خطا در اتصال به استریم: {e}")

# قابلیت جدید: پخش موزیک/ویدیو از فایل با ریپلای
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش)$'))
async def play_h(event):
    if not await security_check(event): return
    reply = await event.get_reply_message()
    if not reply or not (reply.audio or reply.video or reply.voice or getattr(reply, 'document', None)):
        return await event.reply("⚠️ لطفاً روی یک آهنگ، ویس یا ویدیو ریپلای کنید و کلمه «پخش» یا «/play» را بفرستید.")

    msg = await event.reply("📥 در حال دانلود و آماده‌سازی فایل روی سرور (برای جلوگیری از تق‌تق صدا)...")
    
    try:
        # دانلود فایل در سرور
        file_path = await reply.download_media()
        file_name = reply.file.name if reply.file and hasattr(reply.file, 'name') else "فایل مدیا"
        
        if not call_py.active_calls:
            try: await call_py.start()
            except: pass

        # اگر ویدیو باشه، هم تصویر داره هم صدا
        if reply.video or str(file_path).endswith(('.mp4', '.mkv', '.avi')):
            stream = MediaStream(file_path, audio_parameters=AudioQuality.MEDIUM, video_parameters=VideoQuality.SD_360p)
        else:
            # اگر فقط صدا باشه
            stream = MediaStream(file_path, audio_parameters=AudioQuality.HIGH)

        try: await call_py.leave_group_call(event.chat_id)
        except: pass
        await asyncio.sleep(1)
        
        await call_py.join_group_call(event.chat_id, stream)
        current_playing[event.chat_id] = f"🎵 در حال پخش: {file_name}"
        await msg.edit(f"✅ **پخش رسانه آغاز شد!** 🎶\nنام فایل: `{file_name}`")
    except Exception as e:
        await msg.edit(f"❌ خطا در پردازش یا پخش رسانه: {e}")

# ==========================================
# قابلیت‌های جدید اضافه شده به درخواست شما
# ==========================================

# 1. وضعیت پخش فعلی
@user_client.on(events.NewMessage(pattern=r'(?i)^(/status|/وضعیت)'))
async def status_h(event):
    if not await security_check(event): return
    now_playing = current_playing.get(event.chat_id, "هیچ چیزی در حال پخش نیست.")
    await event.reply(f"📻 **وضعیت ویسکال گروه:**\n{now_playing}")

# 2. پاکسازی کش (بسیار مهم برای سرورهای رایگان)
@user_client.on(events.NewMessage(pattern=r'(?i)^(/clearcache|/پاکسازی)'))
async def clear_cache_h(event):
    if not await security_check(event): return
    msg = await event.reply("🧹 در حال پاکسازی فایل‌های اضافه از روی سرور...")
    count = 0
    # پاک کردن تمام فایل‌های دانلودی آهنگ و ویدیو
    for ext in ['*.mp3', '*.mp4', '*.ogg', '*.m4a', '*.avi', '*.mkv']:
        for file in glob.glob(ext):
            try:
                os.remove(file)
                count += 1
            except: pass
    await msg.edit(f"✅ پاکسازی انجام شد!\nتعداد `{count}` فایل از حافظه سرور حذف شد تا سرعت ربات بالا بماند.")

# ==========================================
# قابلیت‌های مدیریت ویسکال
# ==========================================
@user_client.on(events.NewMessage(pattern=r'(?i)^(/pause|توقف موقت)'))
async def pause_h(event):
    if not await security_check(event): return
    try:
        await call_py.pause_stream(event.chat_id)
        await event.reply("⏸ پخش موقتاً متوقف شد. (برای ادامه بنویسید /resume)")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/resume|ادامه)'))
async def resume_h(event):
    if not await security_check(event): return
    try:
        await call_py.resume_stream(event.chat_id)
        await event.reply("▶️ پخش ادامه یافت.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/mute|بی صدا)'))
async def mute_h(event):
    if not await security_check(event): return
    try:
        await call_py.mute_stream(event.chat_id)
        await event.reply("🔇 ربات در ویسکال بی‌صدا شد.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/unmute|صدا دار)'))
async def unmute_h(event):
    if not await security_check(event): return
    try:
        await call_py.unmute_stream(event.chat_id)
        await event.reply("🔊 صدای ربات وصل شد.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'(?i)^/volume\s+(\d+)'))
async def volume_h(event):
    if not await security_check(event): return
    vol = int(event.pattern_match.group(1))
    if vol < 1 or vol > 200:
        return await event.reply("⚠️ لطفاً عددی بین 1 تا 200 وارد کنید.")
    try:
        await call_py.change_volume_call(event.chat_id, vol)
        await event.reply(f"🎚 بلندی صدا روی **{vol}%** تنظیم شد.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if not await security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        if event.chat_id in current_playing:
            del current_playing[event.chat_id]
        gc.collect() # خالی کردن رم
        await event.reply("⏹ استریم قطع و ربات از ویسکال خارج شد. روز خوبی داشته باشید♡.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

# ==========================================
# 🌐 اجرا
# ==========================================
async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Stable Streamer Active"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    print("🚀 Starting...")
    # توکن مستقیماً درون کد لود شد
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await user_client.connect()
        if await user_client.is_user_authorized():
            if not call_py.active_calls: await call_py.start()
    except: pass
    
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())