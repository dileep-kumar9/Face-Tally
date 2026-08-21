FROM python:3.11-slim

# ------------------------------------------------------------
# Runtime libraries + FFmpeg
# FFmpeg is required for processing videos downloaded through
# yt-dlp and for broader video format support.
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ------------------------------------------------------------
# setuptools is pinned because face_recognition_models still
# imports pkg_resources.
# ------------------------------------------------------------
RUN pip install --no-cache-dir --upgrade pip wheel "setuptools<81"

# ------------------------------------------------------------
# Prebuilt dlib wheel.
# Avoids compiling dlib from source.
# ------------------------------------------------------------
RUN pip install --no-cache-dir "dlib-bin==19.24.6"

# ------------------------------------------------------------
# Install application dependencies.
# ------------------------------------------------------------
COPY requirements-aws.txt .
RUN pip install --no-cache-dir -r requirements-aws.txt

# ------------------------------------------------------------
# Install face_recognition packages without allowing pip to
# install source dlib over dlib-bin.
# ------------------------------------------------------------
RUN pip install --no-cache-dir --no-deps \
        face_recognition==1.3.0 \
        face_recognition_models==0.3.0

COPY . .

# ------------------------------------------------------------
# Storage configuration
# ------------------------------------------------------------
ENV KNOWN_FACES_DIR=/data/known_faces \
    UPLOADS_DIR=/tmp/uploads \
    PORT=10000

RUN mkdir -p /data/known_faces /tmp/uploads

EXPOSE 10000

# One worker because every worker loads its own face encodings.
# Threads allow multiple lightweight requests.
# 300 seconds allows video processing time.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 300 app:app"]