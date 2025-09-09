FROM python:3.10-slim

WORKDIR /app

# Update package lists and install system dependencies 
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    exiftool \
    poppler-utils \
    tesseract-ocr \
    libreoffice \
    default-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip

# Install core dependencies first
RUN pip install --no-cache-dir fastapi uvicorn python-multipart redis

# Install MarkItDown with all features (required for full document support)
RUN pip install --no-cache-dir markitdown[all]

# Copy the API code
COPY api.py .

# Expose the port
EXPOSE 8000

# Run the API
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
