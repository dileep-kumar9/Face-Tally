# Official pre-baked deep learning image that contains pre-installed dlib and python
FROM registry.hf.space/asigalov61-midi-visualizer:latest

USER root
WORKDIR /app

# Upgrade fundamental package installers
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy project dependency lists
COPY requirements.txt .

# Strip out local compiler constraints from requirements to maintain stability
RUN sed -i '/cmake/d; /dlib/d; /face[-_]recognition/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Securely bind the face_recognition layers cleanly over the pre-built image
RUN pip install --no-cache-dir face_recognition

# Copy all application assets
COPY . .

# Expose server port and execute
EXPOSE 7860
CMD ["python", "app.py"]
