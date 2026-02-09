import os
import asyncio
import logging
import time
import math
import re
import gc  # Garbage Collector برای خالی کردن رم
import imageio_ffmpeg
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
logger = logging.getLogger("DiskSaverBot")

# ایجاد پوشه‌ها و پاکسازی اولیه
if os.path.exists(DOWNLOAD_PATH):
    import shutil
    shutil.rmtree(DOWNLOAD_PATH)
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(THUMB_PATH, exist_ok=True)

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()

# ==========================================
# کلاینت‌ها و متغیرها
# ==========================================
work_queue = asyncio.Queue()
login_state = {}
pending_jobs = {}  # برای ذخیره موقت ایونت تا زمانی که کاربر کیفیت را انتخاب کند
last_edit_time = {}

bot = TelegramClient(BOT_SESSION, API_ID, API_HASH)

# ✅ تنظیمات اتصال پایدار برای جلوگیری از لاگ‌اوت
user_client = TelegramClient(
    USER_SESSION,
    API_ID,
    API_HASH,
    connection=ConnectionTcpFull,
    device_model="Desktop",  # جا زدن به عنوان دسکتاپ برای پایداری
    app_version="4.10.0",
    system_version="Windows 11",
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
    """ساخت تامنیل برای اینکه ویدیو بدون عکس نباشد"""
    try:
        cmd = [
            FFMPEG_BINARY, '-y',
            '-i', video_path,
            '-ss', '00:00:01',
            '-vframes', '1',
            thumb_path
        ]
        # استفاده از DEVNULL برای جلوگیری از پر شدن بافر
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        if os.path.exists(thumb_path):
            return thumb_path
        return None
    except: return None

async def safe_edit(message_obj, text):
    """ویرایش ایمن پیام با رعایت محدودیت‌های تلگرام"""
    msg_id = message_obj.id
    now = time.time()
    
    # فقط هر 5 ثانیه یکبار اجازه ادیت میدهد
    if now - last_edit_time.get(msg_id, 0) < 5:
        return

    try:
        await message_obj.edit(text)
        last_edit_time[msg_id] = now
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
    except Exception:
        pass

async def update_progress(current, total, message_obj, start_time, action_text):
    if total == 0: return
    
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
        f"⏳ زمان مانده: `{time_formatter(eta)}`"
    )
    
    await safe_edit(message_obj, text)

# ==========================================
# موتور فشرده‌سازی (بهینه شده)
# ==========================================
async def compress_engine(input_path, output_path, duration, percentage, message_obj):
    # تبدیل درصد کاربر به CRF
    # 20% -> CRF 38 (حجم کم)
    # 50% -> CRF 28 (متوسط)
    # 80% -> CRF 23 (کیفیت بالا)
    percentage = max(10, min(100, int(percentage)))
    crf = int(45 - (percentage * 0.25))

    # دستور FFmpeg بهینه شده برای مصرف کم CPU و RAM
    cmd = [
        FFMPEG_BINARY, '-y',
        '-i', input_path,
        '-c:v', 'libx264',
        '-crf', str(crf),
        '-preset', 'superfast', # سرعت بالا = درگیری کمتر رم
        '-c:a', 'aac',
        '-b:a', '96k',
        '-movflags', '+faststart',
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    while True:
        line = await process.stderr.readline()
        if not line: break
        
        line_txt = line.decode('utf-8', errors='ignore')
        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", line_txt)
        
        # بلافاصله متغیر خط را پاک میکنیم تا رم اشغال نشود
        del line
        
        if time_match:
            h, m, s = map(float, time_match.groups())
            done_sec = h*3600 + m*60 + s
            percent_prog = (done_sec / duration) * 100 if duration else 0
            
            filled = math.floor(percent_prog / 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            
            await safe_edit(
                message_obj,
                f"⚙️ **در حال فشرده‌سازی (کیفیت {percentage}%)...**\n{bar} **{round(percent_prog, 1)}%**"
            )

    await process.wait()
    return process.returncode == 0

# ==========================================
# Worker: پردازشگر صف (قلب تپنده ربات)
# ==========================================
async def queue_worker():
    logger.info("👷 Worker Started...")
    while True:
        # دریافت تسک
        task = await work_queue.get()
        event = task['event']
        status_msg = task['status_msg']
        quality_percent = task['quality']
        
        in_file = None
        out_file = None
        thumb_file = None
        
        try:
            # 🧹 مرحله 1: تخلیه رم قبل از شروع
            gc.collect()
            
            msg = event.message
            ts = int(time.time())
            
            ext = ".mp4"
            if msg.file and msg.file.name:
                _, t_ext = os.path.splitext(msg.file.name)
                if t_ext: ext = t_ext
            
            # مسیرهای دیسک
            in_file = os.path.join(DOWNLOAD_PATH, f"in_{ts}{ext}")
            out_file = os.path.join(DOWNLOAD_PATH, f"out_{ts}.mp4")
            thumb_file = os.path.join(THUMB_PATH, f"thumb_{ts}.jpg")

            # 📥 مرحله 2: دانلود روی دیسک (نه رم)
            dl_start = time.time()
            await user_client.download_media(
                msg,
                in_file,
                progress_callback=lambda c, t: asyncio.create_task(
                    update_progress(c, t, status_msg, dl_start, "📥 **در حال دانلود...**")
                )
            )
            gc.collect() # تخلیه رم بعد دانلود

            # ⚙️ مرحله 3: فشرده‌سازی
            duration = msg.file.duration or 1
            success = await compress_engine(in_file, out_file, duration, quality_percent, status_msg)
            gc.collect() # تخلیه رم بعد فشرده‌سازی

            if success:
                await status_msg.edit("🖼 **ساخت تامنیل...**")
                final_thumb = await extract_thumbnail(out_file, thumb_file)
                
                # 📤 مرحله 4: آپلود از دیسک
                up_start = time.time()
                old_sz = os.path.getsize(in_file)
                new_sz = os.path.getsize(out_file)
                red = ((old_sz - new_sz) / old_sz) * 100
                
                cap = (
                    f"✅ **عملیات موفق بود!**\n\n"
                    f"💎 کیفیت انتخابی: {quality_percent}%\n"
                    f"📦 حجم اصلی: `{humanbytes(old_sz)}`\n"
                    f"💾 حجم جدید: `{humanbytes(new_sz)}`\n"
                    f"📉 کاهش حجم: `{round(red, 1)}%`"
                )

                await user_client.send_file(
                    event.chat_id,
                    out_file,
                    caption=cap,
                    thumb=final_thumb,
                    supports_streaming=True, # قابلیت پخش آنلاین
                    reply_to=event.id,
                    progress_callback=lambda c, t: asyncio.create_task(
                        update_progress(c, t, status_msg, up_start, "📤 **در حال ارسال...**")
                    )
                )
                await status_msg.delete()
            else:
                await status_msg.edit("❌ خطا در فشرده‌سازی رخ داد.")

        except Exception as e:
            logger.error(f"Worker Error: {e}")
            try: await status_msg.edit(f"❌ خطا: {str(e)}")
            except: pass
            
        finally:
            # 🗑 مرحله 5: پاکسازی نهایی و حیاتی
            # حذف فایل‌ها از دیسک
            try:
                if in_file and os.path.exists(in_file): os.remove(in_file)
                if out_file and os.path.exists(out_file): os.remove(out_file)
                if thumb_file and os.path.exists(thumb_file): os.remove(thumb_file)
            except: pass
            
            # حذف تایمر ادیت پیام
            if status_msg.id in last_edit_time: del last_edit_time[status_msg.id]
            
            # تخلیه نهایی رم
            del in_file, out_file, thumb_file, msg
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

    # 1. دریافت ویدیو
    if event.message.video or (event.message.document and 'video' in event.message.document.mime_type):
        pending_jobs[chat_id] = event
        await event.reply(
            "🎥 **ویدیو دریافت شد.**\n\n"
            "لطفاً کیفیت خروجی را تعیین کنید:\n"
            "🔢 عددی بین **1 تا 100** بفرستید.\n\n"
            "▫️ **20** = حجم خیلی کم (کیفیت پایین)\n"
            "▫️ **50** = متعادل (پیشنهادی)\n"
            "▫️ **80** = کیفیت بالا (کاهش حجم کم)\n\n"
            "👇 عدد را ارسال کنید:"
        )
        return

    # 2. دریافت درصد کیفیت
    if chat_id in pending_jobs and text.isdigit():
        qual = int(text)
        if not (1 <= qual <= 100):
            await event.reply("⚠️ عدد باید بین 1 تا 100 باشد.")
            return
            
        orig_event = pending_jobs.pop(chat_id)
        q_size = work_queue.qsize()
        
        wait_text = f"✅ **درخواست ثبت شد.**\n📊 کیفیت: {qual}%\n"
        wait_text += f"⏳ نفر **{q_size + 1}** در صف..." if q_size > 0 else "🚀 شروع پردازش..."
        
        msg = await event.reply(wait_text)
        
        # ارسال به صف پردازش
        await work_queue.put({
            'event': orig_event,
            'status_msg': msg,
            'quality': qual
        })
        return
        
    if text.isdigit() and chat_id not in pending_jobs:
        await event.reply("❌ ابتدا یک ویدیو ارسال کنید.")

# ==========================================
# پنل ادمین (لاگین)
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_h(event):
    if event.sender_id != ADMIN_ID: return
    status = "🔴 قطع"
    try:
        if await user_client.is_user_authorized(): status = "🟢 متصل"
    except: pass
    await event.reply(f"👑 **مدیریت یوزربات**\nوضعیت: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`\n3️⃣ `/password ...`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    ph = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await event.reply("✅ کد ارسال شد.")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **اتصال موفقیت آمیز بود!**")
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دو مرحله‌ای دارید: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ لاگین موفق.")
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# اجرای اصلی
# ==========================================
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot Running"))
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
    
    # اجرای Worker در بک‌گراند
    asyncio.create_task(queue_worker())
    
    tasks = [bot.run_until_disconnected()]
    if await user_client.is_user_authorized():
        print("✅ Userbot is Active.")
        tasks.append(user_client.run_until_disconnected())
    
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        print(f"Main Error: {e}")
    finally:
        await user_client.disconnect()
        await bot.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass