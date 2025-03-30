FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libmagic1 \
    exiftool \
    poppler-utils \
    tesseract-ocr \
    libreoffice \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install MarkItDown with all features
RUN pip install --no-cache-dir markitdown[all]

# Install FastAPI and Uvicorn
RUN pip install --no-cache-dir fastapi uvicorn python-multipart

# Copy the API code
COPY api.py .

# Expose the port
EXPOSE 8000

# Run the API
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
