FROM python:3.10-slim

# Install core OS dependencies needed for face-recognition runtime operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Secure and upgrade installer base configurations
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install an optimized, pre-compiled dlib stable production build wheel directly
RUN pip install --no-cache-dir dlib==19.24.2

# Copy local dependencies
COPY requirements.txt .

# Remove local cmake/dlib/face-recognition definitions from requirements.txt to avoid package collisions
RUN sed -i '/cmake/d; /dlib/d; /face[-_]recognition/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Securely bind face-recognition on top of our isolated dlib layer
RUN pip install --no-cache-dir face_recognition

# Copy over app assets
COPY . .

EXPOSE 7860

CMD ["python", "app.py"]
