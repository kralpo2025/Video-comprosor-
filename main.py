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
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.phone import CreateGroupCallRequest
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator

# استفاده از کلاس‌های صحیح و پایدار برای 1.2.9
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

DEFAULT_LIVE_URL = "https://iran.kralp.workers.dev/https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"
AUTH_FILE = "allowed_chats.json"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("StableStreamer")

login_state = {}
current_playing = {} 
admin_states = {} # برای پنل شیشه‌ای ربات

if not os.path.exists("downloads"):
    os.makedirs("downloads")

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
# 🛠 نصب FFmpeg و مدیریت هارد
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

def clean_downloads():
    """پاکسازی خودکار فایل‌های دانلود شده از هارد"""
    try:
        for file in glob.glob("downloads/*"):
            os.remove(file)
    except: pass

# ==========================================
# 🚀 کلاینت‌ها
# ==========================================
bot = TelegramClient(MemorySession(), API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)
call_py = PyTgCalls(user_client)

# ==========================================
# 📊 توابع کمکی (استخراج لینک، دانلود، باز کردن ویسکال)
# ==========================================
async def get_system_info():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent()
    return f"🧠 RAM: {mem.percent}%\n💾 Disk: {disk.percent}%\n🖥 CPU: {cpu}%"

async def ensure_vc(chat_id):
    """استارت خودکار ویسکال در صورت بسته بودن"""
    try:
        entity = await user_client.get_input_entity(chat_id)
        await user_client(CreateGroupCallRequest(
            peer=entity,
            random_id=random.randint(10000, 999999)
        ))
        await asyncio.sleep(2) # صبر برای ایجاد کامل ویسکال
    except: pass # اگر از قبل باز باشه یا دسترسی نباشه ارور میده که مهم نیست

async def download_telethon_media(message, status_msg):
    """دانلود مدیا تلگرام با نمایش درصد پیشرفت"""
    last_edit_time = time.time()
    
    async def progress_callback(current, total):
        nonlocal last_edit_time
        now = time.time()
        if now - last_edit_time > 2.5: # آپدیت هر 2.5 ثانیه برای جلوگیری از فلود
            percent = round((current / total) * 100, 1)
            try:
                await status_msg.edit(f"📥 در حال دانلود روی سرور...\n📊 پیشرفت: `{percent}%`")
                last_edit_time = now
            except: pass

    file_path = await message.download_media(file="downloads/", progress_callback=progress_callback)
    return file_path

async def download_ytdlp_media(url, status_msg, loop):
    """دانلود از یوتیوب، اینستاگرام و لینک مستقیم فیلم با yt-dlp و نمایش درصد"""
    last_edit_time = time.time()

    def my_hook(d):
        nonlocal last_edit_time
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_edit_time > 3:
                percent = d.get('_percent_str', 'N/A')
                speed = d.get('_speed_str', 'N/A')
                try:
                    asyncio.run_coroutine_threadsafe(
                        status_msg.edit(f"📥 در حال دانلود از لینک...\n📊 پیشرفت: `{percent}`\n⚡️ سرعت: `{speed}`"),
                        loop
                    )
                    last_edit_time = now
                except: pass

    ydl_opts = {
        'format': 'best', # بهترین کیفیت اصلی (بدون افت)
        'outtmpl': 'downloads/%(id)s_%(title)s.%(ext)s',
        'progress_hooks': [my_hook],
        'quiet': True,
        'geo_bypass': True
    }

    def run_dl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)

    file_path = await asyncio.to_thread(run_dl)
    return file_path

# ==========================================
# 👮‍♂️ سیستم امنیتی
# ==========================================
async def is_admin(event):
    if event.sender_id == ADMIN_ID: return True
    try:
        participant = await user_client(GetParticipantRequest(event.chat_id, event.sender_id))
        if type(participant.participant) in (ChannelParticipantAdmin, ChannelParticipantCreator): return True
    except: pass
    return False

async def security_check(event):
    if event.chat_id not in ALLOWED_CHATS:
        try:
            await event.reply("💢 مرتیکه! این چت مجاز نیست. ادمینت غلط کرده منو آورده اینجا. سیکتیر!")
            await user_client.delete_dialog(event.chat_id) 
        except: pass
        return False
    if not await is_admin(event):
        await event.reply("⚠️ شرمنده! فقط ادمین‌های این گروه میتونن دستورات ربات رو مدیریت کنن.")
        return False
    return True

# ==========================================
# 🤖 ربات مدیریت (Bot API) و پنل شیشه‌ای
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != ADMIN_ID: return
    
    status_text = "🔴 **آفلاین**"
    if user_client.is_connected() and await user_client.is_user_authorized():
        me = await user_client.get_me()
        status_text = f"🟢 **آنلاین** (`{me.first_name}`)"

    help_text = f"""
🤖 **سیستم مدیریت استریم و رسانه**

وضعیت یوزربات: {status_text}

📋 **دستورات استارت:**
🔸 `/phone [شماره]` | `/code [کد]` | `/password [رمز]`
🔸 `/add [لینک/آیدی]` : مجاز کردن کانال

🛠 **دستورات داخل گروه‌ها:**
🔹 `/live [لینک]` یا `لایو [لینک]` : پخش لینک زنده
🔹 `/play [لینک]` یا `پخش` : پخش مستقیم فایل/فیلم از نت یا ریپلای
🔹 `/stop` یا `قطع` : توقف و خروج
🔹 `ولوم 100` : تنظیم بلندی صدا
🔹 `/clearcache` : پاکسازی هارد سرور

👇 برای کنترل از راه دور از دکمه زیر استفاده کنید:
"""
    buttons = [[Button.inline("🎛 پنل پخش رسانه (کنترل از راه دور)", b"open_panel")]]
    await event.reply(help_text, buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"open_panel"))
async def panel_callback(event):
    if event.sender_id != ADMIN_ID: return
    buttons = []
    # لود کردن اسم کانال‌ها برای ساخت دکمه
    for chat_id in ALLOWED_CHATS:
        if chat_id == ADMIN_ID: continue
        try:
            entity = await user_client.get_entity(chat_id)
            name = getattr(entity, 'title', str(chat_id))
            buttons.append([Button.inline(f"📢 {name}", data=f"playin_{chat_id}".encode())])
        except: pass
    
    if not buttons:
        return await event.answer("⚠️ هیچ کانال یا گروه مجازی یافت نشد! ابتدا با دستور /add اضافه کنید.", alert=True)
    
    await event.edit("📍 **لطفا کانال یا گروهی که می‌خواهید مدیا در آن پخش شود را انتخاب کنید:**", buttons=buttons)

@bot.on(events.CallbackQuery(pattern=b"playin_(.*)"))
async def select_chat_callback(event):
    if event.sender_id != ADMIN_ID: return
    chat_id = int(event.data.decode().split('_')[1])
    
    admin_states[ADMIN_ID] = {'action': 'waiting_for_media', 'target_chat': chat_id}
    await event.edit("✅ **کانال انتخاب شد!**\n\nحالا لطفاً پیام خود را بفرستید. می‌توانید:\n1️⃣ یک لینک فیلم/یوتیوب/اینستاگرام بفرستید.\n2️⃣ یک فایل صوتی/تصویری را همینجا ارسال (یا فوروارد) کنید.\n\nربات به طور خودکار آن را در کانال مورد نظر پخش خواهد کرد.")

# هندل کردن مدیایی که کاربر در ربات می‌فرستد برای پخش از راه دور
@bot.on(events.NewMessage(func=lambda e: e.is_private and e.sender_id == ADMIN_ID))
async def handle_admin_media(event):
    state = admin_states.get(ADMIN_ID)
    if not state or state.get('action') != 'waiting_for_media': return
    
    if event.text and event.text.startswith('/'): return # اگر دستور بود کاری نکن
    
    target_chat = state['target_chat']
    del admin_states[ADMIN_ID] # ریست کردن وضعیت
    
    msg = await event.reply("⏳ در حال پردازش درخواست شما برای پخش در کانال...")
    
    try:
        await ensure_vc(target_chat) # باز کردن ویسکال در صورت بسته بودن
        
        file_path = None
        # اگر لینک سوشال مدیا یا فیلم فرستاد
        if event.text and ("http://" in event.text or "https://" in event.text):
            url = event.text.strip()
            file_path = await download_ytdlp_media(url, msg, asyncio.get_event_loop())
        # اگر فایل مدیا (ویدیو، آهنگ) فرستاد
        elif event.media:
            file_path = await download_telethon_media(event, msg)
            
        if not file_path:
            return await msg.edit("❌ خطا: فرمت پشتیبانی نمی‌شود یا لینکی یافت نشد.")

        await msg.edit("🛠 فایل دانلود شد! در حال پخش در ویسکال کانال...")

        if not call_py.active_calls:
            try: await call_py.start()
            except: pass

        stream = MediaStream(file_path, audio_parameters=AudioQuality.HIGH, video_parameters=VideoQuality.SD_480p)
        try: await call_py.leave_group_call(target_chat)
        except: pass
        await asyncio.sleep(1)
        
        await call_py.join_group_call(target_chat, stream)
        current_playing[target_chat] = "پخش از طریق پنل مدیریت"
        await msg.edit("✅ **با موفقیت در کانال پخش شد!** 🎶\nنکته: فایل پس از پایان با دستور /stop از هارد پاک می‌شود.")

    except Exception as e:
        await msg.edit(f"❌ خطا در پردازش رسانه: {e}")

# (دستورات لاگین مثل قبل)
@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def ph(event):
    if event.sender_id != ADMIN_ID: return
    phone = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        r = await user_client.send_code_request(phone)
        login_state['phone'] = phone
        login_state['hash'] = r.phone_code_hash
        await event.reply("✅ کد ارسال شد.")
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def co(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(login_state['phone'], event.pattern_match.group(1).strip(), phone_code_hash=login_state['hash'])
        await event.reply("✅ لاگین شد.")
        if not call_py.active_calls: await call_py.start()
    except Exception as e: await event.reply(f"❌ خطا: {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pa(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود با رمز دوم موفق!")
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
            await event.reply(f"✅ چت `{entity.id}` مجاز شد.")
    except Exception as e: await event.reply(f"❌ پیدا نشد: {e}")

# ==========================================
# 👤 هندلرهای یوزربات در گروه‌ها
# ==========================================

@user_client.on(events.NewMessage(pattern=r'(?i)^/add(?:\s+(.+))?'))
async def user_add_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    chat_id = event.chat_id
    if chat_id not in ALLOWED_CHATS:
        ALLOWED_CHATS.append(chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("✅ مجاز شد.")

@user_client.on(events.NewMessage(pattern=r'(?i)^/del(?:\s+(.+))?'))
async def user_del_h(event):
    if event.sender_id != ADMIN_ID and not event.out: return
    if event.chat_id in ALLOWED_CHATS:
        ALLOWED_CHATS.remove(event.chat_id)
        save_allowed_chats(ALLOWED_CHATS)
        await event.reply("🗑 حذف شد.")

# پخش استریم زنده
@user_client.on(events.NewMessage(pattern=r'(?i)^(/live|لایو)(?:\s+(.+))?'))
async def live_h(event):
    if not await security_check(event): return
    url_to_play = event.pattern_match.group(2) or DEFAULT_LIVE_URL
    try: await event.delete() # پاک کردن پیام حاوی دستور/لینک
    except: pass

    status = await user_client.send_message(event.chat_id, "📡 در حال اتصال...")
    try:
        await ensure_vc(event.chat_id)
        
        opts = {'format': 'best', 'quiet': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url_to_play, download=False)
            stream_url = info.get('url')
            title = info.get('title', 'Live Stream')

        if not call_py.active_calls:
            try: await call_py.start()
            except: pass

        stream = MediaStream(stream_url, audio_parameters=AudioQuality.HIGH, video_parameters=VideoQuality.SD_480p)
        try: await call_py.leave_group_call(event.chat_id)
        except: pass
        await asyncio.sleep(1) 
        
        await call_py.join_group_call(event.chat_id, stream)
        current_playing[event.chat_id] = f"🔴 لایو: {title}"
        await status.edit(f"🔴 **پخش زنده فعال شد**\n📺 `{title}`")
    except Exception as e:
        await status.edit(f"❌ خطا: {e}")

# پخش فیلم مستقیم از اینترنت (دانلود روی هارد + پخش) یا ریپلای
@user_client.on(events.NewMessage(pattern=r'(?i)^(/play|پخش)(?:\s+(.+))?'))
async def play_h(event):
    if not await security_check(event): return
    
    url_arg = event.pattern_match.group(2)
    reply = await event.get_reply_message()
    
    if not url_arg and not (reply and (reply.audio or reply.video or getattr(reply, 'document', None))):
        return await event.reply("⚠️ لطفاً یک لینک (فیلم/یوتیوب/اینستا) همراه دستور بفرستید یا روی یک فایل ریپلای کنید.")

    try: await event.delete() # حذف لینک ارسالی تو گروه برای تمیزی
    except: pass

    msg = await user_client.send_message(event.chat_id, "📥 آماده‌سازی و دانلود فایل مستقیم روی هارد (بدون فشرده‌سازی و بدون لگ)...")
    
    try:
        await ensure_vc(event.chat_id) # اطمینان از باز بودن ویسکال
        
        file_path = None
        if url_arg:
            file_path = await download_ytdlp_media(url_arg, msg, asyncio.get_event_loop())
        elif reply:
            file_path = await download_telethon_media(reply, msg)

        if not file_path:
            return await msg.edit("❌ خطا در دانلود فایل.")

        await msg.edit("🛠 دانلود تکمیل! در حال اجرای فایل در ویسکال...")
        
        if not call_py.active_calls:
            try: await call_py.start()
            except: pass

        # پخش مستقیم فایل از روی هارد بدون هیچ گونه کامپرس و تبدیل
        stream = MediaStream(file_path, audio_parameters=AudioQuality.HIGH, video_parameters=VideoQuality.SD_480p)

        try: await call_py.leave_group_call(event.chat_id)
        except: pass
        await asyncio.sleep(1) 
        
        await call_py.join_group_call(event.chat_id, stream)
        current_playing[event.chat_id] = f"🎵 در حال پخش از فایل لوکال"
        await msg.edit(f"✅ **پخش رسانه بصورت کاملا روان آغاز شد!** 🎶\nنکته: فایل پس از پایان پاکسازی می‌شود.")
    except Exception as e:
        await msg.edit(f"❌ خطا در پردازش رسانه: {e}")

# ==========================================
# قابلیت‌های مدیریت ویسکال
# ==========================================
@user_client.on(events.NewMessage(pattern=r'(?i)^(/pause|توقف موقت)'))
async def pause_h(event):
    if not await security_check(event): return
    try:
        await call_py.pause_stream(event.chat_id)
        await event.reply("⏸ پخش موقتاً متوقف شد.")
    except: pass

@user_client.on(events.NewMessage(pattern=r'(?i)^(/resume|ادامه)'))
async def resume_h(event):
    if not await security_check(event): return
    try:
        await call_py.resume_stream(event.chat_id)
        await event.reply("▶️ پخش ادامه یافت.")
    except: pass

@user_client.on(events.NewMessage(pattern=r'(?i)^(/mute|بی صدا)'))
async def mute_h(event):
    if not await security_check(event): return
    try:
        await call_py.mute_stream(event.chat_id)
        await event.reply("🔇 ربات بی‌صدا شد.")
    except: pass

@user_client.on(events.NewMessage(pattern=r'(?i)^(/unmute|صدا دار)'))
async def unmute_h(event):
    if not await security_check(event): return
    try:
        await call_py.unmute_stream(event.chat_id)
        await event.reply("🔊 صدای ربات وصل شد.")
    except: pass

# تنظیم ولوم (با پشتیبانی از کلمه فارسی "ولوم")
@user_client.on(events.NewMessage(pattern=r'(?i)^(/volume|ولوم)\s+(\d+)'))
async def volume_h(event):
    if not await security_check(event): return
    vol = int(event.pattern_match.group(2))
    if vol < 1 or vol > 200:
        return await event.reply("⚠️ عدد بین 1 تا 200 وارد کنید.")
    try:
        await call_py.change_volume_call(event.chat_id, vol)
        await event.reply(f"🎚 بلندی صدا: **{vol}%**")
    except: pass

@user_client.on(events.NewMessage(pattern=r'(?i)^(/clearcache|/پاکسازی)'))
async def clear_cache_h(event):
    if not await security_check(event): return
    clean_downloads()
    await event.reply("✅ هارد سرور به طور کامل پاکسازی شد.")

# دستور Stop به همراه پاکسازی هوشمند هارد
@user_client.on(events.NewMessage(pattern=r'(?i)^(/stop|قطع)'))
async def stop_h(event):
    if not await security_check(event): return
    try:
        await call_py.leave_group_call(event.chat_id)
        if event.chat_id in current_playing:
            del current_playing[event.chat_id]
        
        # پاکسازی خودکار فایل‌ها بعد از اتمام کار
        clean_downloads()
        gc.collect() 
        await event.reply("⏹ پخش قطع شد و فایل‌ها جهت خالی شدن هارد سرور پاک شدند. روز خوبی داشته باشید♡.")
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
    clean_downloads() # پاکسازی اولیه هنگام ری‌استارت
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