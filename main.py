import os
import asyncio
import logging
import time
import math
import re
import shutil
import gc  # اضافه شده برای مدیریت رم
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
logger = logging.getLogger("ProCompressor")

# ایجاد پوشه‌ها
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(THUMB_PATH, exist_ok=True)

FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()
PORT = int(os.environ.get("PORT", 8080))

# ==========================================
# متغیرهای وضعیت
# ==========================================
work_queue = asyncio.Queue()
login_state = {}
pending_compression = {}

# تعریف کلاینت‌ها با تنظیمات ضد قطعی
bot = TelegramClient(BOT_SESSION, API_ID, API_HASH)

# ✅ اصلاح مهم: تنظیمات اتصال پایدار برای یوزربات
user_client = TelegramClient(
    USER_SESSION,
    API_ID,
    API_HASH,
    connection=ConnectionTcpFull, # مود اتصال پایدارتر
    device_model="iPhone 15 Pro",  # جعل مدل گوشی برای جلوگیری از بن
    system_version="17.4",
    app_version="10.8",
    lang_code="en",
    system_lang_code="en-US",
    connection_retries=None,      # تلاش نامحدود برای اتصال مجدد
    auto_reconnect=True,          # اتصال خودکار در صورت قطعی
    retry_delay=3                 # صبر 3 ثانیه‌ای بین تلاش‌ها
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
    except Exception:
        return None

async def update_progress(current, total, message_obj, start_time, action_text):
    now = time.time()
    # ✅ اصلاح: افزایش فاصله آپدیت به 5 ثانیه برای جلوگیری از FloodWait
    if now - start_time < 5 and current != total: return
    if total == 0: return

    percentage = current * 100 / total
    speed = current / (now - start_time) if (now - start_time) > 0 else 0
    elapsed_time = now - start_time
    estimated_total_time = elapsed_time / (percentage / 100) if percentage > 0 else 0
    time_left = estimated_total_time - elapsed_time
    
    filled = math.floor(percentage / 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    
    text = (
        f"{action_text}\n"
        f"**{bar} {round(percentage, 1)}%**\n\n"
        f"💾 حجم: `{humanbytes(current)}` / `{humanbytes(total)}`\n"
        f"🚀 سرعت: `{humanbytes(speed)}/s`\n"
        f"⏳ زمان باقیمانده: `{time_formatter(time_left)}`"
    )
    try: await message_obj.edit(text)
    except Exception: pass # نادیده گرفتن خطاها برای قطع نشدن برنامه

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
    
    last_update = 0
    
    while True:
        line = await process.stderr.readline()
        if not line: break
        line_txt = line.decode('utf-8', errors='ignore')
        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", line_txt)
        
        if time_match:
            now = time.time()
            if now - last_update > 5: # 5 ثانیه وقفه برای جلوگیری از بن
                h, m, s = map(float, time_match.groups())
                done_sec = h*3600 + m*60 + s
                percent_prog = (done_sec / duration) * 100 if duration else 0
                
                filled = math.floor(percent_prog / 10)
                bar = "▰" * filled + "▱" * (10 - filled)
                try:
                    await message_obj.edit(
                        f"⚙️ **در حال فشرده‌سازی (کیفیت {percentage}%)...**\n"
                        f"{bar} **{round(percent_prog, 1)}%**"
                    )
                except: pass
                last_update = now

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
            msg = event.message
            ts = int(time.time())
            
            file_ext = ".mp4"
            if msg.file and msg.file.name:
                _, ext = os.path.splitext(msg.file.name)
                if ext: file_ext = ext
            
            in_file = os.path.join(DOWNLOAD_PATH, f"in_{ts}{file_ext}")
            out_file = os.path.join(DOWNLOAD_PATH, f"out_{ts}.mp4")
            thumb_file = os.path.join(THUMB_PATH, f"thumb_{ts}.jpg")

            dl_start = time.time()
            await user_client.download_media(
                msg,
                in_file,
                progress_callback=lambda c, t: asyncio.create_task(
                    update_progress(c, t, status_msg, dl_start, "📥 **در حال دانلود فایل اصلی...**")
                )
            )

            duration = msg.file.duration or 1
            
            # فشرده سازی
            compress_success = await compress_engine(in_file, out_file, duration, quality_percent, status_msg)
            
            if compress_success:
                await status_msg.edit("🖼 **در حال ساخت تامنیل...**")
                final_thumb = await extract_thumbnail(out_file, thumb_file)
                
                up_start = time.time()
                old_sz = os.path.getsize(in_file)
                new_sz = os.path.getsize(out_file)
                reduction = ((old_sz - new_sz) / old_sz) * 100
                
                caption_text = (
                    f"✅ **عملیات با موفقیت انجام شد!**\n\n"
                    f"💎 **کیفیت درخواستی:** %{quality_percent}\n"
                    f"📦 **حجم اولیه:** `{humanbytes(old_sz)}`\n"
                    f"💾 **حجم نهایی:** `{humanbytes(new_sz)}`\n"
                    f"📉 **میزان کاهش:** `{round(reduction, 1)}%`\n\n"
                )

                await user_client.send_file(
                    event.chat_id,
                    out_file,
                    caption=caption_text,
                    thumb=final_thumb,
                    supports_streaming=True,
                    reply_to=event.id,
                    progress_callback=lambda c, t: asyncio.create_task(
                        update_progress(c, t, status_msg, up_start, "📤 **در حال آپلود به تلگرام...**")
                    )
                )
                
                await status_msg.delete()
            else:
                await status_msg.edit("❌ **خطا در پروسه فشرده‌سازی.**")
        
        except FloodWaitError as e:
            # مدیریت خطای فلود برای جلوگیری از دیسکانکت
            logger.warning(f"FloodWait: Waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            await status_msg.edit(f"⚠️ محدودیت تلگرام. صبر کنید: {e.seconds} ثانیه...")
        except Exception as e:
            logger.error(f"Work Error: {e}", exc_info=True)
            try: await status_msg.edit(f"❌ **خطا:**\n`{str(e)}`")
            except: pass
        finally:
            # پاکسازی کامل حافظه و فایل‌ها
            if in_file and os.path.exists(in_file): os.remove(in_file)
            if out_file and os.path.exists(out_file): os.remove(out_file)
            if thumb_file and os.path.exists(thumb_file): os.remove(thumb_file)
            
            # ✅ مدیریت حافظه رم
            gc.collect() 
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
            "🎥 **ویدیو دریافت شد!**\n\n"
            "لطفاً میزان کیفیت (فشرده‌سازی) را تعیین کنید:\n"
            "🔢 عددی بین **1 تا 100** بفرستید.\n\n"
            "▫️ **20** = حجم خیلی کم\n"
            "▫️ **50** = متعادل\n"
            "▫️ **80** = کیفیت بالا\n\n"
            "👇 عدد را بنویس:"
        )
        return

    if chat_id in pending_compression and text.isdigit():
        quality = int(text)
        if not (1 <= quality <= 100):
            await event.reply("⚠️ عدد باید بین 1 تا 100 باشد.")
            return
            
        original_event = pending_compression.pop(chat_id)
        q_size = work_queue.qsize()
        wait_msg = f"✅ **درخواست ثبت شد.**\n📊 کیفیت: **{quality}%**\n"
        wait_msg += f"⏳ نفر **{q_size + 1}** در صف..." if q_size > 0 else "🚀 شروع پردازش..."
            
        status_msg = await event.reply(wait_msg)
        await work_queue.put({'event': original_event, 'status_msg': status_msg, 'quality': quality})
        return
        
    if text.isdigit() and chat_id not in pending_compression:
        await event.reply("❌ اول ویدیو بفرستید.")

# ==========================================
# پنل ادمین
# ==========================================
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id == ADMIN_ID:
        status = "🔴 قطع"
        try:
            if await user_client.is_user_authorized(): status = "🟢 متصل (iPhone 15 Pro)"
        except: pass
        await event.reply(f"👑 **پنل مدیریت**\nوضعیت: {status}\n\n1️⃣ `/phone +98...`\n2️⃣ `/code 12345`\n3️⃣ `/password ...`")
    else:
        await event.reply("⛔️")

@bot.on(events.NewMessage(pattern='/phone (.+)'))
async def phone_h(event):
    if event.sender_id != ADMIN_ID: return
    ph = event.pattern_match.group(1).strip()
    msg = await event.reply("⏳ ...")
    try:
        if not user_client.is_connected(): await user_client.connect()
        s = await user_client.send_code_request(ph)
        login_state['phone'] = ph
        login_state['hash'] = s.phone_code_hash
        await msg.edit("✅ کد ارسال شد.")
    except Exception as e: await msg.edit(f"❌ {e}")

@bot.on(events.NewMessage(pattern='/code (.+)'))
async def code_h(event):
    if event.sender_id != ADMIN_ID: return
    code = event.pattern_match.group(1).strip()
    try:
        await user_client.sign_in(phone=login_state['phone'], code=code, phone_code_hash=login_state['hash'])
        await event.reply("✅ **یوزربات وصل شد!**")
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
    
    print("Userbot Init...")
    # اتصال با تنظیمات جدید
    await user_client.connect()
    
    asyncio.create_task(queue_worker())
    
    tasks = [bot.run_until_disconnected()]
    
    # لاجیک جدید برای زنده نگه داشتن سشن
    if await user_client.is_user_authorized():
        print("✅ Userbot Ready.")
        # ارسال خودکار پیام به خود کاربر (Saved Messages) برای زنده نگه داشتن سشن
        # این خط اختیاری است اما برای سرورهای ابری مفید است
        try:
            me = await user_client.get_me()
            print(f"Logged in as: {me.first_name}")
        except: pass
        
        tasks.append(user_client.run_until_disconnected())
    
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass