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

# Store conversion results for async processing
conversion_results = {}

# Model for URL request
class URLRequest(BaseModel):
    url: str

@app.get("/")
def root():
    return {
        "service": "MarkItDown API",
        "version": "1.0.0",
        "endpoints": [
            {"path": "/health", "method": "GET", "description": "Health check endpoint"},
            {"path": "/convert", "method": "POST", "description": "Convert a file to Markdown"},
            {"path": "/status/{job_id}", "method": "GET", "description": "Check conversion job status"},
            {"path": "/convert-url", "method": "POST", "description": "Convert a URL to Markdown"}
        ]
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": time.time()}

def process_file(file_path: str, job_id: str):
    try:
        # Convert the file to markdown
        result = md.convert(file_path)
        
        # Extract available attributes from the result
        # Note: Based on testing, DocumentConverterResult doesn't have a metadata attribute
        conversion_results[job_id] = {
            "status": "completed",
            "markdown": result.markdown,
            "filename": os.path.basename(file_path)
        }
        logger.info(f"Conversion completed for job {job_id}")
    except Exception as e:
        conversion_results[job_id] = {
            "status": "failed",
            "error": str(e)
        }
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
        
        # Extract available attributes from the result
        conversion_results[job_id] = {
            "status": "completed",
            "markdown": result.markdown,
            "filename": os.path.basename(url) or "url_content"
        }
        logger.info(f"URL conversion completed for job {job_id}")
    except Exception as e:
        conversion_results[job_id] = {
            "status": "failed",
            "error": str(e)
        }
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
        
        # Store initial job status
        conversion_results[job_id] = {
            "status": "processing",
            "filename": file.filename
        }
        
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
        # Store initial job status
        conversion_results[job_id] = {
            "status": "processing",
            "filename": os.path.basename(url_request.url) or "url_content"
        }
        
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
    if job_id not in conversion_results:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return conversion_results[job_id]

# Cleanup old jobs periodically (in a production environment, you'd want a more robust solution)
@app.on_event("startup")
async def startup_event():
    logger.info("MarkItDown API starting up")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("MarkItDown API shutting down")
