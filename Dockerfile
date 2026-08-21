# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install system dependencies required for OpenCV, dlib, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Upgrade pip, setuptools, and wheel
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install pre-compiled dlib wheel for Python 3.11
# Replace the URL below with the direct link to your pre-compiled .whl file
RUN pip install --no-cache-dir https://github.com/zhengbo-deng/dlib-wheels/raw/main/dlib-19.24.1-cp311-cp311-linux_x86_64.whl

# Copy dependencies configuration file
COPY requirements.txt .

# Install Python requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose the application port
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]