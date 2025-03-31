# MarkItDown API

A FastAPI-based service for converting various document formats to Markdown using the MarkItDown library.

## Features

- Convert uploaded files to Markdown
- Convert web URLs to Markdown
- Asynchronous processing with job status tracking
- Health check endpoint
- Automatic storage selection (Redis or in-memory)

## Requirements

- Python 3.10+
- FFmpeg, ExifTool, Poppler-utils, Tesseract OCR, and LibreOffice (for document conversion)
- Redis server (optional, recommended for production)

## Usage Instructions

### Option 1: Using Virtual Environment

This setup allows you to run the application directly on your machine with the most flexibility.

#### Prerequisites

**Install system dependencies:**

On Ubuntu/Debian:
```bash
sudo apt-get update && sudo apt-get install -y \
    ffmpeg \
    libmagic1 \
    exiftool \
    poppler-utils \
    tesseract-ocr \
    libreoffice
```

On macOS:
```bash
brew install ffmpeg libmagic exiftool poppler tesseract libreoffice
```

#### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/vadavision/markitdown-api.git
   cd markitdown-api
   ```

2. **Create and activate a virtual environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Python dependencies:**

   ```bash
   # For basic installation (will use in-memory storage if Redis is not available)
   pip install markitdown[all] fastapi uvicorn python-multipart
   
   # To use Redis storage (recommended for production)
   pip install markitdown[all] fastapi uvicorn python-multipart redis
   ```

4. **Run the API server:**

   **Without Redis (in-memory storage):**

   The application will automatically use in-memory storage if Redis is not available or if no Redis configuration is provided.

   ```bash
   # Start the server with default settings (will use in-memory storage)
   uvicorn api:app --host 0.0.0.0 --port 8000 --reload
   ```

   **With Redis (recommended for production):**

   First, start Redis server:
   ```bash
   # Install Redis if not already installed
   # Ubuntu/Debian: sudo apt-get install redis-server
   # macOS: brew install redis
   
   # Start Redis server in a separate terminal
   redis-server
   ```

   Then start the API with Redis configuration:
   ```bash
   # Configure Redis connection
   export REDIS_HOST=localhost  # On Windows: set REDIS_HOST=localhost
   export REDIS_PORT=6379       # On Windows: set REDIS_PORT=6379
   
   # Start the server
   uvicorn api:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Access the API:**

   Open your browser and navigate to [http://localhost:8000](http://localhost:8000)

### Option 2: Using Docker

This is useful for consistent environments and when you don't want to install dependencies directly on your system.

#### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/) (for running with Redis)

#### Steps

1. **Clone the repository:**

   ```bash
   git clone https://github.com/vadavision/markitdown-api.git
   cd markitdown-api
   ```

2. **Using Docker Compose with Redis (recommended for production):**

   Create a `docker-compose.yml` file:

   ```yaml
   version: '3'
   services:
     api:
       build: .
       ports:
         - "8000:8000"
       environment:
         - REDIS_HOST=redis
       depends_on:
         - redis
     redis:
       image: redis:alpine
       ports:
         - "6379:6379"
   ```

   Then run:

   ```bash
   docker-compose up
   ```

3. **Using Docker with in-memory storage (for development):**

   ```bash
   # Build the image
   docker build -t markitdown-api .
   
   # Run with non-existent Redis host to trigger in-memory fallback
   docker run -p 8000:8000 -e REDIS_HOST=non-existent-host markitdown-api
   ```

4. **Access the API:**

   Open your browser and navigate to [http://localhost:8000](http://localhost:8000)

## API Endpoints

- `GET /`: API information (includes storage type being used)
- `GET /health`: Health check endpoint (shows storage type and connection status)
- `POST /convert`: Convert a file to Markdown
- `POST /convert-url`: Convert a URL to Markdown
- `GET /status/{job_id}`: Check conversion job status

## Example Usage

### Convert a File

```bash
curl -X POST http://localhost:8000/convert \
  -H "Content-Type: multipart/form-data" \
  -F "file=@path/to/your/document.pdf"
```

### Convert a URL

```bash
curl -X POST http://localhost:8000/convert-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/document.html"}'
```

### Check Job Status

```bash
curl -X GET http://localhost:8000/status/your-job-id
```

## Storage Options

The application automatically selects the storage backend based on Redis availability:

### Redis Storage (Default for Production)

- **When used**: When valid Redis credentials are provided and connection is successful
- **Configuration**: Set `REDIS_HOST` and `REDIS_PORT` environment variables
- **Benefits**: Persistent storage, works across multiple instances, automatic expiration

### In-Memory Storage (Fallback for Development)

- **When used**: When Redis connection fails or is not configured
- **Benefits**: No additional dependencies required, simple setup
- **Limitations**: Job data is lost when the server restarts, not suitable for distributed systems

## Deployment

For more detailed production deployment information, please refer to the [DEPLOYMENT.md](DEPLOYMENT.md) file.

## License

[MIT License](LICENSE)