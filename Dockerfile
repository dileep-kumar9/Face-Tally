FROM python:3.11-slim

# Runtime libraries required by OpenCV and FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# face_recognition_models still depends on pkg_resources.
RUN pip install --no-cache-dir --upgrade pip wheel "setuptools<81"

# Prebuilt dlib wheel
RUN pip install --no-cache-dir "dlib-bin==19.24.6"

# Application dependencies
COPY requirements-aws.txt .

RUN pip install --no-cache-dir -r requirements-aws.txt

# Install face recognition packages without reinstalling source dlib
RUN pip install --no-cache-dir --no-deps \
        face_recognition==1.3.0 \
        face_recognition_models==0.3.0

COPY . .

# Persistent known faces when /data is mounted as a Render Disk
ENV KNOWN_FACES_DIR=/data/known_faces \
    UPLOADS_DIR=/tmp/uploads \
    PORT=10000

RUN mkdir -p /data/known_faces /tmp/uploads

EXPOSE 10000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 300 app:app"]