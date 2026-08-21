FROM python:3.11-slim

# Install system dependencies required by OpenCV and dlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and base tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Limit C++ build threads to prevent 8GB RAM spikes on Render
ENV MAKEFLAGS="-j1"
ENV CMAKE_BUILD_PARALLEL_LEVEL=1

# Install dlib individually
RUN pip install --no-cache-dir dlib

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Bind PORT for Render Web Services
ENV PORT=10000
EXPOSE 10000

# Run with Gunicorn production server (120s timeout for video processing)
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "app:app"]