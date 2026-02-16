# استفاده از پایتون نسخه 3.10 که بسیار پایدار است
FROM python:3.10-slim-buster

# نصب FFmpeg و Git (حیاتی برای پخش موزیک)
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y ffmpeg git

# تنظیم پوشه کاری
WORKDIR /app

# کپی کردن فایل‌های پروژه به سرور
COPY . /app

# نصب کتابخانه‌های پایتون
RUN pip3 install --no-cache-dir -r requirements.txt

# اجرای ربات
CMD ["python3", "main.py"]
