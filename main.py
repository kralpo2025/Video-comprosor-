import os
import asyncio
import logging
import time
import math
import re
import shutil
import gc  # کتابخانه مدیریت حافظه
import imageio_ffmpeg
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.network import ConnectionTcpFull

# ==========================================
# 🔴 تنظیمات (اطلاعات خود را وارد کنید)
# ==========================================
API_ID = 27868969
API_HASH = "bdd2e8fccf95c9d7f3beeeff045f8df4"
BOT_TOKEN = "8430316476:AAGupmShC1KAgs3qXDRHGmzg1D7s6Z8wFXU"
ADMIN_ID = 7419222963

# مسیرها
BOT_SESSION = 'bot_session'
USER_SESSION = 'user_session'
DOWNLOAD_PATH = "downloads/"
THUMB_PATH = "thumbs/"

# تنظیمات لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("RamSaverBot")

# ==========================================
# مدیریت حافظه و فایل‌ها
# ==========================================
def clean_start():
    """پاکسازی کامل پوشه‌ها هنگام استارت برای جلوگیری از پر شدن دیسک"""
    try:
        if os.path.exists(DOWNLOAD_PATH): shutil.rmtree(DOWNLOAD_PATH)
        if os.path.exists(THUMB_PATH): shutil.rmtree(THUMB_PATH)
        os.makedirs(DOWNLOAD_PATH, exist_ok=True)
        os.makedirs(THUMB_PATH, exist_ok=True)
        logger.info("✅ Cache Cleared & Directories Created.")
    except Exception as e:
        logger.error(f"Error cleaning start: {e}")

# اجرای پاکسازی قبل از هر چیز
clean_start()

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()
PORT = int(os.environ.get("PORT", 8080))

# ==========================================
# کلاینت‌ها و متغیرها
# ==========================================
work_queue = asyncio.Queue()
login_state = {}
pending_compression = {}
last_edit_time = {}

bot = TelegramClient(BOT_SESSION, API_ID, API_HASH)

# ✅ اتصال پایدار با تلاش مجدد خودکار
user_client = TelegramClient(
    USER_SESSION,
    API_ID,
    API_HASH,
    connection=ConnectionTcpFull,
    device_model="Desktop", # مدل استاندارد برای پایداری بیشتر
    app_version="4.0",
    lang_code="en",
    system_lang_code="en-US",
    connection_retries=None,
    auto_reconnect=True,
    retry_delay=1
)

# ==========================================
# توابع کمکی
# ==========================================
def humanbytes(size):
    if not size: return "0B"
    dic = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    n = 0
    power = 2**10
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic[n] + 'B'

def time_formatter(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return "%02d:%02d:%02d" % (hours, minutes, seconds)

async def extract_thumbnail(video_path, thumb_path):
    try:
        cmd = [
            FFMPEG_BINARY, '-y',
            '-i', video_path,
            '-ss', '00:00:02',
            '-vframes', '1',
            thumb_path
        ]
        # استفاده از DEVNULL برای جلوگیری از پر شدن بافر رم
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        if os.path.exists(thumb_path):
            return thumb_path
        return None
    except: return None

async def safe_edit(message_obj, text):
    """ویرایش ایمن برای جلوگیری از ارورهای تلگرام"""
    msg_id = message_obj.id
    now = time.time()
    
    # محدودیت ویرایش: هر 5 ثانیه
    if now - last_edit_time.get(msg_id, 0) < 5:
        return

    try:
        await message_obj.edit(text)
        last_edit_time[msg_id] = now
    except Exception:
        pass

async def update_progress(current, total, message_obj, start_time, action_text):
    if total == 0: return
    
    # محاسبات
    percentage = current * 100 / total
    elapsed = time.time() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    eta = (elapsed / percentage) * 100 - elapsed if percentage > 0 else 0
    
    filled = math.floor(percentage / 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    
    text = (
        f"{action_text}\n"
        f"**{bar} {round(percentage, 1)}%**\n\n"
        f"💾 حجم: `{humanbytes(current)}` / `{humanbytes(total)}`\n"
        f"🚀 سرعت: `{humanbytes(speed)}/s`\n"
        f"⏳ مانده: `{time_formatter(eta)}`"
    )
    
    await safe_edit(message_obj, text)

# ==========================================
# موتور فشرده‌سازی (بهینه شده برای رم)
# ==========================================
async def compress_engine(input_path, output_path, duration, percentage, message_obj):
    percentage = max(10, min(100, int(percentage)))
    crf = int(48 - (percentage * 0.3))

    scale_cmd = ['-vf', 'scale=iw*0.7:-2'] if percentage < 30 else []
    
    cmd = [
        FFMPEG_BINARY, '-y',
        '-i', input_path,
        '-c:v', 'libx264',
        '-crf', str(crf),
        '-preset', 'ultrafast', # سریعترین حالت برای درگیر نشدن رم
        '-c:a', 'aac',
        '-b:a', '64k',
        '-movflags', '+faststart',
        *scale_cmd,
        output_path
    ]
    
    # اجرای پراسس
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    # خواندن لاگ‌ها برای درصد
    while True:
        line = await process.stderr.readline()
        if not line: break
        
        # خواندن خط و سپس حذف فوری از رم
        line_txt = line.decode('utf-8', errors='ignore')
        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", line_txt)
        del line # حذف از حافظه
        
        if time_match:
            h, m, s = map(float, time_match.groups())
            done_sec = h*3600 + m*60 + s
            percent_prog = (done_sec / duration) * 100 if duration else 0
            
            filled = math.floor(percent_prog / 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            
            await safe_edit(
                message_obj,
                f"⚙️ **در حال فشرده‌سازی...**\n{bar} **{round(percent_prog, 1)}%**"
            )

    await process.wait()
    return process.returncode == 0

# ==========================================
# Worker: پردازشگر صف
# ==========================================
async def queue_worker():
    logger.info("👷 Worker Started...")
    while True:
        task = await work_queue.get()
        event = task['event']
        status_msg = task['status_msg']
        quality_percent = task['quality']
        
        in_file = None
        out_file = None
        thumb_file = None
        
        try:
            # پاکسازی رم قبل از شروع تسک جدید
            gc.collect()
            
            msg = event.message
            ts = int(time.time())
            
            ext = ".mp4"
            if msg.file and msg.file.name:
                _, t_ext = os.path.splitext(msg.file.name)
                if t_ext: ext = t_ext
            
            in_file = os.path.join(DOWNLOAD_PATH, f"in_{ts}{ext}")
            out_file = os.path.join(DOWNLOAD_PATH, f"out_{ts}.mp4")
            thumb_file = os.path.join(THUMB_PATH, f"thumb_{ts}.jpg")

            # 1. دانلود
            dl_start = time.time()
            await user_client.download_media(
                msg,
                in_file,
                progress_callback=lambda c, t: asyncio.create_task(
                    update_progress(c, t, status_msg, dl_start, "📥 **دانلود...**")
                )
            )
            gc.collect() # خالی کردن رم بعد دانلود

            # 2. فشرده‌سازی
            duration = msg.file.duration or 1
            success = await compress_engine(in_file, out_file, duration, quality_percent, status_msg)
            gc.collect() # خالی کردن رم بعد فشرده‌سازی

            if success:
                await status_msg.edit("🖼 **ساخت تامنیل...**")
                final_thumb = await extract_thumbnail(out_file, thumb_file)
                
                # 3. آپلود
                up_start = time.time()
                old_sz = os.path.getsize(in_file)
                new_sz = os.path.getsize(out_file)
                red = ((old_sz - new_sz) / old_sz) * 100
                
                cap = (
                    f"✅ **پایان عملیات!**\n\n"
                    f"📦 قبل: `{humanbytes(old_sz)}`\n"
                    f"💾 بعد: `{humanbytes(new_sz)}`\n"
                    f"📉 کاهش: `{round(red, 1)}%`"
                )

                await user_client.send_file(
                    event.chat_id,
                    out_file,
                    caption=cap,
                    thumb=final_thumb,
                    supports_streaming=True,
                    reply_to=event.id,
                    progress_callback=lambda c, t: asyncio.create_task(
                        update_progress(c, t, status_msg, up_start, "📤 **آپلود...**")
                    )
                )
                await status_msg.delete()
            else:
                await status_msg.edit("❌ خطا در فشرده‌سازی.")

        except Exception as e:
            logger.error(f"Worker Error: {e}")
            try: await status_msg.edit(f"❌ خطا: {e}")
            except: pass
            
        finally:
            # پاکسازی نهایی (بسیار مهم)
            # حذف فایل‌ها از دیسک
            try:
                if in_file and os.path.exists(in_file): os.remove(in_file)
                if out_file and os.path.exists(out_file): os.remove(out_file)
                if thumb_file and os.path.exists(thumb_file): os.remove(thumb_file)
            except: pass
            
            # حذف از دیکشنری‌های کمکی
            if status_msg.id in last_edit_time: del last_edit_time[status_msg.id]
            
            # خالی کردن نهایی رم
            in_file = None
            out_file = None
            msg = None
            task = None
            gc.collect() 
            
            work_queue.task_done()

# ==========================================
# هندلرهای یوزربات
# ==========================================
@user_client.on(events.NewMessage(incoming=True))
async def on_message(event):
    if not event.is_private: return

    chat_id = event.chat_id
    text = event.raw_text

    # دریافت ویدیو
    if event.message.video or (event.message.document and 'video' in event.message.document.mime_type):
        pending_compression[chat_id] = event
        await event.reply(
            "🎥 **ویدیو دریافت شد.**\n"
            "کیفیت را تعیین کنید:\n"
            "20 = حجم کم | 50 = متوسط | 80 = کیفیت بالا"
        )
        # آزاد کردن حافظه ایونت
        return

    # دریافت عدد
    if chat_id in pending_compression and text.isdigit():
        qual = int(text)
        if not (1 <= qual <= 100):
            await event.reply("⚠️ عدد باید بین 1 تا 100 باشد.")
            return
            
        orig_event = pending_compression.pop(chat_id)
        q_size = work_queue.qsize()
        
        msg = await event.reply(f"✅ ثبت شد. (نفر {q_size+1} در صف)")
        await work_queue.put({
            'event': orig_event,
            'status_msg': msg,
            'quality': qual
        })

# ==========================================
# پنل ادمین (لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_h(event):
    if event.sender_id != ADMIN_ID: return
    stat = "🟢 متصل" if await user_client.is_user_authorized() else "🔴 قطع"
    await event.reply(f"وضعیت: {stat}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`\n3️⃣ `/password ...`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    ph = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await event.reply("✅ کد را بفرست.")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **وصل شد!**")
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دارید: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ لاگین موفق.")
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# Main Execution
# ==========================================
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def main():
    await web_server()
    print("Bot Starting...")
    await bot.start(bot_token=BOT_TOKEN)
    
    print("Userbot Starting...")
    await user_client.connect()
    
    # اجرای ورکر در بک‌گراند
    asyncio.create_task(queue_worker())
    
    tasks = [bot.run_until_disconnected()]
    if await user_client.is_user_authorized():
        tasks.append(user_client.run_until_disconnected())
    
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        print(f"Main Loop Error: {e}")
    finally:
        # بستن تمیز برنامه
        await user_client.disconnect()
        await bot.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass