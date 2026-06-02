FROM python:3.11-slim

WORKDIR /app

# System dependencies for OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./detection

# Pre-download YOLO model weights
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" || true

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "detection.main"]
