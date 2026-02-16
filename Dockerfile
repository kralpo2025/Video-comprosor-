# استفاده از پایتون 3.10 روی دبیان جدید (Bookworm) برای جلوگیری از ارورهای Apt
FROM python:3.10-slim-bookworm

# تنظیم ساعت سرور (اختیاری ولی خوب)
ENV TZ=Asia/Tehran

# نصب ملزومات سیستم و FFmpeg (حیاتی برای پخش موزیک)
# دستور clean برای کاهش حجم ایمیج است
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# تنظیم مسیر کاری
WORKDIR /app

# کپی کردن فایل‌ها
COPY . .

# نصب کتابخانه‌های پایتون
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

# اجرای ربات
CMD ["python3", "main.py"]
