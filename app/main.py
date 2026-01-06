"""
FastAPI application with routes and middleware.
Slim entry point - all logic extracted to modules.
"""
import os
import json
import uuid
import time
import shutil
import tempfile
import structlog
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from app.logging_config import logger, request_id_ctx
from app.config import JOB_EXPIRY
from app.models import URLRequest, SearchRequest, FetchRequest
from app.core.storage import storage, redis_client, RedisJobStorage
from app.core.cache import content_cache
from app.services.conversion import process_url, md
from app.services.streaming import stream_url_conversion
from app.services.deep_search import search_stream, fetch_stream
from app.core.cdp_queue import shutdown_cdp_pool


# Create FastAPI app
app = FastAPI(
    title="MarkItDown API",
    description="API for converting documents to Markdown",
    version="1.0.0"
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Add request ID to each request for tracking and logging."""
    # Get request ID from header or generate new one
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    request_id_ctx.set(request_id)

    # Bind request ID to structlog context for all logs in this request
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    # Add request ID to response headers
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ============================================================================
# ROUTES
# ============================================================================

@app.get("/")
def root():
    """Root endpoint with API info."""
    storage_type = "redis" if isinstance(storage, RedisJobStorage) else "in-memory"
    return {
        "service": "MarkItDown API",
        "version": "1.0.0",
        "storage": storage_type,
        "endpoints": [
            {"path": "/health", "method": "GET", "description": "Health check endpoint"},
            {"path": "/convert", "method": "GET/POST", "description": "Convert URL/file to Markdown"},
            {"path": "/status/{job_id}", "method": "GET", "description": "Check conversion job status"},
            {"path": "/convert-url", "method": "POST", "description": "Convert a URL to Markdown"},
            {"path": "/convert-url-stream", "method": "POST", "description": "Convert a URL to Markdown and stream paragraphs"},
            {"path": "/search", "method": "POST", "description": "Search, scrape, chunk, rerank with pagination (page, limit, top_k)"},
            {"path": "/fetch", "method": "POST", "description": "Fetch single URL with auto CDP fallback (url, query, top_k)"}
        ]
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    storage_type = "redis" if isinstance(storage, RedisJobStorage) else "in-memory"
    try:
        redis_client.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    return {
        "status": "healthy",
        "timestamp": time.time(),
        "redis": redis_status,
        "storage_type": storage_type
    }


@app.get("/convert")
async def convert_url_get(url: str, query: str = None):
    """
    Convert a URL to markdown via GET request with streaming response.
    This is the primary endpoint used by the deep search agent.
    """
    return StreamingResponse(
        stream_url_conversion(url, query),
        media_type="application/x-ndjson",
    )


@app.post("/convert")
async def convert_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Convert an uploaded file to markdown."""
    # Generate a job ID
    job_id = str(uuid.uuid4())

    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    temp_file_path = os.path.join(temp_dir, file.filename)

    try:
        # Save the uploaded file
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Store initial job status in Redis
        job_status = {
            "status": "processing",
            "filename": file.filename
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_status), ex=JOB_EXPIRY)

        # Process the file in the background
        background_tasks.add_task(process_file, temp_file_path, job_id)

        # Return the job ID
        return {
            "job_id": job_id,
            "status": "processing",
            "message": "File upload successful. Processing started."
        }
    except Exception as e:
        # Clean up on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


def process_file(file_path: str, job_id: str):
    """Process file conversion in background."""
    try:
        # Convert the file to markdown
        result = md.convert(file_path)

        # Store job result in Redis
        job_result = {
            "status": "completed",
            "markdown": result.markdown,
            "filename": os.path.basename(file_path)
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.info(f"Conversion completed for job {job_id}")
    except Exception as e:
        # Store error in Redis
        job_result = {
            "status": "failed",
            "error": str(e)
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.error(f"Conversion failed for job {job_id}: {str(e)}")
    finally:
        # Clean up the temporary file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            parent_dir = os.path.dirname(file_path)
            if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                shutil.rmtree(parent_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up temporary files: {str(e)}")


@app.post("/convert-url")
async def convert_url(background_tasks: BackgroundTasks, url_request: URLRequest):
    """Convert a URL to markdown (async with job ID)."""
    # Generate a job ID
    job_id = str(uuid.uuid4())

    try:
        # Store initial job status in Redis
        job_status = {
            "status": "processing",
            "filename": os.path.basename(url_request.url) or "url_content"
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_status), ex=JOB_EXPIRY)

        # Process the URL in the background (pass query for smart JS detection)
        background_tasks.add_task(process_url, url_request.url, job_id, url_request.query)

        # Return the job ID
        return {
            "job_id": job_id,
            "status": "processing",
            "message": "URL processing started."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/convert-url-stream")
async def convert_url_stream(url_request: URLRequest):
    """
    Convert a URL to markdown and stream back as JSON-delimited paragraphs.
    Each line contains a JSON object with type: metadata|batch|complete|error
    """
    return StreamingResponse(
        stream_url_conversion(url_request.url, url_request.query),
        media_type="application/x-ndjson",
    )


@app.post("/search")
async def search(request: SearchRequest):
    """
    Web search with scraping, chunking, and reranking.
    Agent-friendly endpoint with clean parameters.

    Args:
        query: Search query (required)
        page: SERP page number, 1-indexed (default: 1)
        limit: Results per SERP page (default: 10)
        top_k: Top chunks to return after reranking (default: 8)

    Streams JSON-delimited progress updates:
    - type: progress (status updates)
    - type: sources (list of scraped sources)
    - type: chunk (individual ranked chunks with scores)
    - type: done (completion with summary including page number)
    - type: error (if something fails)
    """
    return StreamingResponse(
        search_stream(
            query=request.query,
            page=request.page or 1,
            limit=request.limit,
            top_k=request.top_k
        ),
        media_type="application/x-ndjson",
    )


@app.post("/fetch")
async def fetch(request: FetchRequest):
    """
    Fetch a single URL with automatic CDP (browser) fallback.
    Use this when you need to dive deeper into a specific page.

    Args:
        url: URL to fetch (required)
        query: Optional query for relevance checking & focused reranking
        top_k: Top chunks if query provided (default: 10)

    Streams JSON-delimited progress updates:
    - type: progress (status updates)
    - type: chunk (content chunks, ranked if query provided)
    - type: done (completion with used_cdp flag)
    - type: error (if something fails)
    """
    return StreamingResponse(
        fetch_stream(
            url=request.url,
            query=request.query,
            top_k=request.top_k
        ),
        media_type="application/x-ndjson",
    )


@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Get job status by ID."""
    job_data = redis_client.get(f"job:{job_id}")

    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    return json.loads(job_data)


# ============================================================================
# LIFECYCLE EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Application startup."""
    logger.info("MarkItDown API starting up")
    storage_type = "Redis" if isinstance(storage, RedisJobStorage) else "in-memory"
    logger.info(f"Using {storage_type} storage")

    # Try to connect to Redis
    if isinstance(storage, RedisJobStorage):
        try:
            if storage.ping():
                logger.info(f"Connected to Redis at {storage.host}:{storage.port}")
            else:
                logger.error("Failed to connect to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown."""
    logger.info("api_shutdown_start")

    # Shutdown CDP worker pool
    await shutdown_cdp_pool()

    # Clear content cache
    if content_cache:
        content_cache.clear()

    logger.info("api_shutdown_complete")
