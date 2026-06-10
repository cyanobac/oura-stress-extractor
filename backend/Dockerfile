# Backend: FastAPI + OpenCV + Tesseract OCR
FROM python:3.12-slim

# Tesseract is a system package (pytesseract just shells out to it).
# libglib2.0-0 is needed by opencv-python-headless at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user and group
RUN addgroup --system --gid 1000 appgroup && \
    adduser --system --uid 1000 --gid 1000 --home /app --no-create-home appuser

# Set up data directory for SQLite with correct permissions so volume mounts inherit them
RUN mkdir -p /data && chown appuser:appgroup /data

COPY app ./app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
