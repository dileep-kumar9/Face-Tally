FROM python:3.10-slim

# Install system dependencies required for OpenCV and dlib binaries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade fundamental package installers
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install the official pre-compiled dlib wheel binary straight from piwheels 
# This avoids compiling with C++ on Render entirely
RUN pip install --no-cache-dir --prefer-binary dlib==19.24.2

# Copy over dependencies list
COPY requirements.txt .

# Remove raw dlib from requirements.txt to prevent collision and install the rest
RUN sed -i '/dlib/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Copy all application assets
COPY . .

# Expose server port and execute
EXPOSE 7860
CMD ["python", "app.py"]
