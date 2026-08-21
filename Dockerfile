FROM python:3.10-slim

# Install system runtime libraries (no slow compiler tools needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install the pre-compiled dlib wheel directly to bypass Render compilation constraints
RUN pip install --no-cache-dir https://github.com

# Copy dependencies and source code files
COPY requirements.txt .

# Remove dlib manually from requirements.txt dynamically to avoid rebuilding it
RUN sed -i '/dlib/d' requirements.txt && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["python", "app.py"]