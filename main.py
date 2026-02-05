import os
import asyncio
import logging
import time
import math
import re
import gc  # برای مدیریت رم
import imageio_ffmpeg
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.network import ConnectionTcpFull

# ==========================================
# 🔴 تنظیمات
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
logger = logging.getLogger("SafeCompressor")

# ایجاد پوشه‌ها
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(THUMB_PATH, exist_ok=True)

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()
PORT = int(os.environ.get("PORT", 8080))

# ==========================================
# کلاینت‌ها و متغیرها
# ==========================================
work_queue = asyncio.Queue()
login_state = {}
pending_compression = {}
last_message_edit_time = {}  # دیکشنری برای ذخیره زمان آخرین ویرایش هر پیام

bot = TelegramClient(BOT_SESSION, API_ID, API_HASH)

# ✅ تنظیمات ضد بن و جلوگیری از لاگ‌اوت
user_client = TelegramClient(
    USER_SESSION,
    API_ID,
    API_HASH,
    connection=ConnectionTcpFull, # اتصال پایدارتر
    device_model="iPhone 15 Pro",  # جعل مدل گوشی
    system_version="17.4.1",
    app_version="10.9",
    lang_code="en",
    system_lang_code="en-US",
    connection_retries=None,      # تلاش نامحدود
    auto_reconnect=True,
    retry_delay=2
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
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        if os.path.exists(thumb_path):
            return thumb_path
        return None
    except: return None

# ✅ تابع ویرایش امن (Safe Edit)
# این تابع جلوی ویرایش تند تند را می‌گیرد
async def safe_edit_message(message_obj, text):
    msg_id = message_obj.id
    now = time.time()
    
    # اگر زیر 7 ثانیه از آخرین ویرایش گذشته، کنسل کن (مگر اینکه تمام شده باشد)
    last_time = last_message_edit_time.get(msg_id, 0)
    if now - last_time < 7: 
        return

    try:
        await message_obj.edit(text)
        last_message_edit_time[msg_id] = now
    except FloodWaitError as e:
        logger.warning(f"FloodWait hit! Sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds) # صبر اجباری
    except Exception:
        pass

async def update_progress(current, total, message_obj, start_time, action_text):
    if total == 0: return

    percentage = current * 100 / total
    # فقط وقتی درصد تغییر محسوسی کرده یا زمان گذشته آپدیت کن
    
    speed = current / (time.time() - start_time) if (time.time() - start_time) > 0 else 0
    elapsed_time = time.time() - start_time
    estimated_total_time = elapsed_time / (percentage / 100) if percentage > 0 else 0
    time_left = estimated_total_time - elapsed_time
    
    filled = math.floor(percentage / 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    
    text = (
        f"{action_text}\n"
        f"**{bar} {round(percentage, 1)}%**\n\n"
        f"💾 حجم: `{humanbytes(current)}` / `{humanbytes(total)}`\n"
        f"🚀 سرعت: `{humanbytes(speed)}/s`\n"
        f"⏳ مانده: `{time_formatter(time_left)}`"
    )
    
    # فراخوانی ادیت امن
    await safe_edit_message(message_obj, text)

# ==========================================
# موتور فشرده‌سازی
# ==========================================
async def compress_engine(input_path, output_path, duration, percentage, message_obj):
    percentage = max(10, min(100, int(percentage)))
    crf_value = int(48 - (percentage * 0.3))

    scale_cmd = []
    if percentage < 30:
        scale_cmd = ['-vf', 'scale=iw*0.7:-2']
    
    cmd = [
        FFMPEG_BINARY, '-y',
        '-i', input_path,
        '-c:v', 'libx264',
        '-crf', str(crf_value),
        '-preset', 'superfast',
        '-c:a', 'aac',
        '-b:a', '96k',
        '-movflags', '+faststart',
        *scale_cmd,
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
        
        if time_match:
            # محاسبه درصد
            h, m, s = map(float, time_match.groups())
            done_sec = h*3600 + m*60 + s
            percent_prog = (done_sec / duration) * 100 if duration else 0
            
            filled = math.floor(percent_prog / 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            
            text = (
                f"⚙️ **در حال فشرده‌سازی (کیفیت {percentage}%)...**\n"
                f"{bar} **{round(percent_prog, 1)}%**"
            )
            # ادیت امن با رعایت فاصله زمانی
            await safe_edit_message(message_obj, text)

    await process.wait()
    return process.returncode == 0

# ==========================================
# Worker
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
            msg = event.message
            ts = int(time.time())
            
            file_ext = ".mp4"
            if msg.file and msg.file.name:
                _, ext = os.path.splitext(msg.file.name)
                if ext: file_ext = ext
            
            in_file = os.path.join(DOWNLOAD_PATH, f"in_{ts}{file_ext}")
            out_file = os.path.join(DOWNLOAD_PATH, f"out_{ts}.mp4")
            thumb_file = os.path.join(THUMB_PATH, f"thumb_{ts}.jpg")

            # 1. دانلود
            dl_start = time.time()
            await user_client.download_media(
                msg,
                in_file,
                progress_callback=lambda c, t: asyncio.create_task(
                    update_progress(c, t, status_msg, dl_start, "📥 **در حال دانلود...**")
                )
            )

            # 2. فشرده‌سازی
            duration = msg.file.duration or 1
            compress_success = await compress_engine(in_file, out_file, duration, quality_percent, status_msg)
            
            if compress_success:
                await status_msg.edit("🖼 **ساخت تامنیل...**")
                final_thumb = await extract_thumbnail(out_file, thumb_file)
                
                # 3. آپلود
                up_start = time.time()
                old_sz = os.path.getsize(in_file)
                new_sz = os.path.getsize(out_file)
                reduction = ((old_sz - new_sz) / old_sz) * 100
                
                caption_text = (
                    f"✅ **تمام شد!**\n\n"
                    f"💎 کیفیت: %{quality_percent}\n"
                    f"📦 قبل: `{humanbytes(old_sz)}`\n"
                    f"💾 بعد: `{humanbytes(new_sz)}`\n"
                    f"📉 کاهش: `{round(reduction, 1)}%`"
                )

                await user_client.send_file(
                    event.chat_id,
                    out_file,
                    caption=caption_text,
                    thumb=final_thumb,
                    supports_streaming=True,
                    reply_to=event.id,
                    progress_callback=lambda c, t: asyncio.create_task(
                        update_progress(c, t, status_msg, up_start, "📤 **در حال آپلود...**")
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
            # پاکسازی فایل‌ها
            if in_file and os.path.exists(in_file): os.remove(in_file)
            if out_file and os.path.exists(out_file): os.remove(out_file)
            if thumb_file and os.path.exists(thumb_file): os.remove(thumb_file)
            
            # پاک کردن تایمر مسیج
            if status_msg.id in last_message_edit_time:
                del last_message_edit_time[status_msg.id]
                
            gc.collect() # خالی کردن رم
            work_queue.task_done()

# ==========================================
# هندلرها
# ==========================================
@user_client.on(events.NewMessage(incoming=True))
async def message_handler(event):
    if not event.is_private: return

    chat_id = event.chat_id
    text = event.raw_text

    if event.message.video or (event.message.document and 'video' in event.message.document.mime_type):
        pending_compression[chat_id] = event
        await event.reply(
            "🎥 **ویدیو دریافت شد.**\n"
            "کیفیت را انتخاب کنید (1-100):\n"
            "20 = کم حجم | 50 = نرمال | 80 = عالی"
        )
        return

    if chat_id in pending_compression and text.isdigit():
        quality = int(text)
        if not (1 <= quality <= 100):
            await event.reply("⚠️ عدد باید بین 1 تا 100 باشد.")
            return
            
        original_event = pending_compression.pop(chat_id)
        q_size = work_queue.qsize()
        msg = await event.reply(f"✅ ثبت شد. (نفر {q_size+1} در صف)")
        
        await work_queue.put({
            'event': original_event,
            'status_msg': msg,
            'quality': quality
        })

# ==========================================
# پنل ادمین
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id == ADMIN_ID:
        status = "🔴 قطع"
        try:
            if await user_client.is_user_authorized(): status = "🟢 متصل (iPhone 15)"
        except: pass
        await event.reply(f"وضعیت: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code ...`\n3️⃣ `/password ...`")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    ph = event.pattern_match.group(1).strip()
    try:
        if not user_client.is_connected(): await user_client.connect()
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await event.reply("✅ کد را بفرستید.")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **یوزربات متصل شد!**")
    except SessionPasswordNeededError: await event.reply("⚠️ رمز دارید: `/password ...`")
    except Exception as e: await event.reply(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/password (.+)'))
async def pass_h(event):
    if event.sender_id != ADMIN_ID: return
    try:
        await user_client.sign_in(password=event.pattern_match.group(1).strip())
        await event.reply("✅ ورود موفق.")
    except Exception as e: await event.reply(f"❌ {e}")

# ==========================================
# اجرا
# ==========================================
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Alive"))
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
    
    asyncio.create_task(queue_worker())
    
    tasks = [bot.run_until_disconnected()]
    if await user_client.is_user_authorized():
        tasks.append(user_client.run_until_disconnected())
    
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass