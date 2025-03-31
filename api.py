from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
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
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, Union

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("markitdown-api")

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
            {"path": "/convert-url", "method": "POST", "description": "Convert a URL to Markdown"}
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
        # Convert the URL directly to markdown using MarkItDown's URL capability
        result = md.convert_url(url)
        
        # Store job result in Redis
        job_result = {
            "status": "completed",
            "markdown": result.markdown,
            "filename": os.path.basename(url) or "url_content"
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.info(f"URL conversion completed for job {job_id}")
    except Exception as e:
        # Store error in Redis
        job_result = {
            "status": "failed",
            "error": str(e)
        }
        redis_client.set(f"job:{job_id}", json.dumps(job_result), ex=JOB_EXPIRY)
        logger.error(f"URL conversion failed for job {job_id}: {str(e)}")

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
