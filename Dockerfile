# Uses an image that already contains pre-installed dlib, cmake, and python
FROM nativealpha/python-dlib:3.10-slim

WORKDIR /app

# Upgrade package installers
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy dependency configurations
COPY requirements.txt .

# Remove cmake, dlib, and face-recognition from requirements.txt dynamically
# to ensure it uses the pre-installed optimized system versions
RUN sed -i '/cmake/d; /dlib/d; /face[-_]recognition/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Explicitly install face_recognition over the pre-built dlib layers
RUN pip install --no-cache-dir face_recognition

# Copy the rest of your project files
COPY . .

EXPOSE 7860

CMD ["python", "app.py"]
