# Explicitly use stable Python 3.11 to support pre-compiled face recognition wheels
FROM python:3.11-slim

# Install system runtime libraries for image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade base packaging tools inside the container
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install the verified pre-compiled dlib wheel for Python 3.11 (No compiling required!)
RUN pip install --no-cache-dir https://github.com

# Copy dependencies configuration list
COPY requirements.txt .

# Strip out local cmake, dlib, and face-recognition lines to prevent installer collisions
RUN sed -i '/cmake/d; /dlib/d; /face[-_]recognition/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Securely install face_recognition over our working dlib layer
RUN pip install --no-cache-dir face_recognition

# Copy all application assets
COPY . .

# Expose server port and execute
EXPOSE 7860
CMD ["python", "app.py"]
