# استفاده از نسخه جدید Bookworm که مخازن آن فعال است
FROM python:3.10-slim-bookworm

# تنظیم دایرکتوری کاری
WORKDIR /app

# نصب FFmpeg و Git (حیاتی برای پخش موزیک)
# دستورات را در یک خط ادغام کردیم تا بیلد سریع‌تر شود
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# کپی کردن فایل نیازمندی‌ها
COPY requirements.txt .

# نصب کتابخانه‌های پایتون
RUN pip3 install --no-cache-dir -r requirements.txt

# کپی کردن کل پروژه
COPY . .

# اجرای ربات
CMD ["python3", "main.py"]