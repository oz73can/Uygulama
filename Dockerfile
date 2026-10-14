FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir flask flask-cors yt-dlp gunicorn
CMD gunicorn -b 0.0.0.0:${PORT:-5000} -w 1 --threads 8 --timeout 900 app:app
