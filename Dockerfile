FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn[standard] aiofiles python-multipart

# Copy app
COPY . .

# HF Spaces persistent storage is mounted at /data
# Symlinks are created at runtime by launcher.py

EXPOSE 7860

CMD ["python", "launcher.py"]
