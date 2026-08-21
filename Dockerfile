
FROM python:3.11-slim
 
# Runtime libs OpenCV links against. No build-essential / cmake needed —
# dlib is installed as a prebuilt wheel below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
 
WORKDIR /app
 
# setuptools is pinned because face_recognition_models still imports
# pkg_resources, which setuptools 81+ removed.
RUN pip install --no-cache-dir --upgrade pip wheel "setuptools<81"
 
# Prebuilt dlib wheel: turns a ~20 minute C++ compile into ~10 seconds
# and removes the 8 GB RAM spike during build.
RUN pip install --no-cache-dir "dlib-bin==19.24.6"
 
COPY requirements-aws.txt .
RUN pip install --no-cache-dir -r requirements-aws.txt
 
# --no-deps so pip does not pull the source `dlib` package back in on top
# of dlib-bin (they provide the same `dlib` module under different names).
RUN pip install --no-cache-dir --no-deps \
        face_recognition==1.3.0 \
        face_recognition_models==0.3.0
 
COPY . .
 
# Reference photos live on a mounted volume so they survive a redeploy.
ENV KNOWN_FACES_DIR=/data/known_faces \
    UPLOADS_DIR=/tmp/uploads \
    PORT=10000
 
RUN mkdir -p /data/known_faces /tmp/uploads
 
EXPOSE 10000
 
# 1 worker (each one loads its own copy of the face encodings), threads for
# concurrency, 300s timeout because video analysis blocks the request.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 300 app:app"]
 
