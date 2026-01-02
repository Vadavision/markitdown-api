from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from markitdown import MarkItDown
from pydantic import BaseModel
import tempfile
import os
import shutil
import logging
import uuid
import time
import requests
import json
import redis
import os
import re
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, Union, AsyncGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("markitdown-api")

# Bright Data Web Unlocker configuration
BRIGHTDATA_API_TOKEN = os.environ.get("BRIGHTDATA_API_TOKEN", "")
BRIGHTDATA_ZONE = os.environ.get("BRIGHTDATA_ZONE", "web_unlocker1")
BRIGHTDATA_API_URL = "https://api.brightdata.com/request"


def is_blocked_error(error: Exception) -> bool:
    """
    Check if the error indicates the request was blocked (403, captcha, etc.)
    """
    error_str = str(error).lower()
    # Check for common blocking indicators
    blocked_indicators = [
        "403", "forbidden",
        "captcha", "challenge",
        "blocked", "denied",
        "access denied", "bot",
        "429", "too many requests",
        "cloudflare", "security check"
    ]
    return any(indicator in error_str for indicator in blocked_indicators)


def fetch_via_brightdata(url: str) -> str:
    """
    Fetch URL content via Bright Data Web Unlocker API.
    Returns markdown content directly.
    """
    if not BRIGHTDATA_API_TOKEN:
        raise ValueError("BRIGHTDATA_API_TOKEN environment variable not set")

    headers = {
        "Authorization": f"Bearer {BRIGHTDATA_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "zone": BRIGHTDATA_ZONE,
        "url": url,
        "format": "raw",
        "data_format": "markdown"
    }

    logger.info(f"Fetching URL via Bright Data Web Unlocker: {url}")

    response = requests.post(BRIGHTDATA_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    markdown_content = response.text
    logger.info(f"Successfully fetched URL via Bright Data: {url} ({len(markdown_content)} chars)")

    return markdown_content


app = FastAPI(
    title="MarkItDown API", 
    description="API for converting documents to Markdown",
    version="1.0.0"
)

# Initialize MarkItDown
md = MarkItDown()

# Storage interface and implementations
class JobStorage(ABC):
    @abstractmethod
    def set(self, key: str, value: str, expiry: int = None) -> None:
        pass
    
    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        pass
    
    @abstractmethod
    def ping(self) -> bool:
        pass

# Redis storage implementation
class RedisJobStorage(JobStorage):
    def __init__(self, host: str, port: int):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        self.host = host
        self.port = port
        
    def set(self, key: str, value: str, expiry: int = None) -> None:
        self.client.set(key, value, ex=expiry)
        
    def get(self, key: str) -> Optional[str]:
        return self.client.get(key)
        
    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False

# In-memory storage implementation
class InMemoryJobStorage(JobStorage):
    def __init__(self):
        self.data: Dict[str, str] = {}
        self.expiry_times: Dict[str, float] = {}
        
    def set(self, key: str, value: str, expiry: int = None) -> None:
        self.data[key] = value
        if expiry:
            self.expiry_times[key] = time.time() + expiry
        
    def get(self, key: str) -> Optional[str]:
        # Check if key exists and not expired
        if key in self.data:
            if key in self.expiry_times and time.time() > self.expiry_times[key]:
                # Expired
                del self.data[key]
                del self.expiry_times[key]
                return None
            return self.data[key]
        return None
        
    def ping(self) -> bool:
        return True

# Job result expiration time (in seconds) - 24 hours
JOB_EXPIRY = 86400

# Initialize Redis client for backward compatibility
redis_host = os.environ.get("REDIS_HOST", "markitdown-redis")
redis_port = int(os.environ.get("REDIS_PORT", "6379"))

# Determine storage type based on Redis credentials
try:
    # Try to initialize Redis storage
    storage = RedisJobStorage(host=redis_host, port=redis_port)
    if storage.ping():
        logger.info(f"Using Redis storage at {redis_host}:{redis_port}")
        # For backward compatibility
        redis_client = storage.client
    else:
        logger.warning(f"Could not connect to Redis at {redis_host}:{redis_port}, falling back to in-memory storage")
        storage = InMemoryJobStorage()
        # For backward compatibility - create a dummy client that redirects to storage
        class DummyRedisClient:
            def __init__(self, storage):
                self.storage = storage
            
            def set(self, key, value, ex=None):
                return self.storage.set(key, value, expiry=ex)
            
            def get(self, key):
                return self.storage.get(key)
            
            def ping(self):
                return self.storage.ping()
        
        redis_client = DummyRedisClient(storage)
except Exception as e:
    logger.warning(f"Error initializing Redis: {str(e)}, using in-memory storage")
    storage = InMemoryJobStorage()
    # For backward compatibility
    class DummyRedisClient:
        def __init__(self, storage):
            self.storage = storage
        
        def set(self, key, value, ex=None):
            return self.storage.set(key, value, expiry=ex)
        
        def get(self, key):
            return self.storage.get(key)
        
        def ping(self):
            return self.storage.ping()
    
    redis_client = DummyRedisClient(storage)

# Model for URL request
class URLRequest(BaseModel):
    url: str

@app.get("/")
def root():
    storage_type = "redis" if isinstance(storage, RedisJobStorage) else "in-memory"
    return {
        "service": "MarkItDown API",
        "version": "1.0.0",
        "storage": storage_type,
        "endpoints": [
            {"path": "/health", "method": "GET", "description": "Health check endpoint"},
            {"path": "/convert", "method": "POST", "description": "Convert a file to Markdown"},
            {"path": "/status/{job_id}", "method": "GET", "description": "Check conversion job status"},
            {"path": "/convert-url", "method": "POST", "description": "Convert a URL to Markdown"},
            {"path": "/convert-url-stream", "method": "POST", "description": "Convert a URL to Markdown and stream paragraphs"}
        ]
    }

@app.get("/health")
def health_check():
    # Check Redis connection
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

def process_file(file_path: str, job_id: str):
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

def process_url(url: str, job_id: str):
    try:
        logger.info(f"Starting URL conversion for job {job_id}: {url}")

        # Update status to processing
        processing_status = {
            "status": "processing",
            "url": url,
            "filename": os.path.basename(url) or "url_content"
        }
        redis_client.set(f"job:{job_id}", json.dumps(processing_status), ex=JOB_EXPIRY)

        markdown_content = None
        used_brightdata = False

        # Try MarkItDown first
        try:
            result = md.convert_url(url)
            markdown_content = result.markdown
            logger.info(f"URL conversion completed via MarkItDown for job {job_id}")
        except Exception as e:
            # Check if this is a blocking error (403, captcha, etc.)
            if is_blocked_error(e) and BRIGHTDATA_API_TOKEN:
                logger.warning(f"Direct fetch blocked for {url}, trying Bright Data fallback: {str(e)}")
                try:
                    markdown_content = fetch_via_brightdata(url)
                    used_brightdata = True
                    logger.info(f"URL conversion completed via Bright Data for job {job_id}")
                except Exception as bd_error:
                    # Bright Data also failed, raise the original error
                    logger.error(f"Bright Data fallback also failed for {url}: {str(bd_error)}")
                    raise e
            else:
                # Not a blocking error or no Bright Data token, re-raise
                raise e

        # Store job result in Redis
        job_result = {
            "status": "completed",
            "markdown": markdown_content,
            "filename": os.path.basename(url) or "url_content",
            "source": "brightdata" if used_brightdata else "direct"
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)

    except requests.exceptions.HTTPError as e:
        # Handle HTTP errors specifically
        error_msg = f"HTTP error: {str(e)}"
        job_result = {
            "status": "failed",
            "error": error_msg,
            "url": url
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.error(f"URL conversion failed for job {job_id}: {error_msg}")

    except requests.exceptions.RequestException as e:
        # Handle other request errors
        error_msg = f"Request error: {str(e)}"
        job_result = {
            "status": "failed",
            "error": error_msg,
            "url": url
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.error(f"URL conversion failed for job {job_id}: {error_msg}")

    except Exception as e:
        # Handle any other errors
        error_msg = f"Conversion error: {str(e)}"
        job_result = {
            "status": "failed",
            "error": error_msg,
            "url": url
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.error(f"URL conversion failed for job {job_id}: {error_msg}")

def split_markdown_into_paragraphs(markdown: str) -> list[str]:
    """
    Split markdown into meaningful paragraphs/chunks for streaming.
    Preserves markdown structure while creating reasonable chunks.
    """
    if not markdown or not markdown.strip():
        return []
    
    # Split by double newlines (paragraph breaks)
    paragraphs = re.split(r'\n\s*\n', markdown.strip())
    
    chunks = []
    current_chunk = ""
    max_chunk_size = 2000  # Target chunk size
    min_chunk_size = 500   # Minimum chunk size before forcing split
    
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
            
        # If adding this paragraph would make chunk too large
        if current_chunk and len(current_chunk + "\n\n" + paragraph) > max_chunk_size:
            # Save current chunk if it's substantial
            if len(current_chunk) > min_chunk_size:
                chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                # Current chunk is too small, add this paragraph anyway
                current_chunk += "\n\n" + paragraph
        else:
            # Add paragraph to current chunk
            if current_chunk:
                current_chunk += "\n\n" + paragraph
            else:
                current_chunk = paragraph
    
    # Add final chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks

def create_smart_batches(chunks: list[str], max_batch_size: int = 32, max_tokens_per_batch: int = 8000) -> list[list[str]]:
    """
    Create intelligent batches for efficient API calls.
    Groups chunks into batches considering both count and token limits.
    """
    if not chunks:
        return []
    
    batches = []
    current_batch = []
    current_token_count = 0
    
    for chunk in chunks:
        # Rough token estimation: ~4 chars per token
        chunk_tokens = len(chunk) // 4
        
        # Check if adding this chunk would exceed limits
        if (len(current_batch) >= max_batch_size or 
            (current_batch and current_token_count + chunk_tokens > max_tokens_per_batch)):
            
            # Save current batch and start new one
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_token_count = 0
        
        # Add chunk to current batch
        current_batch.append(chunk)
        current_token_count += chunk_tokens
    
    # Add final batch
    if current_batch:
        batches.append(current_batch)
    
    return batches

async def stream_url_conversion(url: str) -> AsyncGenerator[str, None]:
    """
    Convert URL to markdown and stream back as paragraphs.
    Falls back to Bright Data Web Unlocker if direct fetch is blocked.
    """
    try:
        logger.info(f"Starting streaming conversion for URL: {url}")

        markdown = None
        used_brightdata = False

        # Try MarkItDown first
        try:
            result = md.convert_url(url)
            markdown = result.markdown
            logger.info(f"Streaming conversion via MarkItDown for URL: {url}")
        except Exception as e:
            # Check if this is a blocking error (403, captcha, etc.)
            if is_blocked_error(e) and BRIGHTDATA_API_TOKEN:
                logger.warning(f"Direct fetch blocked for {url}, trying Bright Data fallback: {str(e)}")
                try:
                    markdown = fetch_via_brightdata(url)
                    used_brightdata = True
                    logger.info(f"Streaming conversion via Bright Data for URL: {url}")
                except Exception as bd_error:
                    # Bright Data also failed, raise the original error
                    logger.error(f"Bright Data fallback also failed for {url}: {str(bd_error)}")
                    raise e
            else:
                # Not a blocking error or no Bright Data token, re-raise
                raise e

        if not markdown or not markdown.strip():
            yield json.dumps({"type": "error", "error": "No content extracted from URL"}) + "\n"
            return

        # Split into paragraphs/chunks
        chunks = split_markdown_into_paragraphs(markdown)

        # Create smart batches for efficient processing
        batches = create_smart_batches(chunks, max_batch_size=32, max_tokens_per_batch=8000)

        logger.info(f"Split markdown into {len(chunks)} chunks, organized into {len(batches)} batches")

        # Stream metadata first
        metadata = {
            "type": "metadata",
            "filename": os.path.basename(url) or "url_content",
            "total_chunks": len(chunks),
            "total_batches": len(batches),
            "source": "brightdata" if used_brightdata else "direct"
        }
        yield json.dumps(metadata) + "\n"

        # Stream each batch
        for batch_idx, batch in enumerate(batches):
            batch_data = {
                "type": "batch",
                "batch_index": batch_idx,
                "chunks": batch,
                "chunk_count": len(batch),
                "total_batches": len(batches)
            }
            yield json.dumps(batch_data) + "\n"

        # Stream completion marker
        completion = {
            "type": "complete",
            "total_chunks": len(chunks),
            "source": "brightdata" if used_brightdata else "direct"
        }
        yield json.dumps(completion) + "\n"

        logger.info(f"Completed streaming conversion for URL: {url} (source: {'brightdata' if used_brightdata else 'direct'})")

    except requests.exceptions.HTTPError as e:
        error_data = {
            "type": "error",
            "error": f"HTTP error: {str(e)}",
            "url": url
        }
        yield json.dumps(error_data) + "\n"
        logger.error(f"HTTP error in streaming conversion for {url}: {str(e)}")

    except requests.exceptions.RequestException as e:
        error_data = {
            "type": "error",
            "error": f"Request error: {str(e)}",
            "url": url
        }
        yield json.dumps(error_data) + "\n"
        logger.error(f"Request error in streaming conversion for {url}: {str(e)}")

    except Exception as e:
        error_data = {
            "type": "error",
            "error": f"Conversion error: {str(e)}",
            "url": url
        }
        yield json.dumps(error_data) + "\n"
        logger.error(f"Error in streaming conversion for {url}: {str(e)}")

@app.post("/convert")
async def convert_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
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

@app.post("/convert-url")
async def convert_url(background_tasks: BackgroundTasks, url_request: URLRequest):
    # Generate a job ID
    job_id = str(uuid.uuid4())
    
    try:
        # Store initial job status in Redis
        job_status = {
            "status": "processing",
            "filename": os.path.basename(url_request.url) or "url_content"
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_status), ex=JOB_EXPIRY)
        
        # Process the URL in the background
        background_tasks.add_task(process_url, url_request.url, job_id)
        
        # Return the job ID
        return {
            "job_id": job_id,
            "status": "processing",
            "message": "URL processing started."
        }
    except Exception as e:
        # Clean up on error
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/convert-url-stream")
async def convert_url_stream(url_request: URLRequest):
    """
    Convert a URL to markdown and stream back as JSON-delimited paragraphs.
    Each line contains a JSON object with type: metadata|chunk|complete|error
    """
    try:
        return StreamingResponse(
            stream_url_conversion(url_request.url),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    # Get job status from Redis
    job_data = redis_client.get(f"job:{job_id}")
    
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return json.loads(job_data)

# Cleanup old jobs periodically (Redis TTL handles this automatically now)
@app.on_event("startup")
async def startup_event():
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
    logger.info("MarkItDown API shutting down")
